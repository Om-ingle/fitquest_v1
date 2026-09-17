package com.example.mobileapp.core.run

import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.content.ContextCompat
import com.example.mobileapp.core.auth.IdentityProvider
import com.example.mobileapp.core.capture.RunSessionEngine
import com.example.mobileapp.core.data.local.ActiveRunEntity
import com.example.mobileapp.core.data.local.ActiveRunRepository
import com.example.mobileapp.core.session.AccountScopeGuard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * The part of the active-run lifecycle that account switching needs.
 *
 * A one-method interface rather than a direct dependency on
 * [ActiveRunController] so that `AccountScopeCoordinator` can be exercised
 * without a `Context`, a foreground service or a sensor stack — none of which
 * exist in a JVM test. Same declared-type discipline as the rest of the DI
 * graph: the consumer declares the narrow type and the container supplies the
 * implementation.
 */
interface ActiveRunAccountScope {
    /**
     * The signed-in account changed to [currentSubject] (null when signed out).
     * An implementation must drop any live run that belongs to a different
     * account, and must NOT delete that account's persisted checkpoint.
     */
    fun onAccountChanged(currentSubject: String?)
}

/**
 * Asks the system to start/stop [RunTrackingService].
 *
 * Extracted so that [ActiveRunController]'s decisions are testable without an
 * Android context: the conflict between "the run is over" and "the checkpoint
 * must survive an account switch" is the one place in this class where getting
 * it wrong destroys a user's data, and it was previously reachable only through
 * `ContextCompat.startForegroundService`.
 */
fun interface RunServiceLauncher {
    /** [action] is [RunTrackingService.ACTION_START_RUN] or `ACTION_STOP_RUN`. */
    fun launch(action: String)
}

/**
 * The production [RunServiceLauncher]. Kept as its own class so the direct
 * `Context` calls here — the only ones in [ActiveRunController] — are obvious.
 */
class ForegroundRunServiceLauncher(private val context: Context) : RunServiceLauncher {
    override fun launch(action: String) {
        when (action) {
            RunTrackingService.ACTION_START_RUN -> {
                val intent = Intent(context, RunTrackingService::class.java).apply {
                    this.action = action
                }
                // The runId/startedAt extras the service used to receive are
                // read from this process's singleton controller instead; the
                // service already resolves it from Koin, so duplicating them on
                // the Intent only created a second source of truth.
                ContextCompat.startForegroundService(context, intent)
            }
            else -> {
                // Context.stopService() would tear the service down via
                // onDestroy without delivering a new onStartCommand, so the
                // service's checkpoint-clear could never run. Instead deliver an
                // explicit ACTION_STOP to the (already running, foreground)
                // service; its handler clears + stops itself. Guarded in case
                // the service was never started (finish immediately after
                // start) — from the foreground that is a legal start-and-stop.
                val intent = Intent(context, RunTrackingService::class.java).apply {
                    this.action = action
                }
                try {
                    context.startService(intent)
                } catch (_: IllegalStateException) {
                    // App backgrounded mid-stop; service teardown falls back to
                    // onDestroy + the controller safety-net clear.
                }
            }
        }
    }
}

/**
 * Process-lifetime authority for the active run's identity + wall-clock timing,
 * and the only component that starts/stops [RunTrackingService].
 *
 * The HexCaptureEngine singleton already holds the authoritative live steps and
 * hex map; this controller adds what the engine deliberately does not: the
 * runId and the timestamp-based [RunTiming], which must survive screen
 * disposal (Voyager ScreenModels are recreated on every entry). Together the
 * engine + controller let the foreground service checkpoint the run without
 * depending on any screen being alive.
 *
 * Duplicate protection: startRun is a no-op if the same runId is already
 * active, and because the service is only ever started here it cannot be
 * launched twice for one run.
 *
 * Account scoping: a run is owned by the account that started it, recorded here
 * at [startRun]. If that account goes away while the run is live — see
 * [onAccountChanged] — the live machinery is torn down, but the persisted
 * checkpoint is deliberately left behind for the account it belongs to.
 *
 * Fail closed: that teardown only happens if something is watching for the
 * account change, so while [AccountScopeGuard] is closed no run may be started
 * at all. A run begun under a dead coordinator would be a live run that nothing
 * would ever hand back or drop, and the next account to sign in would be put on
 * its screen. Refusing the start costs the user a tracking session; permitting
 * it costs the next account its isolation. [onAccountChanged] and the rest of
 * the teardown path are never gated — stopping a run is always the safe
 * direction.
 */
