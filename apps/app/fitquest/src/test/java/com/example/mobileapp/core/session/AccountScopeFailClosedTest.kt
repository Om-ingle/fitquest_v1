package com.example.mobileapp.core.session

import com.example.mobileapp.core.auth.IdentityProvider
import com.example.mobileapp.core.capture.HexCaptureSnapshot
import com.example.mobileapp.core.capture.RunSessionEngine
import com.example.mobileapp.core.data.local.ActiveRunEntity
import com.example.mobileapp.core.data.local.ActiveRunRepository
import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.network.CoachCache
import com.example.mobileapp.core.network.CoachFetcher
import com.example.mobileapp.core.network.FitQuestApi
import com.example.mobileapp.core.network.LiveCoachStore
import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.network.models.CoachRetrievalInfo
import com.example.mobileapp.core.network.models.FitnessContextResponse
import com.example.mobileapp.core.network.models.Recommendation
import com.example.mobileapp.core.run.ActiveRunAccountScope
import com.example.mobileapp.core.run.ActiveRunController
import com.example.mobileapp.core.run.RunServiceLauncher
import com.example.mobileapp.core.run.RunTiming
import com.example.mobileapp.core.run.RunTrackingService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * The fail-closed half of account isolation: what the app does when the control
 * that enforces isolation is **not running**.
 *
 * ### The failure this is written against
 *
 * `AccountScopeCoordinator` is the only thing that clears the three
 * process-lifetime account-scoped surfaces when the signed-in account changes.
 * A shipped build registered only the concrete `ForegroundRunServiceLauncher`,
 * so `ActiveRunController` could not be constructed, so the coordinator could not
 * be constructed, so `FitQuestApp` caught the exception and logged it. The app
 * launched, looked healthy, and ran with the isolation control entirely absent —
 * and the first symptom was one account being able to see another's data.
 *
 * The fix is not a better log line. It is that the surfaces no longer hold data
 * by default: [AccountScopeGuard] starts closed, they refuse to acquire anything
 * while it is closed, and only the coordinator opens it. So the tests here ask
 * the question the old design could not answer — *what is the state of the world
 * when the coordinator never runs at all?* — and require the answer to be
 * "empty", not "stale".
 *
 * The other direction matters just as much and is tested here too: a gate that
 * never opens is a broken feature. Once the coordinator is watching, all three
 * surfaces must work exactly as before, and when it stops the gate must shut
 * again rather than leaving them open with nothing behind them.
 */
class AccountScopeFailClosedTest {

    private companion object {
        const val ACCOUNT_B = "22222222-2222-4222-8222-222222222222"
    }

    // ── fakes ───────────────────────────────────────────────────────────────

    private class MutableIdentity(initial: String? = null) : IdentityProvider {
        private val state = MutableStateFlow(initial)
        override fun currentSubject(): String? = state.value
        override val subject: Flow<String?> = state
        fun become(subject: String?) {
            state.value = subject
        }
    }

    private class RecordingRunScope : ActiveRunAccountScope {
        override fun onAccountChanged(currentSubject: String?) = Unit
    }

    private class FakeApi(private val behavior: suspend () -> CoachResponse) : FitQuestApi {
        var getCoachCalls = 0
            private set

        override suspend fun getCoach(): CoachResponse {
            getCoachCalls++
            return behavior()
        }

        override suspend fun syncRunSession(payload: com.example.mobileapp.core.network.models.RunSyncPayload) =
            throw UnsupportedOperationException()

        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double, zoomLevel: Double
        ): com.example.mobileapp.core.network.models.MapViewportResponse =
            throw UnsupportedOperationException()

        override suspend fun getLeaderboard(limit: Int):
            com.example.mobileapp.core.network.models.LeaderboardResponse =
            throw UnsupportedOperationException()

        override suspend fun getRecommendations():
            com.example.mobileapp.core.network.models.RecommendationResponse =
            throw UnsupportedOperationException()
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

    private class FakeActiveRunRepository : ActiveRunRepository {
        val saved = mutableListOf<ActiveRunEntity>()
        var clearCalls = 0
            private set

