package com.example.mobileapp.core.session

import com.example.mobileapp.core.auth.IdentityProvider
import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.network.CoachCache
import com.example.mobileapp.core.network.CoachFetcher
import com.example.mobileapp.core.network.FitQuestApi
import com.example.mobileapp.core.network.LiveCoachStore
import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.network.models.CoachRetrievalInfo
import com.example.mobileapp.core.network.models.FitnessContextResponse
import com.example.mobileapp.core.run.ActiveRunAccountScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * The half of account isolation that no query can filter.
 *
 * Room rows are scoped by `ownerSubject`, so a read for the wrong account simply
 * returns nothing. The process-lifetime caches are not: they hold one account's
 * coach message in memory with nothing to filter on, so they have to be told
 * when the account changes. This is the test for that being wired up — the user
 * -visible symptom it prevents is signing in as A and reading B's coach message,
 * which no amount of DAO scoping would have stopped.
 *
 * It also covers the race that a `clear()` on its own does not: a coach response
 * already on the wire when the account changes arriving afterwards and
 * repopulating the cache it was just cleared from.
 */
class AccountScopeCoordinatorTest {

    private companion object {
        const val ACCOUNT_A = "11111111-1111-4111-8111-111111111111"
        const val ACCOUNT_B = "22222222-2222-4222-8222-222222222222"
    }

    private class MutableIdentity(initial: String? = null) : IdentityProvider {
        private val state = MutableStateFlow(initial)
        override fun currentSubject(): String? = state.value
        override val subject: Flow<String?> = state
        fun become(subject: String?) {
            state.value = subject
        }
    }

    /** Records every subject it is told about, so the wiring is observable. */
    private class RecordingRunScope : ActiveRunAccountScope {
        val notifications = mutableListOf<String?>()
        override fun onAccountChanged(currentSubject: String?) {
            notifications += currentSubject
        }
    }

    private class FakeRunSessionRepository : RunSessionRepository {
        override suspend fun getSyncedSessions(): List<RunSessionEntity> = emptyList()
        override suspend fun getUnsynced(): List<RunSessionEntity> = emptyList()
        override suspend fun saveSession(session: RunSessionEntity) = Unit
        override suspend fun markSynced(sessionId: String, xpEarned: Int) = Unit
        override suspend fun setPendingSyncPayload(sessionId: String, json: String) = Unit
        override suspend fun getSessionsBetween(start: Long, end: Long) = emptyList<RunSessionEntity>()
        override fun observeRecentSessions(limit: Int): Flow<List<RunSessionEntity>> = emptyFlow()
        override fun observeAllSessions(): Flow<List<RunSessionEntity>> = emptyFlow()
        override fun observeSessionCount(): Flow<Int> = emptyFlow()
        override fun observeLifetimeSteps(): Flow<Int?> = emptyFlow()
        override fun observeLifetimeDistance(): Flow<Double?> = emptyFlow()
    }