class ActiveRunController(
    private val activeRunRepository: ActiveRunRepository,
    private val hexCaptureEngine: RunSessionEngine,
    private val identity: IdentityProvider,
    private val serviceLauncher: RunServiceLauncher,
    private val accountScope: AccountScopeGuard,
) : ActiveRunAccountScope {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val _runId = MutableStateFlow<String?>(null)
    val runId: StateFlow<String?> = _runId.asStateFlow()

    private val _timing = MutableStateFlow<RunTiming?>(null)
    val timing: StateFlow<RunTiming?> = _timing.asStateFlow()

    /** The account that started the live run, or null when no run is live. */
    @Volatile
    private var activeOwner: String? = null

    /**
     * Set while [onAccountChanged] is discarding a run that belongs to a
     * departed account. Only the teardown decision reads it, and only from the
     * service's worker, so it is volatile rather than locked: the worker can
     * observe this at any point after [abandonRun] nulls [_runId], and getting
     * it wrong there would delete a checkpoint that belongs to someone else.
     */
    @Volatile
    private var abandonedForAccountSwitch = false

    val isActive: Boolean get() = _runId.value != null

    fun currentRunId(): String? = _runId.value
    fun currentTiming(): RunTiming? = _timing.value

    /**
     * Marks the run active and brings the foreground service up. Idempotent
     * for the same runId (e.g. re-entry after a process-local screen recreation).
     */
    fun startRun(runId: String, timing: RunTiming) {
        if (!accountScope.isActive()) {
            // Silent to the user (the screen simply does not start a run) but
            // never silent here: without this line the only symptom of a dead
            // coordinator is a Start button that does nothing.
            Log.w(TAG, "refusing to start run $runId: account scope control is not active")
            return
        }
        if (_runId.value == runId) return
        activeOwner = identity.currentSubject()
        abandonedForAccountSwitch = false
        _runId.value = runId
        _timing.value = timing
        startService()
        persistNow()
    }

    /**
     * The signed-in account changed.
     *
     * A run started by the previous account must not stay live under the new
     * one: its notification, its step sensor subscription and its in-memory
     * tallies all belong to a user who is no longer signed in, and leaving the
     * run active would put the next account on the run screen looking at
     * somebody else's walk.
     *
     * The persisted checkpoint is NOT deleted — see [abandonRun]. It stays owned
     * by the account that started it, so that account is offered the run back
     * the next time it signs in.
     *
     * A no-op when the subject did not actually change (the same account
     * re-emitted, or a sign-in that produced the same subject), so this cannot
     * interrupt a live run for the account that owns it.
     */
    override fun onAccountChanged(currentSubject: String?) {
        val owner = activeOwner
        if (owner == null || _runId.value == null) return
        if (owner == currentSubject) return
        abandonRun()
    }

    fun pause(atMillis: Long = System.currentTimeMillis()) {
        val current = _timing.value ?: return
        if (current.isPaused) return
        _timing.value = current.paused(atMillis)
        persistNow()
    }

    fun resume(atMillis: Long = System.currentTimeMillis()) {
        val current = _timing.value ?: return
        if (!current.isPaused) return
        _timing.value = current.resumed(atMillis)
        persistNow()
    }

    /**
     * Finish path: immediately make the run inactive so the service's
     * periodic writer stops, stop the service (which removes the notification
     * and clears its checkpoint row), and clear the row here as a safety net.
     * Cleared only AFTER the completed session has been persisted by the caller.
     */
    fun finishRun() {
        _runId.value = null
        _timing.value = null
        activeOwner = null
        abandonedForAccountSwitch = false
        stopService()
        scope.launch { activeRunRepository.clearActiveRun() }
    }

    /**
     * Drops the LIVE run for an account that is no longer signed in, keeping the
     * checkpoint row it left behind.
     *
     * Ordering is what makes that hold. [_runId] is nulled first, which is what
     * the service's worker observes; but the worker converges on the same
     * teardown path as an explicit stop, and that path deletes the checkpoint.
     * [abandonedForAccountSwitch] is therefore set BEFORE [_runId] goes null and
     * is what [shouldClearCheckpointOnStop] reports, so whichever of the two
     * teardown routes the worker takes, it leaves the row alone — there is no
     * window in which it could observe a null run and a false flag.
     */
    private fun abandonRun() {
        abandonedForAccountSwitch = true
        _runId.value = null
        _timing.value = null
        activeOwner = null
        stopService()
        hexCaptureEngine.discardSession()
    }

    /**
     * Whether tearing the service down should also delete the persisted
     * checkpoint.
     *
     * False only while an account switch is discarding a run: that checkpoint
     * belongs to the account that started it, and is how that account gets the
     * run back.
     */
    fun shouldClearCheckpointOnStop(): Boolean = !abandonedForAccountSwitch

    /**
     * Builds the checkpoint to persist RIGHT NOW (transitions) using the same
     * live sources the service's periodic writer uses. A no-op when no run is
     * active.
     */
    fun persistNow() {
        val runId = _runId.value ?: return
        val timing = _timing.value ?: return
        val entity = buildCheckpointEntity(runId, timing) ?: return
        scope.launch { activeRunRepository.saveActiveRun(entity) }
    }

    /** Called by the service each tick. Null when no run is active. */
    fun checkpointSnapshot(nowMillis: Long = System.currentTimeMillis()): ActiveRunEntity? {
        val runId = _runId.value ?: return null
        val timing = _timing.value ?: return null
        return buildCheckpointEntity(runId, timing, nowMillis)
    }

    private fun buildCheckpointEntity(
        runId: String,
        timing: RunTiming,
        nowMillis: Long = System.currentTimeMillis()
    ): ActiveRunEntity? {
        val engine = hexCaptureEngine.state.value
        return timing.toCheckpointEntity(
            runId = runId,
            sessionSteps = engine.sessionSteps,
            distanceMeters = RunMetrics.distanceMeters(engine.sessionSteps),
            hexesToStepsJson = HexStepsCodec.encode(engine.hexesToSteps),
            lastCheckpointAtMillis = nowMillis
        )
    }

    private fun startService() {
        serviceLauncher.launch(RunTrackingService.ACTION_START_RUN)
    }

    private fun stopService() {
        serviceLauncher.launch(RunTrackingService.ACTION_STOP_RUN)
    }

    private companion object {
        const val TAG = "FitQuestRun"
    }
}
