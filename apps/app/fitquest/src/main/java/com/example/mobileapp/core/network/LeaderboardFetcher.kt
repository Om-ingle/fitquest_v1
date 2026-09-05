package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.LeaderboardResponse
import retrofit2.HttpException
import java.io.IOException

/**
 * Fetches the server-backed territory leaderboard. Mirrors [RunSyncer]:
 * every failure mode maps to a sealed outcome so callers never crash on
 * network problems.
 *
 * The backend is the single source of truth — no local/fake rivals.
 */
class LeaderboardFetcher(private val api: FitQuestApi) {

    sealed interface Outcome {
        data class Success(val leaderboard: LeaderboardResponse) : Outcome
        data class HttpError(val code: Int) : Outcome
        data class NetworkError(val cause: String? = null) : Outcome
    }

    suspend fun fetchLeaderboard(limit: Int = DEFAULT_LIMIT): Outcome = try {
        Outcome.Success(api.getLeaderboard(limit))
    } catch (e: HttpException) {
        Outcome.HttpError(e.code())
    } catch (e: IOException) {
        Outcome.NetworkError(e.message)
    } catch (e: Exception) {
        // Malformed response or anything unexpected — never crash the UI.
        Outcome.NetworkError(e.message)
    }

    companion object {
        const val DEFAULT_LIMIT = 10
    }
}