        override fun observeActiveRun(): Flow<ActiveRunEntity?> = MutableStateFlow(saved.lastOrNull())
        override suspend fun getActiveRun(): ActiveRunEntity? = saved.lastOrNull()
        override suspend fun saveActiveRun(entity: ActiveRunEntity) {
            saved += entity
        }

        override suspend fun clearActiveRun() {
            clearCalls++
            saved.clear()
        }
    }

    private class FakeEngine : RunSessionEngine {
        private val _state = MutableStateFlow(HexCaptureSnapshot())
        override val state: StateFlow<HexCaptureSnapshot> = _state

        fun beginTracking(steps: Int) {
            _state.value = HexCaptureSnapshot(isTracking = true, sessionSteps = steps)
        }

        override fun discardSession() {
            _state.value = _state.value.copy(isTracking = false, sessionSteps = 0)
        }
    }

    private class RecordingLauncher : RunServiceLauncher {
        val actions = mutableListOf<String>()
        override fun launch(action: String) {
            actions += action
        }
    }

    private fun coachResponse(message: String = "advice") = CoachResponse(
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
        recommendation = Recommendation(
            type = "STARTER",
            title = "Start your territory",
            description = "Walk 1,000 steps to claim your very first hex.",
            target_metric = "steps",
            target_value = 1000,
            difficulty = "easy",
            reason_code = "COLD_START",
            reason = "hexes_owned=0 and total_lifetime_steps=0"
        ),
        retrieval = CoachRetrievalInfo(retrieved_count = 1)
    )

    private fun timing() = RunTiming(startedAtMillis = 1_000L, pausedAccumulatedMillis = 0L)

    /**
     * The whole graph on one guard, wired the way `AppModule` wires it. [start]
     * decides whether a coordinator is running at all — which is the variable
     * under test.
     */
    private inner class Graph(started: Boolean) {
        val guard = AccountScopeGuard()
        val identity = MutableIdentity(ACCOUNT_B)
        val api = FakeApi { coachResponse() }
        val cache = CoachCache(CoachFetcher(api), FakeRunSessionRepository(), guard)
        val live = LiveCoachStore(guard)
        val runRepository = FakeActiveRunRepository()
        val engine = FakeEngine()
        val launcher = RecordingLauncher()
        val runController = ActiveRunController(
            runRepository, engine, identity, launcher, guard
        )
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        private val coordinator = AccountScopeCoordinator(
            identity, cache, live, runController, guard, scope
        )

        init {
            // The one variable under test: is a coordinator running or not?
            if (started) coordinator.start()
        }

        fun startRun() {
            engine.beginTracking(steps = 500)
            runController.startRun("run-1", timing())
        }

        fun dispose() = scope.cancel()
    }

    private suspend fun awaitUntil(timeoutMillis: Long = 2_000, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMillis
        while (System.currentTimeMillis() < deadline) {
            if (condition()) return
            delay(10)
        }
        fail("condition not met within ${timeoutMillis}ms")
    }

    // ── the failure mode ────────────────────────────────────────────────────

    @Test
    fun `the gate is closed until something opens it`() {
        // The load-bearing default. Everything else in this file follows from
        // "not started" meaning "shut": if this flipped, a coordinator that never
        // ran would protect nothing.
        assertFalse(
            "a fresh AccountScopeGuard must be closed — the safe state has to be " +
                "the default, or forgetting to start the coordinator leaks again",
            AccountScopeGuard().isActive()
        )
    }

    @Test
    fun `a coordinator that never starts leaves every account-scoped surface empty`() = runBlocking {
        // The exact shape of the shipped defect: the coordinator could not be
        // constructed, so start() never ran. Before this change all three
        // surfaces would happily fill up and then carry their contents across an
        // account change with nothing to clear them.
        val g = Graph(started = false)

        try {
            assertFalse("no coordinator is running, so the gate must be shut", g.guard.isActive())

            g.cache.ensureLoaded()
            assertEquals("a closed cache must not even ask the network", 0, g.api.getCoachCalls)
            assertNull("a closed cache must not hold a coach message", g.cache.state.value)

            g.live.publish(coachResponse("pushed while unprotected"))
            assertNull("a closed store must not accept a push", g.live.message.value)

            g.startRun()
            assertFalse("a closed controller must not start a run", g.runController.isActive)
            assertEquals(
                "refusing a run must not leave a foreground service running for it",
                emptyList<String>(), g.launcher.actions
            )
        } finally {
            g.dispose()
        }
    }

