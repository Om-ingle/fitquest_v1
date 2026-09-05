package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.LeaderboardResponse
import com.example.mobileapp.core.network.models.MapViewportResponse
import com.example.mobileapp.core.network.models.RunSyncPayload
import com.example.mobileapp.core.network.models.RunSyncSummary
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException

/**
 * JVM unit tests for the run-sync error mapping. The backend stays the
 * authority for XP/ownership; these tests only verify that every failure
 * mode is converted to a non-crashing SyncOutcome.
 */
class RunSyncerTest {

    private val summary = RunSyncSummary(
        hexes_defended = 0,
        hexes_stolen = 0,
        hexes_newly_captured = 2,
        xp_earned = 100,
        new_total_lifetime_steps = 350
    )

    private class FakeApi(
        private val behavior: suspend (RunSyncPayload) -> RunSyncSummary
    ) : FitQuestApi {
        override suspend fun syncRunSession(payload: RunSyncPayload) = behavior(payload)

        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double,
            zoomLevel: Double
        ): MapViewportResponse = MapViewportResponse(is_aggregated = true)

        override suspend fun getLeaderboard(limit: Int): LeaderboardResponse =
            LeaderboardResponse(metric = "hexes", total_players = 0)

        override suspend fun getRecommendations():
            com.example.mobileapp.core.network.models.RecommendationResponse =
            throw UnsupportedOperationException()
    }

    @Test
    fun `success maps to Success with the authoritative summary`() = runBlocking {
        var received: RunSyncPayload? = null
        val syncer = RunSyncer(FakeApi { payload ->
            received = payload
            summary
        })

        val outcome = syncer.syncRun(350, mapOf("8a2a1072b59ffff" to 300))

        assertTrue(outcome is RunSyncer.SyncOutcome.Success)
        assertEquals(summary, (outcome as RunSyncer.SyncOutcome.Success).summary)
        // The payload matches the backend contract exactly.
        assertEquals(350, received!!.total_session_steps)
        assertEquals(mapOf("8a2a1072b59ffff" to 300), received!!.hexes_to_steps)
    }

    @Test
    fun `http 4xx-5xx maps to HttpError with the code`() = runBlocking {
        val body = "{}".toResponseBody("application/json".toMediaType())
        val syncer = RunSyncer(FakeApi { throw HttpException(Response.error<Unit>(500, body)) })

        val outcome = syncer.syncRun(100, emptyMap())

        assertEquals(RunSyncer.SyncOutcome.HttpError(500), outcome)
    }

    @Test
    fun `io exception maps to NetworkError`() = runBlocking {
        val syncer = RunSyncer(FakeApi { throw IOException("no internet") })

        val outcome = syncer.syncRun(100, emptyMap())

        assertTrue(outcome is RunSyncer.SyncOutcome.NetworkError)
    }

    @Test
    fun `malformed response maps to NetworkError instead of crashing`() = runBlocking {
        val syncer = RunSyncer(FakeApi { throw IllegalStateException("bad gson") })

        val outcome = syncer.syncRun(100, emptyMap())

        assertTrue(outcome is RunSyncer.SyncOutcome.NetworkError)
    }
}
