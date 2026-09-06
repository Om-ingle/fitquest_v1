package com.example.mobileapp.core.network

import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.network.models.CoachRetrievalInfo
import com.example.mobileapp.core.network.models.FitnessContextResponse
import com.example.mobileapp.core.network.models.Recommendation
import com.example.mobileapp.core.tts.CoachingSpeechController
import com.example.mobileapp.core.tts.CoachingSpeechGate
import com.example.mobileapp.core.tts.TtsSynthesizer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M8.5 — case D: a genuinely newly credited run with NO live push. The synced
 * signature advances, the pull path produces a fresh response for the new
 * context, and that fresh pull is what the Home card shows (outranking the
 * process-lifetime stale live push) — while the speech engine stays silent,
 * because a pull fallback must never be read aloud (TTS is live-push-only).
 */
class CoachFreshnessPullFallbackTest {

    private val recommendation = Recommendation(
        type = "STARTER",
        title = "Start your territory",
        description = "Walk 1,000 steps to claim your very first hex.",
        target_metric = "steps",
        target_value = 1000,
        difficulty = "easy",
        reason_code = "COLD_START",
        reason = "hexes_owned=0 and total_lifetime_steps=0"
    )

    private fun coachResponse(
        message: String,
        fingerprint: String,
        generatedAt: String,
    ) = CoachResponse(
        generated_at = generatedAt,
        message = message,
        grounded = true,
        context = FitnessContextResponse(
            user_id = "00000000-0000-0000-0000-000000000001",
            total_lifetime_steps = 0,
            hexes_owned = 0,
            recent_captures_7d = 0,
            last_capture_at = null,
            total_defense_steps = 0
        ),
        recommendation = recommendation,
        retrieval = CoachRetrievalInfo(retrieved_count = 3),
        context_fingerprint = fingerprint,
        cached = false
    )

    private fun session(id: String) = RunSessionEntity(
        id = id, startedAt = 0L, endedAt = 0L, durationSeconds = 0L,
        totalSteps = 0, distanceMeters = 0.0, caloriesBurned = 0,
        capturedHexCount = 0, capturedHexIdsJson = "", xpEarned = 0, isSynced = true
    )