    // ── …and that it is still a working feature when it does start ───────────

    @Test
    fun `a started coordinator opens the gate and all three surfaces work`() = runBlocking {
        // The counterweight. A gate that never opens would also pass the test
        // above, and would be a broken app rather than a safe one.
        val g = Graph(started = true)

        try {
            assertTrue("start() must open the gate", g.guard.isActive())

            g.cache.ensureLoaded()
            assertEquals("the cache must fetch once the control is live", 1, g.api.getCoachCalls)
            assertTrue(
                "the cache must hold a coach message once the control is live, " +
                    "but held ${g.cache.state.value}",
                g.cache.state.value is CoachFetcher.Outcome.Success
            )

            g.live.publish(coachResponse("live"))
            assertEquals("live", g.live.message.value?.message)

            g.startRun()
            assertTrue("the run must start once the control is live", g.runController.isActive)
        } finally {
            g.dispose()
        }
    }

    // ── the gate closes again when the watching stops ────────────────────────

    @Test
    fun `when the collector stops the gate shuts and the surfaces are emptied again`() = runBlocking {
        // The gate is meant to be open exactly while something is watching. A
        // collector that dies leaves nobody to react to an account change, so
        // leaving the gate open — and the data in place — would reintroduce the
        // original defect by a different route than the one that shipped.
        val g = Graph(started = true)

        g.cache.ensureLoaded()
        g.live.publish(coachResponse("live"))
        g.startRun()
        assertTrue(g.guard.isActive())
        assertTrue(g.runController.isActive)

        g.dispose()   // the collector's scope goes away

        awaitUntil { !g.guard.isActive() }
        assertNull("a stopped control must not leave a coach message behind", g.cache.state.value)
        assertNull("a stopped control must not leave a pushed message behind", g.live.message.value)
        assertFalse("a stopped control must not leave a run live", g.runController.isActive)
        assertEquals(
            "the run was dropped, so its foreground service must have been stopped",
            listOf(RunTrackingService.ACTION_START_RUN, RunTrackingService.ACTION_STOP_RUN),
            g.launcher.actions
        )
    }

    @Test
    fun `a run dropped because the control stopped keeps its checkpoint`() = runBlocking {
        // Same guarantee as an account switch, for the same reason: the run
        // belongs to the account that started it, and the checkpoint is how that
        // account gets it back. Losing the control must not cost the user their
        // walk — the safe direction is "stop showing it", never "delete it".
        val g = Graph(started = true)

        g.startRun()
        assertTrue(g.runController.isActive)

        g.dispose()
        awaitUntil { !g.runController.isActive }

        assertFalse(
            "teardown caused by losing the control must not be treated as a " +
                "finished run — a finish clears the checkpoint",
            g.runController.shouldClearCheckpointOnStop()
        )
        assertEquals(
            "the persisted checkpoint must not be cleared by the control stopping",
            0, g.runRepository.clearCalls
        )
    }

    // ── clearing is never gated ─────────────────────────────────────────────

    @Test
    fun `clearing still works while the gate is shut`() = runBlocking {
        // Only *acquiring* data is gated. Emptying is always the safe direction,
        // and gating it would mean a surface that somehow holds data could not be
        // emptied — the opposite of what this is for.
        val g = Graph(started = true)
        g.cache.ensureLoaded()
        g.live.publish(coachResponse("live"))
        assertTrue(g.live.message.value != null)

        g.guard.setActive(false)   // the control goes away, the data does not
        g.cache.clear()
        g.live.clear()

        assertNull(g.cache.state.value)
        assertNull(g.live.message.value)
        g.dispose()
    }
}
