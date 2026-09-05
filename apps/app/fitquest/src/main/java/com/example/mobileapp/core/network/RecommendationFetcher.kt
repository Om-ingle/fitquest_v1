package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.RecommendationResponse
import retrofit2.HttpException
import java.io.IOException

/**
 * Fetches the server-backed "Coach" recommendation (Phase 4A rules engine).
 * Mirrors [LeaderboardFetcher]: every failure mode maps to a sealed outcome
 * so the Home tab never crashes on network problems.
 *
 * The backend is the single source of truth — no local/fake advice.
 */
class RecommendationFetcher(private val api: FitQuestApi) {

    sealed interface Outcome {
        data class Success(val response: RecommendationResponse) : Outcome
        data class HttpError(val code: Int) : Outcome
        data class NetworkError(val cause: String? = null) : Outcome

        /** Response could not be parsed / unexpected shape — distinct from
         * transport-level network failures. */
        data class MalformedResponse(val cause: String? = null) : Outcome
    }

    suspend fun fetchRecommendation(): Outcome = try {
        Outcome.Success(api.getRecommendations())
    } catch (e: HttpException) {
        Outcome.HttpError(e.code())
    } catch (e: IOException) {
        Outcome.NetworkError(e.message)
    } catch (e: Exception) {
        // Malformed JSON or anything unexpected — never crash the UI.
        Outcome.MalformedResponse(e.message)
    }
}
