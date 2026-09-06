package com.example.mobileapp.core.run

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build

/**
 * Shared identifiers + channel bootstrap for the active-run notification.
 * Constants live here so the foreground service (owner), the controller and
 * MainActivity's notification-tap deep link all agree.
 */
object RunNotifications {
    const val CHANNEL_ID = "fitquest_run_active"
    const val CHANNEL_NAME = "Active Run Tracking"
    const val NOTIFICATION_ID = 1001

    /** Extra carried on the service-start Intent. */
    const val EXTRA_RUN_ID = "fitquest.runId"
    const val EXTRA_STARTED_AT = "fitquest.startedAt"

    /** Action used by a notification tap to surface the active run screen. */
    const val ACTION_OPEN_RUN = "com.example.mobileapp.action.OPEN_RUN"

    /** Creates the channel idempotently (no-op after the first call). */
    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Live status of your active FitQuest run"
                setShowBadge(false)
            }
        )
    }
}
