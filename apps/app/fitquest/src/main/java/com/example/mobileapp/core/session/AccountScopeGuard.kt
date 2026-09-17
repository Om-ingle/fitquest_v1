package com.example.mobileapp.core.session

import java.util.concurrent.atomic.AtomicBoolean

/**
 * Whether the account-scope control is live, and therefore whether the
 * process-lifetime, account-scoped surfaces are allowed to hold data at all.
 *
 * ### Why this exists
 *
 * The three surfaces that outlive a screen — [com.example.mobileapp.core.network.CoachCache],
 * [com.example.mobileapp.core.network.LiveCoachStore] and the live run in
 * `ActiveRunController` — are each cleared by [AccountScopeCoordinator] when the
 * signed-in account changes. That made the coordinator a **single point of
 * failure for a privacy control**: if it could not be constructed, nothing
 * cleared them, and the app carried the previous account's coach message and
 * live run into the next account's session.
 *
 * That is not hypothetical. `AppModule` registered only the concrete
 * `ForegroundRunServiceLauncher`, so `ActiveRunController` could not be built,
 * so the coordinator could not be built, so `FitQuestApp` caught the failure,
 * logged it, and ran on — with the isolation control simply absent. No crash,
 * no visible symptom, and the defect was found only by reading logcat on a
 * device.
 *
 * ### The inversion this makes
 *
 * The old design was fail-open: the surfaces held data, and a control was
 * supposed to come along and clear them. This makes the **safe state the
 * default**: the gate starts CLOSED, the surfaces refuse to acquire data while
 * it is closed, and [AccountScopeCoordinator] is the only thing that opens it.
 * Forgetting to wire the coordinator therefore yields silence, not a leak — a
 * missing feature rather than a privacy breach. A control that must be
 * remembered is one that can be forgotten; a default that is already safe is
 * not.
 *
 * ### Why not just crash
 *
 * Crashing on a broken DI graph is the loudest possible failure and would have
 * made the original defect unmissable, but it turns any such defect into a
 * launch loop on a user's device. `DeclaredTypeBindingTest` already catches this
 * exact class of wiring mistake in the build, so the residual case is defended
 * in depth, not by the crash. The app stays usable; the three account-scoped
 * surfaces stay empty until something is watching them.
 *
 * ### What it is not
 *
 * Not a session check. It says nothing about whether anyone is signed in — only
 * about whether the thing that reacts to an account *change* is running. A
 * closed gate with a signed-in user is the correct and expected state during the
 * window between process start and the coordinator's first emission, and it is
 * the permanent state if that emission never happens.
 */
class AccountScopeGuard {

    private val open = AtomicBoolean(false)

    /**
     * True once a live collector is watching the session for account changes.
     *
     * Read on every fetch/publish/start, so it is a plain atomic read rather than
     * a suspending flow consultation — the callers are hot paths (Home entry, a
     * WebSocket push, the Start button) and none of them should have to be
     * suspend-aware just to ask.
     */
    fun isActive(): Boolean = open.get()

    /**
     * Open or close the gate. Called by [AccountScopeCoordinator] and by nothing
     * else: it is the only component that knows when the collector it installed
     * has actually begun, and when it has stopped.
     */
    fun setActive(active: Boolean) {
        open.set(active)
    }
}