    /** Returns a scripted sequence of coach responses, one per GET call. */
    private class FakeApi(
        private val responses: List<CoachResponse>
    ) : FitQuestApi {
        var getCoachCalls = 0
            private set

        override suspend fun getCoach(): CoachResponse {
            val r = responses[getCoachCalls.coerceAtMost(responses.size - 1)]
            getCoachCalls++
            return r
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

    private class FakeRunSessionRepository(
        var synced: List<RunSessionEntity>
    ) : RunSessionRepository {
        override suspend fun getSyncedSessions(): List<RunSessionEntity> = synced
        override suspend fun getUnsynced(): List<RunSessionEntity> = emptyList()
        override suspend fun saveSession(session: RunSessionEntity) = throw UnsupportedOperationException()
        override suspend fun markSynced(sessionId: String, xpEarned: Int) = throw UnsupportedOperationException()
        override suspend fun setPendingSyncPayload(sessionId: String, json: String) = throw UnsupportedOperationException()
        override suspend fun getSessionsBetween(start: Long, end: Long) = throw UnsupportedOperationException()
        override fun observeRecentSessions(limit: Int): Flow<List<RunSessionEntity>> = emptyFlow()
        override fun observeAllSessions(): Flow<List<RunSessionEntity>> = emptyFlow()
        override fun observeSessionCount(): Flow<Int> = emptyFlow()
        override fun observeLifetimeSteps(): Flow<Int?> = emptyFlow()
        override fun observeLifetimeDistance(): Flow<Double?> = emptyFlow()
    }

    private class FakeSynthesizer : TtsSynthesizer {
        override var isReady: Boolean = true
        val spoken = mutableListOf<String>()
        private var readyListener: ((Boolean) -> Unit)? = null

        override fun setOnReadyChanged(listener: (Boolean) -> Unit) {
            readyListener = listener
            listener(isReady)
        }

        override fun speak(text: String, flushPrevious: Boolean) {
            spoken.add(text)
        }

        override fun stop() = Unit
        override fun release() = Unit
    }

    // ── D: signature advances, stale live exists, fresh pull is what shows ───

    @Test
    fun `D a newly credited run advances the signature and the fresh pull outranks the stale live`() = runBlocking {
        val repo = FakeRunSessionRepository(listOf(session("run-a")))
        // First GET -> pull for run A's context; second GET (after run B is
        // credited) -> fresh pull for run B's context. This is the CoachCache
        // contract: one fresh request only once the synced signature changes.
        val api = FakeApi(listOf(
            coachResponse("pull for run A", "fix-e-v1:ctx:runA", "2026-09-06T09:30:00.000000"),
            coachResponse("pull for run B", "fix-e-v1:ctx:runB", "2026-09-06T11:00:00.000000"),
        ))
        val cache = CoachCache(CoachFetcher(api), repo)

        cache.ensureLoaded()
        assertEquals(1, api.getCoachCalls)
        assertEquals("pull for run A",
            (cache.state.value as CoachFetcher.Outcome.Success).response.message)

        // A process-lifetime live push for run A still lingers in the store.
        val liveStore = LiveCoachStore()
        liveStore.publish(
            coachResponse("stale live for run A", "fix-e-v1:ctx:runA", "2026-09-06T09:00:00.000000")
        )

        // Reconciliation credits run B -> synced signature advances.
        repo.synced = listOf(session("run-a"), session("run-b"))
        cache.ensureLoaded()          // exactly one fresh pull for the new context
        assertEquals(2, api.getCoachCalls)
        val pullState = cache.state.value as CoachFetcher.Outcome.Success
        assertEquals("pull for run B", pullState.response.message)

        // Freshness-aware selection: the fresh pull is shown, not the stale live.
        val display = CoachDisplaySelector.select(liveStore.message.value, cache.state.value)
        assertTrue(display.outcome is CoachFetcher.Outcome.Success)
        assertEquals("pull for run B", (display.outcome as CoachFetcher.Outcome.Success).response.message)
        assertFalse("the stale live card is replaced by the fresh pull", display.isLive)

        // The live slot itself is NOT cleared — a later genuinely fresh push can
        // still surface (a stale live is shadowed, never deleted).
        assertEquals("stale live for run A", liveStore.message.value?.message)
    }

    // ── D: the fresh pull fallback never drives the speech engine ────────────

    @Test
    fun `D the pull fallback never auto-reads aloud`() {
        val liveStore = LiveCoachStore()
        val synth = FakeSynthesizer()
        val controller = CoachingSpeechController(
            liveCoachStore = liveStore,
            synthesizer = synth,
            gate = CoachingSpeechGate(),
            scope = CoroutineScope(Dispatchers.Unconfined),
        )
        controller.start()

        // A genuine live push arrived earlier and WAS spoken once.
        val staleLive = coachResponse("stale live for run A", "fix-e-v1:ctx:runA", "2026-09-06T09:00:00.000000")
        liveStore.publish(staleLive)
        assertEquals(listOf("stale live for run A"), synth.spoken)

        // The pull cache now refreshes to a fresh context (no push involved).
        val repo = FakeRunSessionRepository(listOf(session("run-a"), session("run-b")))
        val api = FakeApi(listOf(
            coachResponse("pull for run B", "fix-e-v1:ctx:runB", "2026-09-06T11:00:00.000000"),
        ))
        val cache = CoachCache(CoachFetcher(api), repo)
        runBlocking { cache.ensureLoaded() }
        assertEquals("pull for run B",
            (cache.state.value as CoachFetcher.Outcome.Success).response.message)

        // No new live push was published -> nothing else is spoken; TTS stays
        // live-push-only. The card may show the fresh pull, silently.
        assertEquals("no auto-TTS for the pull fallback", listOf("stale live for run A"), synth.spoken)
        assertEquals("stale live for run A", liveStore.message.value?.message)
    }
}
