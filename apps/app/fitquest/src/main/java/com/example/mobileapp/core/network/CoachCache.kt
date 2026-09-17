package com.example.mobileapp.core.network

import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.session.AccountScopeGuard
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
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
 *
 * Account scoping: the cached response belongs to the account it was fetched
 * for, and the synced-run signature it is keyed on is now account-scoped too
 * ([RunSessionRepository] resolves the owner itself). [clear] is called when the
 * signed-in account changes so the next account never sees the previous one's
 * coach message.
 *
 * Fail closed: that guarantee depends on something reacting to the account
 * change, and a cache that is only cleared by a component which might not exist
 * is one that leaks when that component fails to start — which is exactly what
 * happened. So this cache refuses to *acquire* anything while
 * [AccountScopeGuard] is closed; it starts empty each process and stays empty
 * unless the control that will clear it is confirmed live. [clear] is never
 * gated: emptying is always the safe direction.
 */
class CoachCache(
    private val fetcher: CoachFetcher,
    private val runSessionRepository: RunSessionRepository,
    private val accountScope: AccountScopeGuard
) {

    private val _state = MutableStateFlow<CoachFetcher.Outcome?>(null)
    val state: StateFlow<CoachFetcher.Outcome?> = _state.asStateFlow()

    private val inflight = AtomicBoolean(false)

    // Bumped by [clear]. A fetch remembers the generation it started under and
    // refuses to publish if it changed, so a response that arrives after the
    // account changed cannot repopulate the cache with the previous account's
    // coach message.
    private val generation = AtomicLong(0L)

    // Ids of the run sessions that were synced when the current Success was
    // produced (null until the first successful load). A change means the
    // device sent the backend new activity → ask again on the next show.
    @Volatile
    private var syncedSignature: Set<String>? = null

    /**
     * Drop the cached response, for an account change.
     *
     * The cached text was generated for the account that was signed in when it
     * was fetched — it is grounded in that account's run history — so it must
     * not be shown to whoever signs in next. Clearing also drops the
     * [syncedSignature] bookkeeping, so the next Home entry fetches afresh
     * against the new account's synced runs rather than deciding nothing has
     * changed.
     *
     * Bumping [generation] is what makes this hold under a race: a request
     * already in flight when the account changes is left to finish (it cannot be
     * usefully cancelled) but is discarded on arrival instead of winning the
     * race against the clear.
     */
    fun clear() {
        generation.incrementAndGet()
        syncedSignature = null
        _state.value = null
    }

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
        // Checked before clearing state, so a closed gate leaves the card as it
        // is rather than dropping it to a loading state this call cannot fill.
        if (!accountScope.isActive()) return
        _state.value = null
        fetch(silent = false)
    }

    private suspend fun fetch(silent: Boolean) {
        // The single choke point for populating this cache. While the gate is
        // closed there is nothing that would clear the result on an account
        // change, so the result must not be acquired at all — returning here
        // leaves the state `null`, i.e. the card stays empty.
        if (!accountScope.isActive()) return
        if (!inflight.compareAndSet(false, true)) return
        val startedAt = generation.get()
        try {
            val signature = snapshotSyncedSignature()
            val outcome = withContext(Dispatchers.IO) { fetcher.fetchCoachMessage() }
            // The account changed while this was on the wire: the response
            // belongs to whoever was signed in when it was requested.
            if (generation.get() != startedAt) return
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
