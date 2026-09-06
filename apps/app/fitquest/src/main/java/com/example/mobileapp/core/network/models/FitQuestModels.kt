package com.example.mobileapp.core.network.models

data class RunSyncPayload(
    val total_session_steps: Int,
    val hexes_to_steps: Map<String, Int>,
    // Phase 4B.5 daily telemetry (optional; older payloads simply omit it —
    // Gson skips null fields). Absolute day-to-date values so a repeated
    // sync of the same day is idempotent server-side.
    val daily_activity: DailyActivitySnapshot? = null,
    // Stable run/session id (Fix A replay guard). Persisted with this payload
    // before the first sync so a later retry replays byte-identical data, and
    // the backend recognises an already-applied run instead of re-crediting.
    val run_id: String? = null
)

// The user's device-local day as of this sync. activity_date is the DEVICE's
// local calendar date (same date the app uses for streaks/HomeTab), not UTC.
// hexes_lost / defense_steps are null: the device cannot observe rival
// steals or attribute defense steps reliably in v1 — the server keeps NULL
// ("unknown") rather than a wrong zero.
data class DailyActivitySnapshot(
    val activity_date: String, // YYYY-MM-DD, device-local
    val steps: Int,
    val active_minutes: Int,
    val goal_steps: Int,
    val goal_completed: Boolean,
    val hexes_owned: Int,
    val hexes_captured: Int,
    val hexes_lost: Int? = null,
    val defense_steps: Int? = null
)

data class RunSyncSummary(
    val hexes_defended: Int,
    val hexes_stolen: Int,
    val hexes_newly_captured: Int,
    val xp_earned: Int,
    val new_total_lifetime_steps: Int,
    // True when the payload carried a run_id the server had already applied.
    // No credit happened; callers keep the local (provisional) xpEarned rather
    // than overwriting it with the zeroed xp_earned. Missing on older servers.
    val already_processed: Boolean = false
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
// The trailing daily-activity fields (Fix E) are optional on purpose: older
// servers / cold users simply omit them (Gson leaves the field null), and they
// mirror the backend FitnessContext's "latest reported activity day" telemetry.

data class FitnessContextResponse(
    val user_id: String,
    val total_lifetime_steps: Int,
    val hexes_owned: Int,
    val recent_captures_7d: Int,
    val last_capture_at: String? = null,
    val total_defense_steps: Int,
    val activity_date: String? = null,
    val steps_today: Int? = null,
    val active_minutes_today: Int? = null,
    val goal_steps: Int? = null,
    val goal_completed_today: Boolean? = null,
    val goal_progress_ratio: Double? = null
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

// AI coach (backend Phase 4C.2, GET /api/v1/coach — Android integration
// Phase 4C.3B). Models the ACTUAL backend CoachResponse — no invented
// fields. Retrieval metadata is modeled minimally: the backend also returns
// per-chunk similarity scores, the raw query text and chunk sources, but
// those are developer/debug concerns and are deliberately NOT modeled
// (Gson ignores unmapped JSON fields), so they can never reach the UI.
//
// Fields are nullable on purpose: Gson bypasses Kotlin null-safety when a
// field is missing from the JSON, so [CoachFetcher] validates the essential
// ones (message, recommendation) and maps shape violations to
// MalformedResponse instead of letting an NPE reach the UI.

data class CoachRetrievalInfo(
    val retrieved_count: Int? = null
)

data class CoachResponse(
    val generated_at: String? = null,
    val message: String? = null,
    val grounded: Boolean? = null,
    val context: FitnessContextResponse? = null,
    val recommendation: Recommendation? = null,
    val retrieval: CoachRetrievalInfo? = null,
    // Fix E: deterministic digest of the context this response was grounded
    // in, and whether it was served from the backend cache (no new LLM call).
    val context_fingerprint: String? = null,
    val cached: Boolean? = null
)
