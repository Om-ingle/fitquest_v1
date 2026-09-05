package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.LeaderboardEntryResponse
import com.example.mobileapp.core.network.models.LeaderboardResponse
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
 * JVM unit tests for the leaderboard fetcher's outcome mapping — mirrors
 * RunSyncerTest: every failure mode becomes a non-crashing Outcome.
 */
class LeaderboardFetcherTest {

    private val leaderboard = LeaderboardResponse(
        metric = "hexes",
        total_players = 1,
        entries = listOf(
            LeaderboardEntryResponse(
                rank = 1,
                user_id = "00000000-0000-0000-0000-000000000001",
                username = "devuser",
                avatar_url = null,
                hexes_owned = 3,
                is_current_user = true
            )
        ),
        current_user_entry = null
    )

    private class FakeApi(
        private val behavior: suspend (Int) -> LeaderboardResponse
    ) : FitQuestApi {
        override suspend fun syncRunSession(payload: com.example.mobileapp.core.network.models.RunSyncPayload) =
            throw UnsupportedOperationException()

        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double,
            zoomLevel: Double
        ): com.example.mobileapp.core.network.models.MapViewportResponse =
            throw UnsupportedOperationException()

        override suspend fun getLeaderboard(limit: Int) = behavior(limit)

        override suspend fun getRecommendations():
            com.example.mobileapp.core.network.models.RecommendationResponse =
            throw UnsupportedOperationException()
    }

    @Test
    fun `success maps to Success with the server leaderboard`() = runBlocking {
        var receivedLimit: Int? = null
        val fetcher = LeaderboardFetcher(FakeApi { limit ->
            receivedLimit = limit
            leaderboard
        })

        val outcome = fetcher.fetchLeaderboard(limit = 5)

        assertTrue(outcome is LeaderboardFetcher.Outcome.Success)
        assertEquals(leaderboard, (outcome as LeaderboardFetcher.Outcome.Success).leaderboard)
        assertEquals(5, receivedLimit)
    }

    @Test
    fun `http 4xx-5xx maps to HttpError with the code`() = runBlocking {
        val body = "{}".toResponseBody("application/json".toMediaType())
        val fetcher = LeaderboardFetcher(FakeApi { throw HttpException(Response.error<Unit>(503, body)) })

        assertEquals(LeaderboardFetcher.Outcome.HttpError(503), fetcher.fetchLeaderboard())
    }

    @Test
    fun `io exception maps to NetworkError`() = runBlocking {
        val fetcher = LeaderboardFetcher(FakeApi { throw IOException("no internet") })

        assertTrue(fetcher.fetchLeaderboard() is LeaderboardFetcher.Outcome.NetworkError)
    }
}
