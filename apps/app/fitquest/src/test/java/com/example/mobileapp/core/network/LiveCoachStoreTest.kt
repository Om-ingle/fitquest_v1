package com.example.mobileapp.core.network

import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.network.models.CoachRetrievalInfo
import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.network.models.FitnessContextResponse
import com.example.mobileapp.core.network.models.Recommendation
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M8.3B: the LIVE push slot ([LiveCoachStore]) is a separate singleton from the
 * pull [CoachCache]. A real-time coaching_message that arrives mid-session must
 * NOT be written into the pull cache — that cache keys its "fetch again?"
 * decision on the set of synced run ids, and a pushed response represents a
 * different trigger/context than the last pull, so writing it in would corrupt
 * that bookkeeping. These tests prove publish/read semantics and that a push
 * leaves the pull cache's state AND its future-fetch decision untouched.
 */
class LiveCoachStoreTest {

    private val recommendation = Recommendation(
        type = "RECOVERY",
        title = "Nice run — recover well",
        description = "Walk it off, hydrate, and stretch.",
        target_metric = "steps",
        target_value = 2000,
        difficulty = "easy",
        reason_code = "RUN_DONE",
        reason = "total_lifetime_steps=1000"
    )

    private fun coachResponse(message: String = "cached pull advice") = CoachResponse(
        generated_at = "2026-09-06T10:15:00.000000",
        message = message,
        grounded = true,
        context = FitnessContextResponse(
            user_id = "00000000-0000-0000-0000-000000000001",
            total_lifetime_steps = 1000,
            hexes_owned = 1,
            recent_captures_7d = 1,
            last_capture_at = null,
            total_defense_steps = 0
        ),
        recommendation = recommendation,
        retrieval = CoachRetrievalInfo(retrieved_count = 3),
        context_fingerprint = "fix-e-v1:abc123",
        cached = false
    )

    private fun session(id: String) = RunSessionEntity(
        id = id, startedAt = 0L, endedAt = 0L, durationSeconds = 0L,
        totalSteps = 0, distanceMeters = 0.0, caloriesBurned = 0,
        capturedHexCount = 0, capturedHexIdsJson = "", xpEarned = 0, isSynced = true
    )

    private class FakeApi(
        private val behavior: suspend () -> CoachResponse
    ) : FitQuestApi {
        var getCoachCalls = 0
            private set

        override suspend fun getCoach(): CoachResponse {
            getCoachCalls++
            return behavior()
        }

        override suspend fun syncRunSession(payload: com.example.mobileapp.core.network.models.RunSyncPayload) =
            throw UnsupportedOperationException()

        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double,
            zoomLevel: Double
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

    @Test
    fun `starts empty and publishes the latest live message`() = runBlocking {
        val store = LiveCoachStore()
        assertNull(store.message.first())

        store.publish(coachResponse(message = "live push"))

        assertEquals("live push", store.message.value?.message)
    }

    @Test
    fun `a newer push replaces the previous one`() = runBlocking {
        val store = LiveCoachStore()
        store.publish(coachResponse(message = "first push"))
        store.publish(coachResponse(message = "second push"))

        assertEquals("second push", store.message.value?.message)
    }

    @Test
    fun `clear returns the store to empty`() = runBlocking {
        val store = LiveCoachStore()
        store.publish(coachResponse())
        store.clear()

        assertNull(store.message.value)
    }

    // ── 7. A push never corrupts the pull CoachCache ─────────────────────────

    @Test
    fun `a live push does not overwrite the pull cache state`() = runBlocking {
        val api = FakeApi { coachResponse(message = "pull advice") }
        val repo = FakeRunSessionRepository(listOf(session("a")))
        val pullCache = CoachCache(CoachFetcher(api), repo)
        val liveStore = LiveCoachStore()

        pullCache.ensureLoaded()                                   // Home pull path
        assertEquals(1, api.getCoachCalls)
        val pullState = pullCache.state.value
        assertTrue(pullState is CoachFetcher.Outcome.Success)
        assertEquals("pull advice", (pullState as CoachFetcher.Outcome.Success).response.message)

        // A real-time coaching_message lands from the WebSocket...
        liveStore.publish(coachResponse(message = "live realtime push"))

        // ...and the pull cache still holds ITS OWN response (not the push).
        val after = pullCache.state.value as CoachFetcher.Outcome.Success
        assertEquals("pull advice", after.response.message)
        assertEquals("live realtime push", liveStore.message.value?.message)
        // The push did not touch the pull cache's future-fetch decision either:
        // no new synced activity -> next Home show is still a cached no-op.
        pullCache.ensureLoaded()
        assertEquals(1, api.getCoachCalls)
    }

    @Test
    fun `live and pull responses stay fully independent objects`() {
        val liveStore = LiveCoachStore()
        val pull = coachResponse(message = "pull advice")

        liveStore.publish(coachResponse(message = "live realtime push"))

        val live = liveStore.message.value
        assertTrue(live != null && live !== pull)
        assertEquals("pull advice", pull.message)
        assertEquals("live realtime push", live?.message)
    }
}
