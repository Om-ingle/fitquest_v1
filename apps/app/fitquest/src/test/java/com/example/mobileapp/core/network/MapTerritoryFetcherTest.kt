package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.HexDetailResponse
import com.example.mobileapp.core.network.models.MapViewportResponse
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException

/**
 * JVM unit tests for the shared-map viewport fetcher and its
 * meaningful-change detector — mirrors LeaderboardFetcherTest: every
 * failure mode becomes a non-crashing Outcome.
 */
class MapTerritoryFetcherTest {

    private val viewport = MapViewportResponse(
        is_aggregated = false,
        hexes = listOf(
            HexDetailResponse(
                hex_id = "8a2a1072b59ffff",
                king_id = "00000000-0000-0000-0000-000000000001",
                king_username = "devuser",
                defense_score_steps = 120,
                is_owned_by_me = true
            )
        ),
        heatmaps = emptyList()
    )

    private class FakeApi(
        private val behavior: suspend (ViewportBounds) -> MapViewportResponse
    ) : FitQuestApi {
        override suspend fun syncRunSession(payload: com.example.mobileapp.core.network.models.RunSyncPayload) =
            throw UnsupportedOperationException()

        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double,
            zoomLevel: Double
        ): MapViewportResponse = behavior(
            ViewportBounds(minLat, minLng, maxLat, maxLng, zoomLevel)
        )

        override suspend fun getLeaderboard(limit: Int) =
            throw UnsupportedOperationException()

        override suspend fun getRecommendations():
            com.example.mobileapp.core.network.models.RecommendationResponse =
            throw UnsupportedOperationException()
    }

    @Test
    fun `success maps to Success with the bounds forwarded to the api`() = runBlocking {
        var received: ViewportBounds? = null
        val fetcher = MapTerritoryFetcher(FakeApi { bounds ->
            received = bounds
            viewport
        })
        val bounds = ViewportBounds(21.0, 78.0, 21.2, 78.2, 15.5)

        val outcome = fetcher.fetchViewport(bounds)

        assertTrue(outcome is MapTerritoryFetcher.Outcome.Success)
        assertEquals(viewport, (outcome as MapTerritoryFetcher.Outcome.Success).response)
        assertEquals(bounds, received)
    }

    @Test
    fun `http 4xx-5xx maps to HttpError with the code`() = runBlocking {
        val body = "{}".toResponseBody("application/json".toMediaType())
        val fetcher = MapTerritoryFetcher(FakeApi { throw HttpException(Response.error<Unit>(503, body)) })

        val outcome = fetcher.fetchViewport(ViewportBounds(21.0, 78.0, 21.2, 78.2, 15.5))

        assertEquals(MapTerritoryFetcher.Outcome.HttpError(503), outcome)
    }

    @Test
    fun `io exception maps to NetworkError`() = runBlocking {
        val fetcher = MapTerritoryFetcher(FakeApi { throw IOException("no internet") })

        val outcome = fetcher.fetchViewport(ViewportBounds(21.0, 78.0, 21.2, 78.2, 15.5))

        assertTrue(outcome is MapTerritoryFetcher.Outcome.NetworkError)
    }

    // ── ViewportChangeDetector ──────────────────────────────────────────────

    private val base = ViewportBounds(minLat = 21.0, minLng = 78.0, maxLat = 21.2, maxLng = 78.2, zoomLevel = 15.0)

    @Test
    fun `first viewport (no previous) always fetches`() {
        assertTrue(ViewportChangeDetector.shouldFetch(null, base))
    }

    @Test
    fun `identical viewport does not fetch again`() {
        assertFalse(ViewportChangeDetector.shouldFetch(base, base))
    }

    @Test
    fun `tiny camera drift (center shift under 25 percent) does not fetch`() {
        // 25% of the lat span (0.2°) is 0.05°; shift by 0.04° — below it.
        val drifted = base.copy(minLat = 21.04, maxLat = 21.24)
        assertFalse(ViewportChangeDetector.shouldFetch(base, drifted))
    }

    @Test
    fun `center shift of 25 percent of the viewport span fetches`() {
        // 25% of the lat span (0.2°) is 0.05°; shift by 0.06° — clearly past it.
        val shifted = base.copy(minLat = 21.06, maxLat = 21.26)
        assertTrue(ViewportChangeDetector.shouldFetch(base, shifted))
    }

    @Test
    fun `zoom change of at least 0-25 fetches`() {
        val zoomed = base.copy(zoomLevel = 15.3)
        assertTrue(ViewportChangeDetector.shouldFetch(base, zoomed))
    }

    @Test
    fun `zoom change under 0-25 does not fetch`() {
        val zoomed = base.copy(zoomLevel = 15.1)
        assertFalse(ViewportChangeDetector.shouldFetch(base, zoomed))
    }
}
