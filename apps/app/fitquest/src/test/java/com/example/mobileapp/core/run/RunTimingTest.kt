package com.example.mobileapp.core.run

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM unit tests for the timestamp-based elapsed-time model. Elapsed time must
 * never be a delay(1000) counter — it is `now - startedAt - accumulatedPaused`.
 * All times are injected explicitly so the tests are deterministic.
 */
class RunTimingTest {

    @Test
    fun freshRunStartsAtZeroElapsed() {
        val timing = RunTiming.starting(atMillis = 1_000L)
        assertEquals(0L, timing.elapsedMillis(atMillis = 1_000L))
        assertEquals(0L, timing.elapsedSeconds(atMillis = 1_000L))
        assertFalse(timing.isPaused)
    }

    @Test
    fun elapsedGrowsWithWallClock() {
        val timing = RunTiming.starting(atMillis = 0L)
        assertEquals(5_000L, timing.elapsedMillis(atMillis = 5_000L))
        assertEquals(5L, timing.elapsedSeconds(atMillis = 5_000L))
    }

    @Test
    fun pauseFreezesElapsedEvenAsClockMoves() {
        val timing = RunTiming
            .starting(atMillis = 0L)
            .paused(atMillis = 5_000L)
        // Clock keeps moving but elapsed stays frozen at the pause instant.
        assertEquals(5_000L, timing.elapsedMillis(atMillis = 5_000L))
        assertEquals(5_000L, timing.elapsedMillis(atMillis = 9_000L))
        assertTrue(timing.isPaused)
    }

    @Test
    fun resumeAccumulatesPausedDuration() {
        val timing = RunTiming
            .starting(atMillis = 0L)
            .paused(atMillis = 5_000L)
            .resumed(atMillis = 8_000L)
        assertFalse(timing.isPaused)
        assertEquals(3_000L, timing.pausedAccumulatedMillis)
        // 9_000 - 0 - 3_000 = 6_000ms active.
        assertEquals(6_000L, timing.elapsedMillis(atMillis = 9_000L))
        assertEquals(6L, timing.elapsedSeconds(atMillis = 9_000L))
    }

    @Test
    fun multiplePausesAccumulate() {
        val timing = RunTiming
            .starting(atMillis = 0L)
            .paused(atMillis = 2_000L)
            .resumed(atMillis = 4_000L)   // acc = 2_000
            .paused(atMillis = 5_000L)    // frozen at 5_000 - 2_000 = 3_000
            .resumed(atMillis = 9_000L)   // acc = 2_000 + 4_000 = 6_000
        assertEquals(6_000L, timing.pausedAccumulatedMillis)
        assertEquals(4_000L, timing.elapsedMillis(atMillis = 10_000L))
        assertEquals(4L, timing.elapsedSeconds(atMillis = 10_000L))
    }

    @Test
    fun elapsedClampsToZeroOnClockSkew() {
        // startedAt in the future relative to the reference instant (clock
        // rolled back after a pause) must not yield a negative elapsed.
        val timing = RunTiming(startedAtMillis = 10_000L)
        assertEquals(0L, timing.elapsedMillis(atMillis = 4_000L))
    }

    @Test
    fun pauseIsIdempotent() {
        val timing = RunTiming
            .starting(atMillis = 0L)
            .paused(atMillis = 1_000L)
            .paused(atMillis = 2_000L)
        // First pause instant is retained; second pause is a no-op.
        assertEquals(1_000L, timing.pausedSinceMillis)
    }

    @Test
    fun resumeWhenNotPausedIsNoOp() {
        val timing = RunTiming
            .starting(atMillis = 0L)
            .resumed(atMillis = 1_000L)
        assertEquals(0L, timing.pausedAccumulatedMillis)
        assertNull(timing.pausedSinceMillis)
    }

    @Test
    fun checkpointRoundTripPreservesTiming() {
        val timing = RunTiming
            .starting(atMillis = 100_000L)
            .paused(atMillis = 105_000L)
        val entity = timing.toCheckpointEntity(
            runId = "run-123",
            sessionSteps = 120,
            distanceMeters = 90.0,
            hexesToStepsJson = "abc:50,def:70",
            lastCheckpointAtMillis = 105_001L
        )

        assertEquals("run-123", entity.runId)
        assertEquals(100_000L, entity.startedAtMillis)
        assertTrue(entity.isPaused)
        assertEquals(105_000L, entity.pausedSinceMillis)
        assertEquals(120, entity.sessionSteps)
        assertEquals(90.0, entity.distanceMeters, 0.0)
        assertEquals("abc:50,def:70", entity.hexesToStepsJson)
        assertEquals(105_001L, entity.lastCheckpointAtMillis)

        val rebuilt = RunTiming.fromCheckpoint(entity)
        assertEquals(timing, rebuilt)
        // Recovered timing stays paused with the elapsed frozen at the pause.
        assertEquals(5_000L, rebuilt.elapsedMillis(atMillis = 200_000L))
    }

    @Test
    fun recoveredActiveRunElapsedUsesCheckpointPauseState() {
        val entity = RunTiming
            .starting(atMillis = 0L)
            .toCheckpointEntity(
                runId = "r",
                sessionSteps = 0,
                distanceMeters = 0.0,
                hexesToStepsJson = "",
                lastCheckpointAtMillis = 0L
            )
        val rebuilt = RunTiming.fromCheckpoint(entity)
        // A run recovered at t=12345 that was never paused resumes counting
        // from its original startedAt, not from recovery time.
        assertEquals(12L, rebuilt.elapsedSeconds(atMillis = 12_345L))
    }
}
