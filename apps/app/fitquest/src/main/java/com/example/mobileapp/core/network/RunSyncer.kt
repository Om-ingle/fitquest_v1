package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.RunSyncPayload
import com.example.mobileapp.core.network.models.RunSyncSummary
import retrofit2.HttpException
import java.io.IOException

/**
 * Sends a finished run to the backend and maps every failure mode to a
 * sealed outcome so callers never crash on network problems:
 * no internet / timeout / malformed response -> [SyncOutcome.NetworkError];
 * HTTP 4xx/5xx -> [SyncOutcome.HttpError] with the status code.
 *
 * The backend is the single authority for competitive game state (XP,
 * hex ownership). The app keeps its own provisional estimate only until a
 * successful sync replaces it.
 */
class RunSyncer(private val api: FitQuestApi) {

    sealed interface SyncOutcome {
        data class Success(val summary: RunSyncSummary) : SyncOutcome
        data class HttpError(val code: Int) : SyncOutcome
        data class NetworkError(val cause: String? = null) : SyncOutcome
    }

    suspend fun syncRun(
        totalSessionSteps: Int,
        hexesToSteps: Map<String, Int>
    ): SyncOutcome = try {
        val summary = api.syncRunSession(
            RunSyncPayload(
                total_session_steps = totalSessionSteps,
                hexes_to_steps = hexesToSteps
            )
        )
        SyncOutcome.Success(summary)
    } catch (e: HttpException) {
        SyncOutcome.HttpError(e.code())
    } catch (e: IOException) {
        SyncOutcome.NetworkError(e.message)
    } catch (e: Exception) {
        // Malformed response (Gson/JsonSyntaxException), serialization bugs,
        // or anything else unexpected — never propagate to crash the app.
        SyncOutcome.NetworkError(e.message)
    }
}
