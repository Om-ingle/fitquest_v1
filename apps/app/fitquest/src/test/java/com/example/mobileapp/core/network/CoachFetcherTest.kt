package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.network.models.CoachRetrievalInfo
import com.example.mobileapp.core.network.models.FitnessContextResponse
import com.example.mobileapp.core.network.models.Recommendation
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
 * JVM unit tests for the AI coach fetcher's outcome mapping — mirrors
 * RecommendationFetcherTest: every failure mode becomes a non-crashing
 * Outcome, and a response that parses but violates the essential shape
 * (blank message / missing recommendation) is MalformedResponse, never
 * a Success with unusable data. No network, Gemini, or Supabase access —
 * the API is always faked.
 */
class CoachFetcherTest {

    private val recommendation = Recommendation(
        type = "STARTER",
        title = "Start your territory",
        description = "You have no territory yet. Walk 1,000 steps to claim your very first hex.",
        target_metric = "steps",
        target_value = 1000,
        difficulty = "easy",
        reason_code = "COLD_START",
        reason = "hexes_owned=0 and total_lifetime_steps=0"
    )

    private val context = FitnessContextResponse(
        user_id = "00000000-0000-0000-0000-000000000001",
        total_lifetime_steps = 0,
        hexes_owned = 0,
        recent_captures_7d = 0,
        last_capture_at = null,
        total_defense_steps = 0
    )

    private fun coachResponse(
        message: String? = "Aim for 1,000 steps today — that first hex is within reach.",
        grounded: Boolean? = true
    ) = CoachResponse(
        generated_at = "2026-09-06T10:15:00.000000",
        message = message,
        grounded = grounded,
        context = context,
        recommendation = recommendation,
        retrieval = CoachRetrievalInfo(retrieved_count = 3)
    )

    private class FakeApi(
        private val behavior: suspend () -> CoachResponse
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

        override suspend fun getRecommendations():
            com.example.mobileapp.core.network.models.RecommendationResponse =
            throw UnsupportedOperationException()

        override suspend fun getCoach() = behavior()
    }

    @Test
    fun `success maps to Success with the validated coach response`() = runBlocking {
        val response = coachResponse()
        val fetcher = CoachFetcher(FakeApi { response })

        val outcome = fetcher.fetchCoachMessage()

        assertTrue(outcome is CoachFetcher.Outcome.Success)
        assertEquals(response, (outcome as CoachFetcher.Outcome.Success).response)
    }

    @Test
    fun `http 4xx-5xx maps to HttpError with the code`() = runBlocking {
        val body = "{}".toResponseBody("application/json".toMediaType())
        val fetcher = CoachFetcher(FakeApi { throw HttpException(Response.error<Unit>(503, body)) })

        assertEquals(
            CoachFetcher.Outcome.HttpError(503),
            fetcher.fetchCoachMessage()
        )
    }

    @Test
    fun `io exception maps to NetworkError`() = runBlocking {
        val fetcher = CoachFetcher(FakeApi { throw IOException("no internet") })

        assertTrue(fetcher.fetchCoachMessage() is CoachFetcher.Outcome.NetworkError)
    }

    @Test
    fun `malformed json maps to MalformedResponse`() = runBlocking {
        // Malformed JSON surfaces from the Gson converter as a parse
        // exception, not an IOException.
        val fetcher = CoachFetcher(FakeApi { throw IllegalArgumentException("Unexpected JSON token") })

        val outcome = fetcher.fetchCoachMessage()

        assertTrue(outcome is CoachFetcher.Outcome.MalformedResponse)
        assertEquals(
            "Unexpected JSON token",
            (outcome as CoachFetcher.Outcome.MalformedResponse).cause
        )
    }

    @Test
    fun `blank message or missing recommendation maps to MalformedResponse`() = runBlocking {
        // Gson bypasses Kotlin null-safety when a field is missing from
        // the JSON — the fetcher must catch shape violations itself.
        val blankMessage = CoachFetcher(FakeApi { coachResponse(message = "   ") })
        assertTrue(
            blankMessage.fetchCoachMessage() is CoachFetcher.Outcome.MalformedResponse
        )

        val missingRecommendation = CoachFetcher(
            FakeApi { coachResponse().copy(recommendation = null) }
        )
        assertTrue(
            missingRecommendation.fetchCoachMessage() is CoachFetcher.Outcome.MalformedResponse
        )
    }

    @Test
    fun `response fields map to the dto contract`() = runBlocking {
        var sent: CoachResponse? = null
        val fetcher = CoachFetcher(FakeApi { sent = coachResponse(); sent!! })

        val outcome = fetcher.fetchCoachMessage() as CoachFetcher.Outcome.Success

        assertEquals("2026-09-06T10:15:00.000000", outcome.response.generated_at)
        assertEquals("Aim for 1,000 steps today — that first hex is within reach.", outcome.response.message)
        assertEquals(true, outcome.response.grounded)
        assertEquals(context, outcome.response.context)
        assertEquals(recommendation, outcome.response.recommendation)
        assertEquals(3, outcome.response.retrieval?.retrieved_count)
    }

    @Test
    fun `grounded true is preserved so the ui can label it grounded`() = runBlocking {
        val fetcher = CoachFetcher(FakeApi { coachResponse(grounded = true) })

        val outcome = fetcher.fetchCoachMessage() as CoachFetcher.Outcome.Success

        assertEquals(true, outcome.response.grounded)
    }

    @Test
    fun `grounded false fallback is passed through not rejected`() = runBlocking {
        // grounded=false is the backend's flagged general-guidance
        // fallback — a valid, displayable response, not an error.
        val fetcher = CoachFetcher(FakeApi { coachResponse(grounded = false) })

        val outcome = fetcher.fetchCoachMessage()

        assertTrue(outcome is CoachFetcher.Outcome.Success)
        assertEquals(false, (outcome as CoachFetcher.Outcome.Success).response.grounded)
    }
}
