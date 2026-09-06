package com.example.mobileapp.core.network

/**
 * M8.5 — orchestrates what happens when the app returns to the foreground so a
 * run that was just reconciled can reach the Home coach card fresh, whether it
 * arrives as a live push or (when the WebSocket is down / a push is suppressed)
 * as a pull refresh.
 *
 * Ordering matters:
 *  1. The live channel is opened BEFORE unsynced runs are replayed. A run
 *     credited by that replay can then arrive as a live push over the freshly
 *     opened socket; if the socket were opened after the replay the server's
 *     push would be suppressed (no live session at push time) and a stale live
 *     message could linger. Opening the channel is best-effort and never blocks
 *     or aborts the replay — a channel failure degrades to the pull path.
 *  2. After the replay, if it actually credited a new run, the pull cache is
 *     re-ensured once. [CoachCache] keys its own "fetch again?" decision on the
 *     synced run-id signature, but Home's first `ensureLoaded()` may have
 *     sampled that signature BEFORE the replay finished marking rows synced — so
 *     without this a fresh pull would wait for the next Home re-entry. Calling
 *     [CoachCache.ensureLoaded] again is a no-op when the signature is unchanged
 *     (no repeated LLM call) and produces exactly one fresh pull when it did
 *     advance.
 *
 * Dependencies are injected as narrow function handles so this ordering is
 * unit-testable (no WebSocket/Room/network in the JVM test).
 */
class CoachForegroundCoordinator(
    private val openLiveChannel: () -> Unit,
    private val reconcileUnsyncedRuns: suspend () -> Boolean,
    private val refreshPullAfterNewRun: suspend () -> Unit,
) {

    /** Runs on every activity foreground (from MainActivity.onStart). */
    suspend fun onForeground() {
        try {
            openLiveChannel()
        } catch (_: Throwable) {
            // Best-effort: a channel failure must never abort the replay of
            // unsynced runs (the pull path still catches up on the next show).
        }
        val creditedNewRun = reconcileUnsyncedRuns()
        if (creditedNewRun) {
            // No-op when the synced signature did not change; a single fresh
            // pull when it did — this is what un-shadows a stale live push
            // when no fresh push arrived.
            refreshPullAfterNewRun()
        }
    }
}
