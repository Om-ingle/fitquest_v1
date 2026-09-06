package com.example.mobileapp.core.run

/**
 * Decision about what an entry into the run screen should do with an
 * in-progress run. Pure function of the two sources of truth, so it is unit
 * testable without Android:
 *
 *  - engine tracking (the process-lifetime [HexCaptureEngine] singleton is
 *    mid-run) → [LIVE]. The live session is authoritative; the screen adopts
 *    it. A checkpoint, if any, is simply overwritten going forward.
 *  - no live engine but a Room checkpoint exists → [RECOVERABLE]. The process
 *    (or only the screen) was killed mid-run; the user must choose to resume
 *    or discard rather than have it silently lost.
 *  - neither → [NONE]. Fresh standby screen.
 */
enum class ActiveRunStatus { NONE, RECOVERABLE, LIVE }

object ActiveRunStatusResolver {
    fun resolve(
        isEngineTracking: Boolean,
        checkpointExists: Boolean
    ): ActiveRunStatus = when {
        isEngineTracking -> ActiveRunStatus.LIVE
        checkpointExists -> ActiveRunStatus.RECOVERABLE
        else -> ActiveRunStatus.NONE
    }
}
