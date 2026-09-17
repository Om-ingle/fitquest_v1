package com.example.mobileapp.core.session

import android.util.Log
import com.example.mobileapp.core.auth.IdentityProvider
import com.example.mobileapp.core.network.CoachCache
import com.example.mobileapp.core.network.LiveCoachStore
import com.example.mobileapp.core.run.ActiveRunAccountScope
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

/**
 * Keeps the things that live longer than a screen in step with the signed-in
 * account, and is the only component allowed to declare those things safe to
 * hold data.
 *
 * ### The problem this exists for
 *
 * A process-lifetime cache is, by definition, still there when the account
 * changes. That is how the isolation defect presented: sign in as B, run
 * something, sign out, sign in as A — and A is shown B's data. The Room half of
 * that is fixed by scoping the rows and having the repositories re-subscribe
 * when the account changes (`IdentityProvider.ownedFlow`). This class covers the
 * half that is not Room: the in-memory state that no query can filter, because
 * it was never keyed by anything.
 *
 * Three things have to follow the account, and none of them can be left to the
 * sign-out button:
 *
 *  * [CoachCache] holds one account's coach message, grounded in that account's
 *    run history. It cannot be shown to the next account.
 *  * [LiveCoachStore] holds the last message pushed down an authenticated
 *    socket. Same reasoning, and it arrives unsolicited so it is even easier to
 *    leave behind.
 *  * [ActiveRunAccountScope] holds a live run — sensors, a foreground
 *    notification, and a ticking timer. A run belongs to the account that
 *    started it; the next account must not be dropped onto its run screen.
 *
 * ### Why it observes the session rather than being called by sign-out
 *
 * `AuthSession.signOut()` is one of several ways a session ends: the refresh
 * token can be explicitly rejected mid-request, `restore()` can refuse a stored
 * session at startup, and an account switch is a sign-out followed by a sign-in
 * that may never pass through `AuthState.SignedOut` at all if the change is
 * observed in a single step. Subscribing to the subject covers every one of
 * those, including the transitions nobody thought to call a hook for. Coupling a
 * privacy guarantee to a function that has to remember to call it is how the
 * defect got here in the first place.
 *
 * ### Fail closed: this class is the only thing that opens the gate
 *
 * Observing the session is necessary but was not sufficient. Making this class
 * responsible for clearing the three surfaces also made it a single point of
 * failure for a privacy control, and that failure was not hypothetical: a
 * concrete-only `RunServiceLauncher` binding meant this class could not be
 * constructed at all, `FitQuestApp` caught and logged that, and the app ran on
 * with the isolation control simply absent — no crash, no symptom.
 *
 * So the surfaces no longer hold data by default. [AccountScopeGuard] starts
 * closed, and [CoachCache], [LiveCoachStore] and `ActiveRunController` refuse to
 * acquire anything while it is closed. `start()` opens it, and it is closed
 * again the moment the collector stops for any reason — so the gate is open
 * exactly while something is watching, and a coordinator that never runs leaves
 * three empty surfaces rather than three stale ones.
 *
 * The one thing this deliberately does NOT do is delete data. Signing out
 * preserves the account's rows — runs, hexes, quests, profile — and its
 * unfinished run checkpoint, so signing back in restores that account's local
 * history exactly as it was.
 */
class AccountScopeCoordinator(
    private val identity: IdentityProvider,
    private val coachCache: CoachCache,
    private val liveCoachStore: LiveCoachStore,
    private val activeRunScope: ActiveRunAccountScope,
    private val guard: AccountScopeGuard,
    /** Process-lifetime scope; the subscription must outlive every Activity. */
    private val scope: CoroutineScope,
) {

    private val started = AtomicBoolean(false)

    /**
     * Begin watching, and open the gate the account-scoped surfaces read.
     *
     * Idempotent, so resolving this twice (Koin is lazy, and `FitQuestApp`
     * resolves it eagerly) cannot install two collectors.
     *
     * The collector is started [CoroutineStart.UNDISPATCHED] so its first
     * emission — and the reset that emission performs — completes on the calling
     * thread before this returns. That makes "start() returned" mean "a reset has
     * already run", rather than "a coroutine has been scheduled somewhere". It
     * runs during `FitQuestApp.onCreate`, before any Activity exists, and the
     * reset is a no-op there by construction: nothing is signed in, and the
     * stores it clears are empty.
     */
    fun start() {
        if (!started.compareAndSet(false, true)) return

        // Open before the collector exists, close on its completion however it
        // completes. Between these two lines the gate is open with nothing
        // behind it, which is safe because the surfaces it protects are empty by
        // definition until something fetches into them — and nothing can, until
        // this method returns.
        guard.setActive(true)
        val collector = scope.launch(start = CoroutineStart.UNDISPATCHED) {
            var previous: String? = null
            identity.subject.distinctUntilChanged().collect { current ->
                val changed = current != previous
                previous = current
                if (changed) onAccountChanged(current)
            }
        }
        // Fires on normal completion, on cancellation, and on failure — and
        // fires immediately if the collector never ran, which is what a scope
        // that is already cancelled produces. There is no way for the gate to
        // stay open with no collector behind it.
        collector.invokeOnCompletion { stopWatching() }
    }

    /**
     * The signed-in account is now [current] (null when signed out).
     *
     * Runs on every change, including the collector's initial emission at
     * process start — where it clears caches that are empty and tells the run
     * controller about a subject change it will ignore because no run is live.
     * That is a no-op by construction rather than by a special case, so there is
     * no "first time through" branch that could be got wrong. It also means a
     * collector that starts late still performs a reset against whatever the
     * subject is by then, rather than assuming nothing changed while it was
     * absent.
     */
    private fun onAccountChanged(current: String?) {
        // Order matters only in that the run is stopped before the caches are
        // dropped: abandoning a run publishes nothing, so either order is
        // correct, but stopping first means no live writer can repopulate a
        // store between the clear and the next account's first read.
        activeRunScope.onAccountChanged(current)
        coachCache.clear()
        liveCoachStore.clear()
        Log.d(TAG, "account scope reset for subject ${current?.let(::maskSubject) ?: "<signed out>"}")
    }

    /**
     * The collector has stopped, so nothing is watching the session any more.
     *
     * Closing the gate is the whole point — the surfaces stop acquiring data —
     * but the data already in them has to go too, or a closed gate would only
     * stop the *next* leak. [onAccountChanged] is reused with a null subject
     * rather than duplicating the clearing: null can never equal a live run's
     * owner, so it drops any live run, and it is exactly the teardown path an
     * account change takes. The run's persisted checkpoint is left behind, as
     * always, so its owner is offered it back.
     *
     * Idempotent: closing an already-closed gate, clearing an empty store and
     * abandoning a run that is already gone are all no-ops.
     */
    private fun stopWatching() {
        guard.setActive(false)
        onAccountChanged(null)
        Log.w(TAG, "account scope control stopped — account-scoped surfaces are now closed")
    }

    private companion object {
        const val TAG = "FitQuestAccount"

        /**
         * Enough of the subject to correlate two log lines, never enough to be
         * a credential. The subject is a Supabase user id — not a secret, but
         * logcat is not the place for a stable per-user identifier either.
         */
        fun maskSubject(subject: String): String =
            if (subject.length <= 8) "…" else "${subject.take(8)}…"
    }
}
