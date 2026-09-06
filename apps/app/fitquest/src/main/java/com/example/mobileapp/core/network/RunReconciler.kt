package com.example.mobileapp.core.network

import com.example.mobileapp.core.data.local.HexRepository
import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.network.models.RunSyncPayload
import com.example.mobileapp.core.network.models.RunSyncPayloadCodec
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Foreground reconciliation of unsynced runs (Fix A).
 *
 * Every finished run is stored in Room with `isSynced = 0` until the server
 * confirms the sync. [reconcileUnsyncedRuns] is invoked on app foreground and
 * replays every unsynced row through the normal [RunSyncer] path, marking a run
 * synced ONLY after the server reports success — so a failed sync is simply
 * retried later and never silently dropped, and a crash between the server's
 * commit and the client's "mark synced" cannot double-credit (the server
 * dedupes on `run_id`).
 *
 * Single-flight (an [AtomicBoolean]) so overlapping foregrounds never race each
 * other or the run-finish path. Runs off the main thread; never blocks the UI.
 *
 * Two kinds of unsynced rows are handled:
 *  1. Rows with a stored [RunSessionEntity.pendingSyncPayloadJson] — every run
 *     finished after Fix A — are replayed byte-identically (run_id included,
 *     so a repeat of an already-applied run is a server-side no-op).
 *  2. Legacy rows (no stored payload; created before the column existed) are
 *     reconstructed deterministically. Lifetime steps and XP land exactly.
 *     Territory is minted from the device's authoritative cumulative per-hex
 *     record for hexes never touched by a synced session, which also makes
 *     per-hex defense land exactly on the recorded totals. Hexes the server
 *     already knows (touched by an earlier synced session) are defended with a
 *     zero-step entry: the +10 defend credit is preserved while the defense
 *     score is left at its previously-synced value, because the unsynced
 *     portion of those hexes cannot be isolated from local data without
 *     double-counting what the server already holds.
 */
class RunReconciler(
    private val runSyncer: RunSyncer,
    private val runSessionRepository: RunSessionRepository,
    private val hexRepository: HexRepository
) {

    private val inFlight = AtomicBoolean(false)

    /**
     * Replays all unsynced runs once; safe to call on every foreground.
     *
     * @return true when at least one run reached the synced state during this
     *         call (i.e. the device's synced-run signature advanced and the
     *         server context may have changed). False when there was nothing to
     *         replay, nothing succeeded, or another foreground already holds the
     *         single-flight lock.
     */
    suspend fun reconcileUnsyncedRuns(): Boolean {
        if (!inFlight.compareAndSet(false, true)) return false
        return try {
            withContext(Dispatchers.IO) {
                reconcile()
            }
        } finally {
            inFlight.set(false)
        }
    }

    private suspend fun reconcile(): Boolean {
        val unsynced = runSessionRepository.getUnsynced()
        if (unsynced.isEmpty()) return false

        // Hexes the server already holds, inferred from hexes touched by any
        // synced session — used only by the legacy best-effort path.
        val syncedHexes = runSessionRepository.getSyncedSessions()
            .flatMap { splitHexIds(it.capturedHexIdsJson) }
            .toSet()

        // Mint budget: for a hex never synced, the recorded cumulative total is
        // exactly the final defense the server should hold. Consumed oldest-run
        // first, so the earliest run that visited a hex mints it at that exact
        // total and later runs just reinforce (zero-step defend).
        val budget: MutableMap<String, Int> = linkedMapOf()
        hexRepository.getCapturedHexes()
            .filter { it.hexId !in syncedHexes }
            .forEach { budget[it.hexId] = it.totalSteps }

        var creditedNewRun = false
        for (session in unsynced) {
            val payload = payloadFor(session, budget) ?: continue
            when (val outcome = runSyncer.syncRun(payload)) {
                is RunSyncer.SyncOutcome.Success -> {
                    // already_processed: this run_id was already applied by an
                    // earlier attempt whose response was lost — keep the local
                    // xp value rather than overwriting it with the zeroed one.
                    val xp = if (outcome.summary.already_processed) session.xpEarned
                    else outcome.summary.xp_earned
                    runSessionRepository.markSynced(session.id, xp)
                    creditedNewRun = true
                }
                // Any other outcome leaves the row unsynced in Room so it is
                // retried on the next foreground — never silently dropped.
                is RunSyncer.SyncOutcome.HttpError,
                is RunSyncer.SyncOutcome.NetworkError -> Unit
            }
        }
        return creditedNewRun
    }

    private fun payloadFor(session: RunSessionEntity, budget: MutableMap<String, Int>): RunSyncPayload? {
        val stored = session.pendingSyncPayloadJson
        if (stored != null) {
            // Corrupt stored payload -> leave the row unsynced rather than risk
            // a wrong replay. (Should never happen.)
            val exact = RunSyncPayloadCodec.fromJson(stored) ?: return null
            // Exact sessions don't need the budget, but consume what they
            // credit so a (newer) legacy row can never over-mint the same hex.
            exact.hexes_to_steps.forEach { (hex, steps) ->
                if (steps > 0) budget[hex]?.let { budget[hex] = maxOf(0, it - steps) }
            }
            return exact
        }

        // Legacy row: deterministic best-effort reconstruction (see class doc).
        val hexIds = splitHexIds(session.capturedHexIdsJson)
        val hexesToSteps = linkedMapOf<String, Int>()
        for (hex in hexIds) {
            val remaining = budget[hex] ?: 0
            if (remaining > 0) {
                hexesToSteps[hex] = remaining
                budget[hex] = 0
            } else {
                // Server already holds the exact recorded total for this hex
                // (synced, or minted by an earlier recovered run). A zero-step
                // defend preserves the +10 defend credit at defense 0.
                hexesToSteps[hex] = 0
            }
        }
        return RunSyncPayload(
            total_session_steps = session.totalSteps,
            hexes_to_steps = hexesToSteps,
            daily_activity = null,
            run_id = session.id
        )
    }

    private fun splitHexIds(json: String?): List<String> =
        json?.split(",")?.map { it.trim() }?.filter { it.isNotEmpty() } ?: emptyList()
}
