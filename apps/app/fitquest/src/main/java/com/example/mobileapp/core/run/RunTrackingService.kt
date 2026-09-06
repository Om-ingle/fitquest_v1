package com.example.mobileapp.core.run

import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import com.example.mobileapp.MainActivity
import com.example.mobileapp.R
import com.example.mobileapp.core.data.local.ActiveRunEntity
import com.example.mobileapp.core.data.local.ActiveRunRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.koin.android.ext.android.inject
import java.util.Locale

/**
 * Foreground service for an active run. Responsibilities:
 *
 *  - Keeps the process foreground while a run is active (type [ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION],
 *    started from the foreground, so no ACCESS_BACKGROUND_LOCATION is needed).
 *  - Owns the persistent "🏃 FitQuest Run Active" notification and periodically
 *    refreshes it with live steps/distance. Tapping returns to the run screen.
 *  - Is the periodic Room checkpoint writer for the active-run row.
 *
 * It deliberately does NOT start the capture engine — the ScreenModel owns the
 * engine lifecycle. The service reads the singleton [ActiveRunController]
 * (runId + RunTiming) and [HexCaptureEngine] (live steps/hexes) each tick, so
 * it keeps working after the screen is disposed (e.g. user pressed Home).
 *
 * A single worker coroutine plus a [Mutex] serialise all Room checkpoint
 * writes with the final clear, so a finish can never be re-ordered after a
 * stray periodic write (the worker is cancelled before the clear acquires the
 * lock; cancellation aborts a write still waiting on it).
 */
class RunTrackingService : Service() {

    private val controller: ActiveRunController by inject()
    private val activeRunRepository: ActiveRunRepository by inject()

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    // Shutdown cleanup runs on its own scope so onDestroy (which cancels
    // serviceScope) can never abort an in-flight checkpoint clear.
    private val shutdownScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val monitorMutex = Mutex()
    private var monitorJob: Job? = null

    /** Checkpoint/notification cadence: frequent enough to be recoverable, not so
     * frequent it wastes battery (never per sensor event). */
    private val tickMillis = 5_000L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        RunNotifications.ensureChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START_RUN -> {
                val snapshot = controller.checkpointSnapshot()
                if (snapshot == null) {
                    // No active run behind this start request — nothing to keep alive.
                    stopSelf()
                    return START_NOT_STICKY
                }
                goForeground(snapshot)
                beginMonitoring()
                return START_STICKY
            }
            ACTION_STOP_RUN -> {
                shutdown()
                return START_NOT_STICKY
            }
            else -> {
                // System-restarted the service (START_STICKY) but no run is active:
                // there is nothing to keep foreground, so stop cleanly.
                if (controller.isActive) {
                    controller.checkpointSnapshot()?.let { goForeground(it) }
                    beginMonitoring()
                    return START_STICKY
                }
                stopSelf()
                return START_NOT_STICKY
            }
        }
    }

    override fun onDestroy() {
        monitorJob?.cancel()
        monitorJob = null
        serviceScope.cancel()
        super.onDestroy()
    }

    // ── Foreground + notification ───────────────────────────────────────────

    private fun goForeground(snapshot: ActiveRunEntity) {
        val notification = buildNotification(snapshot)
        ServiceCompat.startForeground(
            this,
            RunNotifications.NOTIFICATION_ID,
            notification,
            ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        )
    }

    private fun buildNotification(snapshot: ActiveRunEntity): android.app.Notification {
        val contentText = buildString {
            append(snapshot.sessionSteps)
            append(" steps • ")
            append(String.format(Locale.US, "%.2f km", snapshot.distanceMeters / 1000.0))
        }
        val builder = NotificationCompat.Builder(this, RunNotifications.CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_run)
            .setContentTitle("🏃 FitQuest Run Active")
            .setContentText(contentText)
            .setOngoing(true)
            .setSilent(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(openRunPendingIntent())
        if (android.os.Build.VERSION.SDK_INT >= 31) {
            builder.foregroundServiceBehavior = NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE
        }
        return builder.build()
    }

    private fun openRunPendingIntent(): PendingIntent {
        val intent = Intent(this, MainActivity::class.java).apply {
            action = RunNotifications.ACTION_OPEN_RUN
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        return PendingIntent.getActivity(
            this,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    // ── Checkpoint loop ─────────────────────────────────────────────────────

    private fun beginMonitoring() {
        if (monitorJob?.isActive == true) return
        monitorJob = serviceScope.launch {
            while (isActive) {
                val snapshot = controller.checkpointSnapshot()
                if (snapshot == null) {
                    // Run ended underneath the service (the controller already
                    // nulled it) before ACTION_STOP was handled. Tear down the
                    // checkpoint and notification exactly like a stop so nothing
                    // leaks, then leave the loop.
                    teardownFromWorker()
                    return@launch
                }
                monitorMutex.withLock {
                    if (!isActive) return@withLock
                    activeRunRepository.saveActiveRun(snapshot)
                }
                // Refresh the notification content without re-issuing
                // startForeground each tick. If notification permission was
                // denied on 13+, notify() no-ops but the FGS still runs.
                NotificationManagerCompat.from(this@RunTrackingService)
                    .notify(RunNotifications.NOTIFICATION_ID, buildNotification(snapshot))
                delay(tickMillis)
            }
        }
    }

    private fun shutdown() {
        val job = monitorJob
        monitorJob = null
        job?.cancel()
        runTeardown(job)
    }

    /** Worker observed the run disappear; nothing left to join before cleanup. */
    private fun teardownFromWorker() {
        monitorJob = null
        runTeardown(null)
    }

    /**
     * Serialise with any in-flight periodic write, then clear. [monitor] is
     * joined first so a tick that is mid-[NotificationManagerCompat.notify] can
     * never re-post the notification after we remove it; the explicit cancel is
     * the belt-and-braces for that same window (a notify() racing
     * [ServiceCompat.stopForeground] leaves the ongoing notification behind).
     */
    private fun runTeardown(monitor: Job?) {
        shutdownScope.launch {
            monitor?.join()
            monitorMutex.withLock {
                activeRunRepository.clearActiveRun()
            }
            ServiceCompat.stopForeground(
                this@RunTrackingService,
                ServiceCompat.STOP_FOREGROUND_REMOVE
            )
            NotificationManagerCompat.from(this@RunTrackingService)
                .cancel(RunNotifications.NOTIFICATION_ID)
            stopSelf()
        }
    }

    companion object {
        const val ACTION_START_RUN = "com.example.mobileapp.action.START_RUN"
        const val ACTION_STOP_RUN = "com.example.mobileapp.action.STOP_RUN"
    }
}
