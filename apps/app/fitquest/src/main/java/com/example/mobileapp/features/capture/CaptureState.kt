package com.example.mobileapp.features.capture

import com.example.mobileapp.core.data.local.AchievementEntity
import com.example.mobileapp.core.data.local.ActiveRunEntity
import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.model.GeoPoint
import com.example.mobileapp.core.network.models.RunSyncSummary

data class CaptureState(
    val isTracking: Boolean = false,
    val isPaused: Boolean = false,
    val durationSeconds: Long = 0L,
    val distanceMeters: Double = 0.0,
    val caloriesBurned: Int = 0,
    val currentLocation: GeoPoint? = null,
    val currentHexId: String? = null,
    val sessionSteps: Int = 0,
    val sessionCapturedHexes: List<String> = emptyList(),
    val historicalCapturedHexes: List<String> = emptyList(),
    val allCapturedHexes: List<String> = emptyList(),

    // Non-null when a Room checkpoint was found on entry but the capture
    // engine is not live (process death): the user must Resume or Discard.
    // See CaptureScreenModel.onResumeRecovery / onDiscardRecovery.
    val pendingRecovery: ActiveRunEntity? = null,

    // Post-Run Dialog State
    val showSummaryDialog: Boolean = false,
    val latestCompletedSession: RunSessionEntity? = null,
    val unlockedAchievements: List<AchievementEntity> = emptyList(),

    // Network & Multiplayer Sync
    val syncSummary: RunSyncSummary? = null,

    // Shared-map (server-backed) territory, from GET /api/v1/map/viewport.
    // Rival-owned hexes (GeoJSON, one "owner" property per feature).
    val multiplayerGeoJson: String = "",
    // Server-confirmed hexes owned by the current user (GeoJSON, "owner" = "YOU").
    val myServerHexesGeoJson: String = "",
    val isFetchingSharedMap: Boolean = false,
    val sharedMapFetchFailed: Boolean = false,

    // Pre-computed GeoJSON strings for the map layers.
    // Built on Dispatchers.Default to keep the UI thread free and avoid "skipped frames".
    val capturedHexGeoJson: String = "",
    val currentHexGeoJson: String = "",
    val nearbyHexGeoJson: String = ""
)
