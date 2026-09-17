package com.example.mobileapp.core.data.local

import com.example.mobileapp.core.auth.IdentityProvider
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * Cross-account isolation, driven through the real repositories.
 *
 * ### The defect this is written against
 *
 * Sign in as B, record a run, sign out, sign in as A — and A was shown B's run,
 * B's stats and B's completed onboarding, because every table had exactly one
 * row set on the device and nothing asked who it belonged to. Observable on the
 * device as: the account that signs in second inherits the first one's history
 * and skips onboarding.
 *
 * ### What is real here and what is faked
 *
 * The repositories under test are the production [RoomRunSessionRepository],
 * [RoomUserProfileRepository] and [RoomActiveRunRepository] — the classes that
 * decide which account a read or write belongs to, and where the fix lives. The
 * DAOs behind them are in-memory fakes that honour their owner argument exactly
 * as Room's generated `*_Impl` classes do (`WHERE ownerSubject = :owner`), which
 * is what lets this run as a plain JVM test. `OwnerScopedDaoSourceTest` is what
 * proves the real DAOs actually carry that filter, since a fake can only prove
 * what the repository passes down.
 *
 * ### Why every test signs out and back in rather than just switching
 *
 * The device sequence is sign-out-then-sign-in, and it matters: signing out must
 * not be the thing that makes the data safe. If isolation depended on a cleanup
 * on the way out, an account switch that never passed through `SignedOut` would
 * leak — and [a degraded sign-out cannot expose the next account] pins that.
 */
class AccountScopedLocalDataTest {

    private companion object {
        const val ACCOUNT_A = "11111111-1111-4111-8111-111111111111"
        const val ACCOUNT_B = "22222222-2222-4222-8222-222222222222"
    }

    /** [IdentityProvider] over a settable subject, standing in for the session. */
    private class MutableIdentity(initial: String? = null) : IdentityProvider {
        private val state = MutableStateFlow(initial)

        override fun currentSubject(): String? = state.value

        override val subject: Flow<String?> = state

        /** Sign in as [subject], or out with null. */
        fun become(subject: String?) {
            state.value = subject
        }
    }

    /**
     * Room's generated DAOs return *live* queries: the flow re-emits whenever the
     * table changes. A fake returning a one-shot snapshot would make an observer
     * test pass for the wrong reason — or, as here, hang — so the fakes below
     * carry a revision counter and re-derive their result on every change, which
     * is what a test of "the observer stops delivering the old account's rows"
     * actually depends on.
     */
    private class Revisions {
        private val counter = MutableStateFlow(0)

        fun bump() {
            counter.value++
        }

        fun <T> observe(compute: () -> T): Flow<T> = counter.map { compute() }
    }

    private class FakeRunSessionDao : RunSessionDao {
        val rows = LinkedHashMap<String, RunSessionEntity>()
        private val revisions = Revisions()

        private fun owned(owner: String) = rows.values.filter { it.ownerSubject == owner }

        override suspend fun insertSession(session: RunSessionEntity) {
            rows[session.id] = session
            revisions.bump()
        }

        override suspend fun markSynced(owner: String, sessionId: String, xpEarned: Int) {
            val row = rows[sessionId] ?: return
            if (row.ownerSubject != owner) return
            rows[sessionId] = row.copy(xpEarned = xpEarned, isSynced = true, pendingSyncPayloadJson = null)
            revisions.bump()
        }

        override suspend fun setPendingSyncPayload(owner: String, sessionId: String, json: String) {
            val row = rows[sessionId] ?: return
            if (row.ownerSubject != owner) return
            rows[sessionId] = row.copy(pendingSyncPayloadJson = json)
            revisions.bump()
        }

        override suspend fun getUnsynced(owner: String): List<RunSessionEntity> =
            owned(owner).filter { !it.isSynced }.sortedBy { it.startedAt }

        override suspend fun getSyncedSessions(owner: String): List<RunSessionEntity> =
            owned(owner).filter { it.isSynced }

        override fun observeAllSessions(owner: String): Flow<List<RunSessionEntity>> =
            revisions.observe { owned(owner).sortedByDescending { it.endedAt } }

        override suspend fun getSessionsBetween(owner: String, start: Long, end: Long): List<RunSessionEntity> =
            owned(owner).filter { it.startedAt in start until end }

