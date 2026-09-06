package com.example.mobileapp.core.run

import com.example.mobileapp.core.data.local.ActiveRunEntity

/**
 * Immutable, wall-clock-derived timing for an active run.
 *
 * Elapsed time is NEVER accumulated by a delay(1000) ticker; it is always
 * derived as `now - startedAt - accumulatedPausedDuration`. That makes it
 * correct across backgrounding, screen lock, scheduler jitter and (once
 * rebuilt from a checkpoint) process death. A [delay]-based display timer may
 * re-derive `elapsedSeconds()` once per second for the UI, but the number it
 * shows is this pure function of the clock — not a counter.
 *
 * A non-null [pausedSinceMillis] means the run is currently paused; while
 * paused the elapsed value is frozen at the pause instant.
 */
data class RunTiming(
    val startedAtMillis: Long,
    /** Non-null while the run is paused (the wall-clock instant pause began). */
    val pausedSinceMillis: Long? = null,
    /** Total paused duration (before the current pause, if paused) in millis. */
    val pausedAccumulatedMillis: Long = 0L
) {
    val isPaused: Boolean get() = pausedSinceMillis != null

    /** Active elapsed time at [atMillis] (frozen while paused). */
    fun elapsedMillis(atMillis: Long = System.currentTimeMillis()): Long {
        val reference = pausedSinceMillis ?: atMillis
        val active = reference - startedAtMillis - pausedAccumulatedMillis
        return active.coerceAtLeast(0L)
    }

    fun elapsedSeconds(atMillis: Long = System.currentTimeMillis()): Long =
        elapsedMillis(atMillis) / 1_000L

    /** Transition to paused at [atMillis]. Idempotent (already paused → self). */
    fun paused(atMillis: Long = System.currentTimeMillis()): RunTiming =
        if (pausedSinceMillis != null) this else copy(pausedSinceMillis = atMillis)

    /** Transition back to running at [atMillis]. Idempotent (not paused → self). */
    fun resumed(atMillis: Long = System.currentTimeMillis()): RunTiming {
        val pauseStart = pausedSinceMillis ?: return this
        return copy(
            pausedSinceMillis = null,
            pausedAccumulatedMillis =
                pausedAccumulatedMillis + (atMillis - pauseStart).coerceAtLeast(0L)
        )
    }

    /** Snapshot the run into a Room checkpoint entity. */
    fun toCheckpointEntity(
        runId: String,
        sessionSteps: Int,
        distanceMeters: Double,
        hexesToStepsJson: String,
        lastCheckpointAtMillis: Long = System.currentTimeMillis()
    ): ActiveRunEntity = ActiveRunEntity(
        runId = runId,
        startedAtMillis = startedAtMillis,
        isPaused = isPaused,
        pausedSinceMillis = pausedSinceMillis,
        pausedAccumulatedMillis = pausedAccumulatedMillis,
        sessionSteps = sessionSteps,
        distanceMeters = distanceMeters,
        hexesToStepsJson = hexesToStepsJson,
        lastCheckpointAtMillis = lastCheckpointAtMillis
    )

    companion object {
        fun starting(atMillis: Long = System.currentTimeMillis()): RunTiming =
            RunTiming(startedAtMillis = atMillis)

        /** Rebuild timing from a recovered checkpoint. */
        fun fromCheckpoint(entity: ActiveRunEntity): RunTiming = RunTiming(
            startedAtMillis = entity.startedAtMillis,
            pausedSinceMillis = entity.pausedSinceMillis,
            pausedAccumulatedMillis = entity.pausedAccumulatedMillis
        )
    }
}
