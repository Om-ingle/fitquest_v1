package com.example.mobileapp.core.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Room-backed checkpoint of an *in-progress* run, used ONLY for recovery
 * after process death. This is deliberately separate from the completed
 * [RunSessionEntity] flow: a finished run is saved via [RunSessionRepository]
 * (Room -> RunSyncer), while this row holds enough state to reconstruct an
 * active run so it is never silently lost.
 *
 * There is at most one row at a time (single-run semantics). The foreground
 * service is the periodic writer; the row is cleared on run completion or
 * explicit discard.
 *
 * Distance/calories are derived from steps elsewhere (`steps * 0.75` / `* 0.04`);
 * [distanceMeters] is stored as the latest snapshot so a notification or
 * recovery screen does not need to recompute it from a possibly-lost source.
 */
@Entity(tableName = "active_run")
data class ActiveRunEntity(
    @PrimaryKey val runId: String,
    val startedAtMillis: Long,
    val isPaused: Boolean = false,
    val pausedSinceMillis: Long? = null,
    val pausedAccumulatedMillis: Long = 0L,
    val sessionSteps: Int = 0,
    val distanceMeters: Double = 0.0,
    // JSON map hexId -> steps, so the partial territory captured before the
    // process died is not lost (the engine only persists hexes to Room on
    // completion via mergeSessionHexes).
    val hexesToStepsJson: String = "{}",
    val lastCheckpointAtMillis: Long = 0L
)