        override fun observeRecentSessions(owner: String, limit: Int): Flow<List<RunSessionEntity>> =
            revisions.observe { owned(owner).take(limit) }

        override fun observeSessionCount(owner: String): Flow<Int> =
            revisions.observe { owned(owner).size }

        override fun observeLifetimeSteps(owner: String): Flow<Int?> =
            revisions.observe { owned(owner).sumOf { it.totalSteps } }

        override fun observeLifetimeDistance(owner: String): Flow<Double?> =
            revisions.observe { owned(owner).sumOf { it.distanceMeters } }
    }

    private class FakeUserDao : UserDao {
        val rows = LinkedHashMap<String, UserProfileEntity>()
        private val revisions = Revisions()

        override suspend fun upsertProfile(profile: UserProfileEntity) {
            rows[profile.ownerSubject] = profile
            revisions.bump()
        }

        override suspend fun getProfileById(owner: String): UserProfileEntity? = rows[owner]

        override fun observeProfile(owner: String): Flow<UserProfileEntity?> =
            revisions.observe { rows[owner] }

        override suspend fun setOnboardingCompleted(owner: String) {
            rows[owner]?.let {
                rows[owner] = it.copy(isOnboardingCompleted = true)
                revisions.bump()
            }
        }

        override suspend fun updateDailyGoal(owner: String, goal: Int) {
            rows[owner]?.let {
                rows[owner] = it.copy(dailyStepGoal = goal)
                revisions.bump()
            }
        }
    }

    private class FakeActiveRunDao : ActiveRunDao {
        val rows = LinkedHashMap<String, ActiveRunEntity>()
        private val revisions = Revisions()

        override fun observeActiveRun(owner: String): Flow<ActiveRunEntity?> =
            revisions.observe { rows[owner] }

        override suspend fun getActiveRun(owner: String): ActiveRunEntity? = rows[owner]

        override suspend fun upsert(entity: ActiveRunEntity) {
            rows[entity.ownerSubject] = entity
            revisions.bump()
        }

        override suspend fun clear(owner: String) {
            rows.remove(owner)
            revisions.bump()
        }
    }

    private fun session(id: String, steps: Int = 1000, synced: Boolean = false) = RunSessionEntity(
        id = id, startedAt = 0L, endedAt = 0L, durationSeconds = 0L,
        totalSteps = steps, distanceMeters = 0.0, caloriesBurned = 0,
        capturedHexCount = 0, capturedHexIdsJson = "", xpEarned = 0, isSynced = synced
    )

    private suspend fun awaitUntil(timeoutMillis: Long = 2_000, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMillis
        while (System.currentTimeMillis() < deadline) {
            if (condition()) return
            delay(10)
        }
        fail("condition not met within ${timeoutMillis}ms")
    }

    // ── Runs ─────────────────────────────────────────────────────────────────

    @Test
    fun `a run written by one account is not visible to the next`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val dao = FakeRunSessionDao()
        val repository = RoomRunSessionRepository(dao, identity)

        repository.saveSession(session("run-b", steps = 4321))
        assertEquals(1, repository.observeAllSessions().first().size)

        // Sign out, then in as A — the exact device sequence.
        identity.become(null)
        identity.become(ACCOUNT_A)