    private class FakeApi(private val behavior: suspend () -> CoachResponse) : FitQuestApi {
        override suspend fun getCoach(): CoachResponse = behavior()
        override suspend fun syncRunSession(payload: com.example.mobileapp.core.network.models.RunSyncPayload) =
            throw UnsupportedOperationException()
        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double, zoomLevel: Double
        ): com.example.mobileapp.core.network.models.MapViewportResponse =
            throw UnsupportedOperationException()
        override suspend fun getLeaderboard(limit: Int):
            com.example.mobileapp.core.network.models.LeaderboardResponse = throw UnsupportedOperationException()
        override suspend fun getRecommendations():
            com.example.mobileapp.core.network.models.RecommendationResponse = throw UnsupportedOperationException()
    }

    private fun coachResponse(message: String) = CoachResponse(
        generated_at = "2026-09-17T10:15:00.000000",
        message = message,
        grounded = true,
        context = FitnessContextResponse(
            user_id = ACCOUNT_B,
            total_lifetime_steps = 0,
            hexes_owned = 0,
            recent_captures_7d = 0,
            last_capture_at = null,
            total_defense_steps = 0
        ),
        recommendation = null,
        retrieval = CoachRetrievalInfo(retrieved_count = 1)
    )

    private suspend fun awaitUntil(timeoutMillis: Long = 2_000, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMillis
        while (System.currentTimeMillis() < deadline) {
            if (condition()) return
            delay(10)
        }
        fail("condition not met within ${timeoutMillis}ms")
    }

    @Test
    fun `changing the account clears the coach cache and the live slot`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        // One guard for the whole graph, exactly as AppModule wires it: the
        // coordinator opens the gate, and the cache and store below read the
        // same instance. Giving each its own would model a wiring mistake rather
        // than production, and would leave the gate shut when it matters.
        val guard = AccountScopeGuard()
        val cache = CoachCache(CoachFetcher(FakeApi { coachResponse("B's advice") }), FakeRunSessionRepository(), guard)
        val live = LiveCoachStore(guard)
        val runScope = RecordingRunScope()
        val coordinator = AccountScopeCoordinator(identity, cache, live, runScope, guard, scope)

        try {
            coordinator.start()
            awaitUntil { runScope.notifications.size == 1 }

            // B is signed in and has both a pulled and a pushed message on screen.
            cache.ensureLoaded()
            assertNotNull(cache.state.value)
            live.publish(coachResponse("B: push harder"))
            assertNotNull(live.message.value)

            identity.become(ACCOUNT_A)

            awaitUntil { cache.state.value == null && live.message.value == null }
            assertNull("Account A was shown Account B's coach message", cache.state.value)
            assertNull("Account A was shown Account B's pushed message", live.message.value)
            assertEquals(
                "The run controller was not told about the new account",
                listOf(ACCOUNT_B, ACCOUNT_A), runScope.notifications
            )
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun `a coach response that lands after an account change cannot repopulate the cache`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val onTheWire = CompletableDeferred<Unit>()
        val apiCalled = CompletableDeferred<Unit>()
        val guard = AccountScopeGuard()
        val cache = CoachCache(
            CoachFetcher(
                FakeApi {
                    apiCalled.complete(Unit)
                    onTheWire.await()
                    coachResponse("B's advice, requested before the switch")
                }
            ),
            FakeRunSessionRepository(),
            guard
        )
        val runScope = RecordingRunScope()
        val coordinator = AccountScopeCoordinator(identity, cache, LiveCoachStore(guard), runScope, guard, scope)

        try {
            coordinator.start()
            // Let the initial emission (and its clear) settle, so the generation
            // the fetch records below is the one the account change invalidates
            // — rather than racing the coordinator's own start-up clear.
            awaitUntil { runScope.notifications.size == 1 }

            val fetch = launch { cache.ensureLoaded() }
            apiCalled.await()              // the request is out, response not back

            identity.become(ACCOUNT_A)
            awaitUntil { runScope.notifications.size == 2 }

            onTheWire.complete(Unit)       // B's response arrives now
            fetch.join()
            delay(200)                     // give a wrong implementation time to land

            assertNull(
                "A response requested by Account B repopulated the cache after Account A signed in",
                cache.state.value
            )
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun `start is idempotent so the collector cannot be installed twice`() = runBlocking {
        val identity = MutableIdentity(ACCOUNT_B)
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val runScope = RecordingRunScope()
        val guard = AccountScopeGuard()
        val coordinator = AccountScopeCoordinator(
            identity,
            CoachCache(CoachFetcher(FakeApi { coachResponse("advice") }), FakeRunSessionRepository(), guard),
            LiveCoachStore(guard),
            runScope,
            guard,
            scope
        )

        try {
            coordinator.start()
            coordinator.start()
            coordinator.start()

            awaitUntil { runScope.notifications.isNotEmpty() }
            identity.become(ACCOUNT_A)
            awaitUntil { runScope.notifications.size == 2 }
            delay(100)

            assertEquals(
                "One account change produced more than one notification",
                listOf(ACCOUNT_B, ACCOUNT_A), runScope.notifications
            )
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun `the coordinator never deletes local data`() {
        // A structural assertion, not a behavioural one: the class holds no
        // repository and no DAO, so there is nothing it could delete with. This
        // is what keeps "clear the caches on account change" from quietly
        // becoming "wipe the previous account's history on account change" —
        // the requirement is that signing back in restores that account's data.
        val types = AccountScopeCoordinator::class.java.declaredFields.map { it.type.simpleName }
        assertTrue(
            "AccountScopeCoordinator must not hold anything that can delete rows: $types",
            types.none { it.contains("Dao") || it.contains("Repository") || it.contains("Database") }
        )
    }
}
