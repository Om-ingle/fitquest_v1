package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.network.models.LeaderboardResponse
import com.example.mobileapp.core.network.models.MapViewportResponse
import com.example.mobileapp.core.network.models.RecommendationResponse
import com.example.mobileapp.core.network.models.RunSyncPayload
import com.example.mobileapp.core.network.models.RunSyncSummary
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Query

interface FitQuestApi {

    @POST("api/v1/runs/sync")
    suspend fun syncRunSession(
        @Body payload: RunSyncPayload
    ): RunSyncSummary

    @GET("api/v1/leaderboard")
    suspend fun getLeaderboard(
        @Query("limit") limit: Int
    ): LeaderboardResponse

    @GET("api/v1/map/viewport")
    suspend fun getMapViewport(
        @Query("min_lat") minLat: Double,
        @Query("min_lng") minLng: Double,
        @Query("max_lat") maxLat: Double,
        @Query("max_lng") maxLng: Double,
        @Query("zoom_level") zoomLevel: Double
    ): MapViewportResponse

    @GET("api/v1/recommendations")
    suspend fun getRecommendations(): RecommendationResponse

    /** Grounded AI coaching (Gemini + RAG) for the current dev user. */
    @GET("api/v1/coach")
    suspend fun getCoach(): CoachResponse
}