        assertEquals(
            "Account A was shown Account B's run history",
            emptyList<RunSessionEntity>(), repository.observeAllSessions().first()
        )
        assertEquals(emptyList<RunSessionEntity>(), repository.getUnsynced())
        assertEquals(emptyList<RunSessionEntity>(), repository.getSyncedSessions())
        assertEquals(0, repository.observeSessionCount().first())
        assertEquals(0, repository.observeLifetimeSteps().first() ?: 0)
    }

    @Test
    fun `the run remains available to the account that recorded it`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val repository = RoomRunSessionRepository(FakeRunSessionDao(), identity)

        repository.saveSession(session("run-b", steps = 4321))

        // A comes and goes. Nothing about A's session may touch B's history.
        identity.become(ACCOUNT_A)
        repository.saveSession(session("run-a", steps = 10))
        identity.become(null)
        identity.become(ACCOUNT_B)

        val b = repository.observeAllSessions().first()
        assertEquals("B lost its own run", listOf("run-b"), b.map { it.id })
        assertEquals(4321, b.single().totalSteps)

        // And A's run is A's alone.
        identity.become(ACCOUNT_A)
        assertEquals(listOf("run-a"), repository.observeAllSessions().first().map { it.id })
    }

    @Test
    fun `a run is filed under the signed-in account, not the one the caller named`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_A)
        val dao = FakeRunSessionDao()
        val repository = RoomRunSessionRepository(dao, identity)

        // The capture screen builds the entity and has no business knowing which
        // account is signed in, so it passes the constructor default. The
        // repository must stamp the real subject over whatever it receives.
        repository.saveSession(session("run-1").copy(ownerSubject = ACCOUNT_B))

        assertEquals(ACCOUNT_A, dao.rows.getValue("run-1").ownerSubject)
        assertTrue(
            "The row was also filed under the account the caller named",
            dao.rows.values.none { it.ownerSubject == ACCOUNT_B }
        )
    }

    @Test
    fun `a write with no signed-in account is refused rather than filed under a placeholder`() = runBlocking {
        val identity = MutableIdentity(null)
        val dao = FakeRunSessionDao()
        val repository = RoomRunSessionRepository(dao, identity)

        repository.saveSession(session("orphan"))

        assertTrue("An unowned row was written to the device", dao.rows.isEmpty())
        repository.markSynced("orphan", 100)
        repository.setPendingSyncPayload("orphan", "{}")
        assertTrue(dao.rows.isEmpty())
    }

    // ── Profile and onboarding ───────────────────────────────────────────────

    @Test
    fun `profiles and onboarding state are per account`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val dao = FakeUserDao()
        val repository = RoomUserProfileRepository(dao, identity)

        repository.completeOnboarding()
        repository.recordCompletedSession(
            steps = 12_000, distanceMeters = 9_000.0, calories = 480, hexCount = 3, xp = 250
        )
        val b = repository.getProfile()
        assertTrue(b.isOnboardingCompleted)
        assertEquals(12_000, b.totalLifetimeSteps)
        assertEquals(2, b.level)

        identity.become(ACCOUNT_A)
        val a = repository.getProfile()

        assertTrue(
            "Account A inherited Account B's completed onboarding and skipped it",
            !a.isOnboardingCompleted
        )
        assertEquals("Account A was shown Account B's lifetime steps", 0, a.totalLifetimeSteps)
        assertEquals(1, a.level)
        assertEquals("Account A was shown Account B's username", "Scout", a.username)

        // A onboards for itself; B's answer is untouched.
        repository.completeOnboarding()
        identity.become(ACCOUNT_B)
        assertTrue(repository.getProfile().isOnboardingCompleted)
        identity.become(ACCOUNT_A)
        assertTrue(repository.getProfile().isOnboardingCompleted)

        // Two rows, one per account — not one row rewritten twice.
        assertEquals(setOf(ACCOUNT_A, ACCOUNT_B), dao.rows.keys)
    }

    @Test
    fun `a profile read with no signed-in account persists nothing`() = runBlocking {
        val dao = FakeUserDao()
        val repository = RoomUserProfileRepository(dao, MutableIdentity(null))

        val placeholder = repository.getProfile()

        assertTrue("A profile owned by nobody was written", dao.rows.isEmpty())
        assertEquals(LEGACY_UNOWNED_SUBJECT, placeholder.ownerSubject)
    }

    // ── Active run ───────────────────────────────────────────────────────────

    @Test
    fun `an in-progress run does not leak to the next account and is not destroyed`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val dao = FakeActiveRunDao()
        val repository = RoomActiveRunRepository(dao, identity)

        repository.saveActiveRun(ActiveRunEntity(runId = "live-b", startedAtMillis = 1L, sessionSteps = 900))

        identity.become(ACCOUNT_A)
        assertNull("Account A was offered Account B's unfinished run", repository.getActiveRun())

        // A finishing its own run must not delete the checkpoint B left behind —
        // that row is how B gets its run back.
        repository.clearActiveRun()
        assertNotNull("Account A's clear deleted Account B's checkpoint", dao.rows[ACCOUNT_B])

        identity.become(ACCOUNT_B)
        val recovered = repository.getActiveRun()
        assertEquals("B could not recover its own run", "live-b", recovered?.runId)
        assertEquals(900, recovered?.sessionSteps)
    }

    @Test
    fun `each account can hold its own checkpoint at the same time`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val dao = FakeActiveRunDao()
        val repository = RoomActiveRunRepository(dao, identity)

        repository.saveActiveRun(ActiveRunEntity(runId = "live-b", startedAtMillis = 1L))
        identity.become(ACCOUNT_A)
        repository.saveActiveRun(ActiveRunEntity(runId = "live-a", startedAtMillis = 2L))

        assertEquals(setOf(ACCOUNT_A, ACCOUNT_B), dao.rows.keys)
        assertEquals("live-a", repository.getActiveRun()?.runId)
        identity.become(ACCOUNT_B)
        assertEquals("live-b", repository.getActiveRun()?.runId)
    }

    // ── Observers ────────────────────────────────────────────────────────────

    @Test
    fun `an open observer stops delivering the previous account's rows`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val dao = FakeRunSessionDao()
        val repository = RoomRunSessionRepository(dao, identity)
        repository.saveSession(session("run-b"))

        val delivered = mutableListOf<List<String>>()
        val job = launch {
            repository.observeAllSessions().collect { sessions ->
                delivered += sessions.map { it.id }
            }
        }

        awaitUntil { delivered.isNotEmpty() }
        assertEquals(listOf("run-b"), delivered.last())

        // The account changes while the screen that opened this collector is
        // still alive. The old DAO flow only ever knew the owner it was given,
        // so without re-subscribing it would keep emitting B's rows to A.
        identity.become(ACCOUNT_A)
        awaitUntil { delivered.last().isEmpty() }

        repository.saveSession(session("run-a"))
        awaitUntil { delivered.last() == listOf("run-a") }
        assertEquals(
            "Account B's run was delivered after the account changed",
            listOf("run-a"), delivered.last()
        )
        job.cancel()
    }

    @Test
    fun `a degraded sign-out cannot expose the next account`() = runBlocking {
        // The transition B -> A observed as a single step, with no SignedOut in
        // between. Isolation must not depend on cleanup happening on the way out.
        val identity = MutableIdentity(ACCOUNT_B)
        val dao = FakeRunSessionDao()
        val repository = RoomRunSessionRepository(dao, identity)
        repository.saveSession(session("run-b"))
        repository.saveSession(session("run-b2"))

        identity.become(ACCOUNT_A)

        assertEquals(emptyList<RunSessionEntity>(), repository.observeAllSessions().first())
        assertEquals(emptyList<RunSessionEntity>(), repository.getUnsynced())
        assertEquals(2, dao.rows.size)
    }

    @Test
    fun `observeRecentSessions and lifetime totals follow the account`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val repository = RoomRunSessionRepository(FakeRunSessionDao(), identity)
        repository.saveSession(session("b1", steps = 100).copy(isSynced = true))
        repository.saveSession(session("b2", steps = 250).copy(isSynced = true))

        assertEquals(350, repository.observeLifetimeSteps().first())
        assertEquals(listOf("b1", "b2"), repository.getSyncedSessions().map { it.id })

        identity.become(ACCOUNT_A)
        assertEquals(0, repository.observeLifetimeSteps().first() ?: 0)
        assertEquals(emptyList<RunSessionEntity>(), repository.getSyncedSessions())
        assertTrue(repository.observeRecentSessions(5).first().isEmpty())
    }

    @Test
    fun `observeProfile follows the account`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val repository = RoomUserProfileRepository(FakeUserDao(), identity)
        repository.completeOnboarding()

        assertTrue(repository.observeProfile().first()?.isOnboardingCompleted == true)

        identity.become(ACCOUNT_A)
        // A has no row yet, so the observer emits null — not B's profile.
        assertNull(repository.observeProfile().first())

        identity.become(null)
        assertNull("A signed-out observer still holds a profile", repository.observeProfile().first())
    }

    @Test
    fun `observeActiveRun follows the account`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val dao = FakeActiveRunDao()
        val repository = RoomActiveRunRepository(dao, identity)
        repository.saveActiveRun(ActiveRunEntity(runId = "live-b", startedAtMillis = 1L))

        assertEquals("live-b", repository.observeActiveRun().first()?.runId)

        identity.become(ACCOUNT_A)
        assertNull(repository.observeActiveRun().first())
    }
}
