package com.example.mobileapp.core.run

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.example.mobileapp.core.capture.HexCaptureEngine
import com.example.mobileapp.core.data.local.ActiveRunEntity
import com.example.mobileapp.core.data.local.ActiveRunRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

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
 */
class ActiveRunController(
    private val context: Context,
    private val activeRunRepository: ActiveRunRepository,
    private val hexCaptureEngine: HexCaptureEngine
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val _runId = MutableStateFlow<String?>(null)
    val runId: StateFlow<String?> = _runId.asStateFlow()

    private val _timing = MutableStateFlow<RunTiming?>(null)
    val timing: StateFlow<RunTiming?> = _timing.asStateFlow()

    val isActive: Boolean get() = _runId.value != null

    fun currentRunId(): String? = _runId.value
    fun currentTiming(): RunTiming? = _timing.value

    /**
     * Marks the run active and brings the foreground service up. Idempotent
     * for the same runId (e.g. re-entry after a process-local screen recreation).
     */
    fun startRun(runId: String, timing: RunTiming) {
        if (_runId.value == runId) return
        _runId.value = runId
        _timing.value = timing
        startService()
        persistNow()
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
        stopService()
        scope.launch { activeRunRepository.clearActiveRun() }
    }

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
        val intent = Intent(context, RunTrackingService::class.java).apply {
            action = RunTrackingService.ACTION_START_RUN
            putExtra(RunNotifications.EXTRA_RUN_ID, _runId.value)
            putExtra(RunNotifications.EXTRA_STARTED_AT, _timing.value?.startedAtMillis ?: 0L)
        }
        ContextCompat.startForegroundService(context, intent)
    }

    /**
     * Context.stopService() would tear the service down via onDestroy without
     * delivering a new onStartCommand, so the service's checkpoint-clear could
     * never run. Instead deliver an explicit ACTION_STOP to the (already
     * running, foreground) service; its handler clears + stops itself.
     * Guarded in case the service was never started (finish immediately after
     * start) — from the foreground that is a legal start-and-stop.
     */
    private fun stopService() {
        val intent = Intent(context, RunTrackingService::class.java).apply {
            action = RunTrackingService.ACTION_STOP_RUN
        }
        try {
            context.startService(intent)
        } catch (_: IllegalStateException) {
            // App backgrounded mid-stop; service teardown falls back to
            // onDestroy + the controller safety-net clear below.
        }
    }
}
