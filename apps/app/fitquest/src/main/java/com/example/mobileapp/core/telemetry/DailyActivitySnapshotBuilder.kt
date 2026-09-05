package com.example.mobileapp.core.telemetry

import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.network.models.DailyActivitySnapshot
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

/**
 * Builds the Phase 4B.5 daily telemetry snapshot from Room data, at the
 * moment a run is synced.
 *
 * The snapshot carries ABSOLUTE day-to-date values for the run's device-local
 * calendar date (the same date the app already uses for streaks and HomeTab),
 * aggregated over ALL of that date's saved run sessions — including the one
 * just saved, which is why [CaptureScreenModel][com.example.mobileapp.features.capture.CaptureScreenModel]
 * saves the session to Room before syncing. Re-sending the same day therefore
 * upserts to identical values server-side (idempotent by construction).
 *
 * hexes_lost and defense_steps are deliberately left null: the device cannot
 * observe rival steals and cannot attribute per-day defense steps reliably.
 */
object DailyActivitySnapshotBuilder {

    /** Device-local calendar date key (YYYY-MM-DD) for a timestamp. */
    fun localDateKey(timestampMillis: Long): String =
        SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date(timestampMillis))

    /**
     * [start, end) millis window of the device-local day containing
     * [timestampMillis] — used to narrow the Room query before the exact
     * local-date filtering below.
     */
    fun localDayWindow(timestampMillis: Long): Pair<Long, Long> {
        val calendar = Calendar.getInstance().apply {
            timeInMillis = timestampMillis
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        val start = calendar.timeInMillis
        calendar.add(Calendar.DAY_OF_MONTH, 1)
        return start to calendar.timeInMillis
    }

    /**
     * @param sessions all run sessions in the day's window (the caller may
     *   over-fetch; sessions from other local dates are filtered out here).
     * @param goalSteps the user's daily step goal (user_profile.dailyStepGoal).
     * @param hexesOwned end-of-day owned count (device mirror of territory).
     * @return the snapshot, or null when no session falls on that date
     *   (nothing to report — a fully idle day produces no sync, by design).
     */
    fun build(
        sessions: List<RunSessionEntity>,
        goalSteps: Int,
        hexesOwned: Int,
        forTimestampMillis: Long
    ): DailyActivitySnapshot? {
        val dateKey = localDateKey(forTimestampMillis)
        val daySessions = sessions.filter { localDateKey(it.startedAt) == dateKey }
        if (daySessions.isEmpty()) return null

        val steps = daySessions.sumOf { it.totalSteps }
        val activeMinutes = (daySessions.sumOf { it.durationSeconds } / 60.0).roundToInt()

        return DailyActivitySnapshot(
            activity_date = dateKey,
            steps = steps,
            active_minutes = activeMinutes,
            goal_steps = goalSteps,
            goal_completed = steps >= goalSteps,
            hexes_owned = hexesOwned,
            hexes_captured = daySessions.sumOf { it.capturedHexCount }
        )
    }
}
