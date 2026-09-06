package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse
import retrofit2.HttpException
import java.io.IOException

/**
 * Fetches the grounded AI coach message (backend Phase 4C.2 pipeline:
 * real FitnessContext → recommendation → RAG retrieval → Gemini LLM).
 * Mirrors [RecommendationFetcher]: every failure mode maps to a sealed
 * outcome so the Home tab never crashes on network problems.
 *
 * The backend is the single source of truth — no local/fake coaching text.
 * On [Outcome.Success] the response has been validated: `message` is
 * non-blank and `recommendation` is present. A response that parses but
 * violates that shape (e.g. a schema drift) is [Outcome.MalformedResponse],
 * not a crash.
 */
class CoachFetcher(private val api: FitQuestApi) {

    sealed interface Outcome {
        /** [response.message] is guaranteed non-blank; [response.grounded]
         * tells grounded RAG coaching apart from the backend's flagged
         * general-guidance fallback (grounded=false). */
        data class Success(val response: CoachResponse) : Outcome
        data class HttpError(val code: Int) : Outcome
        data class NetworkError(val cause: String? = null) : Outcome

        /** Response could not be parsed / unexpected shape — distinct from
         * transport-level network failures. */
        data class MalformedResponse(val cause: String? = null) : Outcome
    }

    suspend fun fetchCoachMessage(): Outcome = try {
        val response = api.getCoach()
        if (response.message.isNullOrBlank() || response.recommendation == null) {
            Outcome.MalformedResponse("coach response missing message or recommendation")
        } else {
            Outcome.Success(response)
        }
    } catch (e: kotlinx.coroutines.CancellationException) {
        // Coroutine cancellation (e.g. the caller left the screen mid-fetch)
        // must propagate, not masquerade as a MalformedResponse.
        throw e
    } catch (e: HttpException) {
        Outcome.HttpError(e.code())
    } catch (e: IOException) {
        Outcome.NetworkError(e.message)
    } catch (e: Exception) {
        // Malformed JSON or anything unexpected — never crash the UI.
        Outcome.MalformedResponse(e.message)
    }
}
