package com.example.mobileapp.core.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.util.UUID

@Entity(tableName = "run_sessions")
data class RunSessionEntity(
    @PrimaryKey val id: String = UUID.randomUUID().toString(),
    val startedAt: Long,
    val endedAt: Long,
    val durationSeconds: Long,
    val totalSteps: Int,
    val distanceMeters: Double,
    val caloriesBurned: Int,
    val capturedHexCount: Int,
    val capturedHexIdsJson: String, // Comma-separated or JSON string of hex IDs
    val xpEarned: Int,
    // False until the backend run-sync succeeded. While false, xpEarned holds
    // the local provisional estimate; after a successful sync it holds the
    // backend's authoritative value. Unsynced sessions stay in Room (offline
    // gameplay preserved) and are replayed by RunReconciler on the next
    // foreground (Fix A).
    val isSynced: Boolean = false,
    // The exact outbound RunSyncPayload JSON (incl. run_id = this session's
    // id), persisted BEFORE the first sync attempt so a later retry replays
    // byte-identical data. Null for legacy rows created before this column
    // existed — RunReconciler best-effort reconstructs those instead. Cleared
    // by markSynced once the server confirms the sync.
    val pendingSyncPayloadJson: String? = null
)
