package com.example.mobileapp.core.network.models

data class RunSyncPayload(
    val total_session_steps: Int,
    val hexes_to_steps: Map<String, Int>
)

data class RunSyncSummary(
    val hexes_defended: Int,
    val hexes_stolen: Int,
    val hexes_newly_captured: Int,
    val xp_earned: Int,
    val new_total_lifetime_steps: Int
)

data class HexDetailResponse(
    val hex_id: String,
    val king_id: String,
    val king_username: String,
    val defense_score_steps: Int,
    val is_owned_by_me: Boolean
)

data class HeatmapResponse(
    val parent_hex_id: String,
    val dominant_king_id: String,
    val dominant_king_username: String,
    val total_hexes_inside: Int
)

data class MapViewportResponse(
    val is_aggregated: Boolean,
    val hexes: List<HexDetailResponse> = emptyList(),
    val heatmaps: List<HeatmapResponse> = emptyList()
)

data class LeaderboardEntryResponse(
    val rank: Int,
    val user_id: String,
    val username: String,
    val avatar_url: String? = null,
    val hexes_owned: Int,
    val is_current_user: Boolean
)

data class LeaderboardResponse(
    val metric: String,
    val total_players: Int,
    val entries: List<LeaderboardEntryResponse> = emptyList(),
    val current_user_entry: LeaderboardEntryResponse? = null
)

// Server-backed recommendation (Phase 4A rules engine, GET /api/v1/recommendations).

data class FitnessContextResponse(
    val user_id: String,
    val total_lifetime_steps: Int,
    val hexes_owned: Int,
    val recent_captures_7d: Int,
    val last_capture_at: String? = null,
    val total_defense_steps: Int
)

data class Recommendation(
    val type: String,
    val title: String,
    val description: String,
    val target_metric: String,
    val target_value: Int,
    val difficulty: String,
    val reason_code: String,
    val reason: String
)

data class RecommendationResponse(
    val generated_at: String,
    val context: FitnessContextResponse,
    val recommendation: Recommendation
)
