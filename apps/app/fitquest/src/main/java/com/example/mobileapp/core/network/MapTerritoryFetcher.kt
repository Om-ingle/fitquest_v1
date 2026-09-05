package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.MapViewportResponse
import retrofit2.HttpException
import java.io.IOException

/**
 * The visible map region reported by the MapLibre camera:
 * southwest + northeast corners plus the current zoom level.
 */
data class ViewportBounds(
    val minLat: Double,
    val minLng: Double,
    val maxLat: Double,
    val maxLng: Double,
    val zoomLevel: Double
)

/**
 * Decides whether a new camera position differs enough from the last
 * fetched viewport to justify another request — avoids hammering the
 * backend on every tiny camera movement.
 */
object ViewportChangeDetector {

    private const val CENTER_SHIFT_FRACTION = 0.25
    private const val ZOOM_DELTA = 0.25

    fun shouldFetch(last: ViewportBounds?, next: ViewportBounds): Boolean {
        if (last == null) return true
        if (kotlin.math.abs(last.zoomLevel - next.zoomLevel) >= ZOOM_DELTA) return true

        val latSpan = (last.maxLat - last.minLat).coerceAtLeast(1e-9)
        val lngSpan = (last.maxLng - last.minLng).coerceAtLeast(1e-9)
        val centerLatShift = kotlin.math.abs(
            (last.minLat + last.maxLat) / 2 - (next.minLat + next.maxLat) / 2
        )
        val centerLngShift = kotlin.math.abs(
            (last.minLng + last.maxLng) / 2 - (next.minLng + next.maxLng) / 2
        )
        return centerLatShift >= CENTER_SHIFT_FRACTION * latSpan ||
            centerLngShift >= CENTER_SHIFT_FRACTION * lngSpan
    }
}

/**
 * Fetches server-owned territory for the visible map region via
 * GET /api/v1/map/viewport. Mirrors [LeaderboardFetcher]: every failure
 * mode maps to a sealed outcome so a map API failure never crashes the
 * run or blocks local tracking.
 */
class MapTerritoryFetcher(private val api: FitQuestApi) {

    sealed interface Outcome {
        data class Success(val response: MapViewportResponse) : Outcome
        data class HttpError(val code: Int) : Outcome
        data class NetworkError(val cause: String? = null) : Outcome
    }

    suspend fun fetchViewport(bounds: ViewportBounds): Outcome = try {
        Outcome.Success(
            api.getMapViewport(
                minLat = bounds.minLat,
                minLng = bounds.minLng,
                maxLat = bounds.maxLat,
                maxLng = bounds.maxLng,
                zoomLevel = bounds.zoomLevel
            )
        )
    } catch (e: HttpException) {
        Outcome.HttpError(e.code())
    } catch (e: IOException) {
        Outcome.NetworkError(e.message)
    } catch (e: Exception) {
        // Malformed response or anything unexpected — never propagate.
        Outcome.NetworkError(e.message)
    }
}
