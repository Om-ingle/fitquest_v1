package com.example.mobileapp.core.run

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * JVM unit tests for the recovery decision on run-screen entry.
 *
 * The live in-process engine is always authoritative (a LIVE run wins even if
 * a stale checkpoint exists — it is simply overwritten going forward). A
 * checkpoint is only surfaced as user-actionable recovery when no engine is
 * live (process death), so a finished run is never recovered and a fresh run
 * is never duplicated.
 */
class ActiveRunStatusResolverTest {

    @Test
    fun liveEngineWinsEvenWithStaleCheckpoint() {
        assertEquals(
            ActiveRunStatus.LIVE,
            ActiveRunStatusResolver.resolve(isEngineTracking = true, checkpointExists = true)
        )
    }

    @Test
    fun liveEngineWithoutCheckpointIsLive() {
        assertEquals(
            ActiveRunStatus.LIVE,
            ActiveRunStatusResolver.resolve(isEngineTracking = true, checkpointExists = false)
        )
    }

    @Test
    fun deadEngineWithCheckpointIsRecoverable() {
        assertEquals(
            ActiveRunStatus.RECOVERABLE,
            ActiveRunStatusResolver.resolve(isEngineTracking = false, checkpointExists = true)
        )
    }

    @Test
    fun deadEngineWithoutCheckpointIsNone() {
        assertEquals(
            ActiveRunStatus.NONE,
            ActiveRunStatusResolver.resolve(isEngineTracking = false, checkpointExists = false)
        )
    }
}
