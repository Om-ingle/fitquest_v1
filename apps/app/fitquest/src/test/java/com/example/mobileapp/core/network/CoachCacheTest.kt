package com.example.mobileapp.core.network

import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.network.models.CoachRetrievalInfo
import com.example.mobileapp.core.network.models.FitnessContextResponse
import com.example.mobileapp.core.network.models.Recommendation
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM unit tests for the Fix E Android coach cache: Home navigation alone must
 * not re-trigger the coach GET, a fresh request happens only when the
 * device-side synced-run signature changes, a previous failure is not
 * auto-retried by navigation (Retry works instead), a silent refresh failure
 * keeps the last good response, and overlapping loads are single-flight.
 * No network — the API and the Room repository are always faked.
 */
class CoachCacheTest {

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

    private fun coachResponse(message: String = "Aim for 1,000 steps today.") = CoachResponse(
        generated_at = "2026-09-06T10:15:00.000000",
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
        retrieval = CoachRetrievalInfo(retrieved_count = 3)
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
    fun `first load fetches once and returning home with no new activity does not refetch`() = runBlocking {
        val api = FakeApi { coachResponse() }
        val cache = CoachCache(
            CoachFetcher(api),
            FakeRunSessionRepository(listOf(session("a")))
        )

        cache.ensureLoaded()          // first Home entry → fetch
        assertEquals(1, api.getCoachCalls)
        assertTrue(cache.state.value is CoachFetcher.Outcome.Success)

        cache.ensureLoaded()          // Home → Profile → Home, nothing changed
        assertEquals(1, api.getCoachCalls)  // cached response, NO network request
        assertTrue(cache.state.value is CoachFetcher.Outcome.Success)
    }

    @Test
    fun `a newly synced run triggers one fresh request then settles`() = runBlocking {
        val repo = FakeRunSessionRepository(listOf(session("a")))
        val api = FakeApi { coachResponse(message = "fresh") }
        val cache = CoachCache(CoachFetcher(api), repo)

        cache.ensureLoaded()
        assertEquals(1, api.getCoachCalls)

        repo.synced = listOf(session("a"), session("b"))   // new run synced server-side
        cache.ensureLoaded()
        assertEquals(2, api.getCoachCalls)                 // context may have changed → ask once
        assertEquals("fresh", (cache.state.value as CoachFetcher.Outcome.Success).response.message)

        cache.ensureLoaded()                               // now unchanged again
        assertEquals(2, api.getCoachCalls)
    }

    @Test
    fun `navigation after a failure does not auto retry but manual retry works`() = runBlocking {
        var down = true
        val api = FakeApi {
            if (down) throw IOException("no internet") else coachResponse()
        }
        val cache = CoachCache(CoachFetcher(api), FakeRunSessionRepository(listOf(session("a"))))

        cache.ensureLoaded()           // backend down on first load
        assertEquals(1, api.getCoachCalls)
        assertTrue(cache.state.value is CoachFetcher.Outcome.NetworkError)

        cache.ensureLoaded()           // Home re-entry while still down
        assertEquals(1, api.getCoachCalls)  // no auto-retry on navigation

        down = false
        cache.refresh()                // user presses Retry
        assertEquals(2, api.getCoachCalls)
        assertTrue(cache.state.value is CoachFetcher.Outcome.Success)
    }

    @Test
    fun `silent refresh failure keeps the previous good response`() = runBlocking {
        var down = false
        val repo = FakeRunSessionRepository(listOf(session("a")))
        val api = FakeApi {
            if (down) throw IOException("flaky") else coachResponse(message = "cached advice")
        }
        val cache = CoachCache(CoachFetcher(api), repo)

        cache.ensureLoaded()
        assertEquals(1, api.getCoachCalls)

        repo.synced = listOf(session("a"), session("b"))   // looks like new context
        down = true
        cache.ensureLoaded()           // background refresh fails...
        assertEquals(2, api.getCoachCalls)
        val current = cache.state.value as CoachFetcher.Outcome.Success
        assertEquals("cached advice", current.response.message)  // ...old advice kept, no error flash
    }

    @Test
    fun `concurrent loads are single flight and do not double fetch`() = runBlocking {
        val gate = CompletableDeferred<Unit>()
        val api = FakeApi {
            gate.await()
            coachResponse()
        }
        val cache = CoachCache(CoachFetcher(api), FakeRunSessionRepository(listOf(session("a"))))

        val first = launch { cache.ensureLoaded() }
        delay(50)                       // let the first load reach the (blocking) network call
        val second = launch { cache.ensureLoaded() }   // overlapping Home entry
        delay(50)
        gate.complete(Unit)
        first.join()
        second.join()

        assertEquals(1, api.getCoachCalls)
        assertTrue(cache.state.value is CoachFetcher.Outcome.Success)
    }
}
