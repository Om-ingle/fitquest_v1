package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.FitnessContextResponse
import com.example.mobileapp.core.network.models.Recommendation
import com.example.mobileapp.core.network.models.RecommendationResponse
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
 * JVM unit tests for the coach-recommendation fetcher's outcome mapping —
 * mirrors LeaderboardFetcherTest: every failure mode becomes a
 * non-crashing Outcome.
 */
class RecommendationFetcherTest {

    private val recommendationResponse = RecommendationResponse(
        generated_at = "2026-09-05T12:52:38.812137",
        context = FitnessContextResponse(
            user_id = "00000000-0000-0000-0000-000000000001",
            total_lifetime_steps = 0,
            hexes_owned = 0,
            recent_captures_7d = 0,
            last_capture_at = null,
            total_defense_steps = 0
        ),
        recommendation = Recommendation(
            type = "STARTER",
            title = "Start your territory",
            description = "You have no territory yet. Walk 1,000 steps to claim your very first hex and start your empire.",
            target_metric = "steps",
            target_value = 1000,
            difficulty = "easy",
            reason_code = "COLD_START",
            reason = "hexes_owned=0 and total_lifetime_steps=0"
        )
    )

    private class FakeApi(
        private val behavior: suspend () -> RecommendationResponse
    ) : FitQuestApi {
        override suspend fun syncRunSession(payload: com.example.mobileapp.core.network.models.RunSyncPayload) =
            throw UnsupportedOperationException()

        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double,
            zoomLevel: Double
        ): com.example.mobileapp.core.network.models.MapViewportResponse =
            throw UnsupportedOperationException()

        override suspend fun getLeaderboard(limit: Int) =
            throw UnsupportedOperationException()

        override suspend fun getRecommendations() = behavior()

        override suspend fun getCoach(): com.example.mobileapp.core.network.models.CoachResponse =
            throw UnsupportedOperationException()
    }

    @Test
    fun `success maps to Success with the server recommendation`() = runBlocking {
        val fetcher = RecommendationFetcher(FakeApi { recommendationResponse })

        val outcome = fetcher.fetchRecommendation()

        assertTrue(outcome is RecommendationFetcher.Outcome.Success)
        assertEquals(
            recommendationResponse,
            (outcome as RecommendationFetcher.Outcome.Success).response
        )
        assertEquals("STARTER", outcome.response.recommendation.type)
    }

    @Test
    fun `http 4xx-5xx maps to HttpError with the code`() = runBlocking {
        val body = "{}".toResponseBody("application/json".toMediaType())
        val fetcher = RecommendationFetcher(FakeApi { throw HttpException(Response.error<Unit>(503, body)) })

        assertEquals(
            RecommendationFetcher.Outcome.HttpError(503),
            fetcher.fetchRecommendation()
        )
    }

    @Test
    fun `io exception maps to NetworkError`() = runBlocking {
        val fetcher = RecommendationFetcher(FakeApi { throw IOException("no internet") })

        assertTrue(fetcher.fetchRecommendation() is RecommendationFetcher.Outcome.NetworkError)
    }

    @Test
    fun `malformed response maps to MalformedResponse`() = runBlocking {
        // Malformed JSON surfaces from the Retrofit converter as a parse
        // exception (e.g. SerializationException), not an IOException.
        val fetcher = RecommendationFetcher(FakeApi { throw IllegalArgumentException("Unexpected JSON token") })

        val outcome = fetcher.fetchRecommendation()

        assertTrue(outcome is RecommendationFetcher.Outcome.MalformedResponse)
        assertEquals(
            "Unexpected JSON token",
            (outcome as RecommendationFetcher.Outcome.MalformedResponse).cause
        )
    }
}
