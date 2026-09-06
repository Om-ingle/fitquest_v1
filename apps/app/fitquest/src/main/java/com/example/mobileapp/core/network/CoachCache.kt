package com.example.mobileapp.core.network

import com.example.mobileapp.core.data.local.RunSessionRepository
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

/**
 * Process-lifetime holder for the AI-coach response shown on Home (Fix E).
 *
 * WHY: navigating Home → Profile → Home used to re-run the coach GET on every
 * re-entry (Voyager disposes the tab composition), and each GET could trigger
 * another expensive backend LLM generation. This cache makes the fetch
 * *context-driven*, not navigation-driven:
 *
 *  - A [Success] is kept and shown immediately on Home re-entry, and no
 *    network request is made while the device-side signals that feed the
 *    server's context are unchanged.
 *  - A fresh request is made only when device-side run telemetry changed
 *    (i.e. a new run was synced) — the only client-observable way the server
 *    context fingerprint can change — or when nothing is cached yet.
 *  - A previous FAILURE is never auto-retried by navigation alone; the user
 *    must press Retry ([refresh]), which always goes to the network.
 *
 * The signature of "relevant context" is deliberately coarse: the ids of all
 * synced run sessions. Server context is derived from data the device only
 * changes by syncing a run, so a synced-run-id change is a safe "ask again"
 * trigger. If the backend finds the context fingerprint unchanged it serves
 * its own cached response (no LLM), so the worst case for a false-positive
 * trigger is a cheap GET, never an unnecessary LLM call.
 *
 * Concurrency: the network/DB work runs on [Dispatchers.IO]; state updates go
 * through a thread-safe [StateFlow]; single-flight via [inflight] so rapid
 * Home re-entries / overlapping foregrounds never fire duplicate requests.
 *
 * The card UI (HomeTab) reads [state] and needs no logic change: `null` =
 * loading, Success/error = as before. A silent background refresh keeps the
 * last good [Success] on screen; if that refresh fails the cached response is
 * kept rather than replaced by an error.
 */
class CoachCache(
    private val fetcher: CoachFetcher,
    private val runSessionRepository: RunSessionRepository
) {

    private val _state = MutableStateFlow<CoachFetcher.Outcome?>(null)
    val state: StateFlow<CoachFetcher.Outcome?> = _state.asStateFlow()

    private val inflight = AtomicBoolean(false)

    // Ids of the run sessions that were synced when the current Success was
    // produced (null until the first successful load). A change means the
    // device sent the backend new activity → ask again on the next show.
    @Volatile
    private var syncedSignature: Set<String>? = null

    /** Called whenever Home is shown. Never blocks; may silently refresh. */
    suspend fun ensureLoaded() {
        when (_state.value) {
            // Nothing loaded yet (first Home entry / fresh process) → fetch.
            null -> fetch(silent = false)

            // Warm success. No new synced activity → show cached, no request.
            // New synced activity → background refresh, keeping old on screen.
            is CoachFetcher.Outcome.Success -> {
                if (signatureUnchanged()) return
                fetch(silent = true)
            }

            // A previous attempt failed: do NOT auto-retry just because the
            // user navigated. Manual Retry ([refresh]) is the path back.
            is CoachFetcher.Outcome.HttpError,
            is CoachFetcher.Outcome.NetworkError,
            is CoachFetcher.Outcome.MalformedResponse -> Unit
        }
    }

    /**
     * Manual Retry / forced refresh: clears to the loading state and always
     * hits the network. This is what the Home Retry button invokes after a
     * real failure, so a failure is never hidden behind a cached value.
     */
    suspend fun refresh() {
        _state.value = null
        fetch(silent = false)
    }

    private suspend fun fetch(silent: Boolean) {
        if (!inflight.compareAndSet(false, true)) return
        try {
            val signature = snapshotSyncedSignature()
            val outcome = withContext(Dispatchers.IO) { fetcher.fetchCoachMessage() }
            when (outcome) {
                is CoachFetcher.Outcome.Success -> {
                    syncedSignature = signature
                    _state.value = outcome
                }
                else -> if (!silent) _state.value = outcome
                // Silent refresh failure: keep the last good response rather
                // than flash an error over content the user can still read.
            }
        } finally {
            inflight.set(false)
        }
    }

    private suspend fun snapshotSyncedSignature(): Set<String> =
        withContext(Dispatchers.IO) {
            runSessionRepository.getSyncedSessions().map { it.id }.toSet()
        }

    private suspend fun signatureUnchanged(): Boolean {
        val before = syncedSignature ?: return false
        return snapshotSyncedSignature() == before
    }
}
