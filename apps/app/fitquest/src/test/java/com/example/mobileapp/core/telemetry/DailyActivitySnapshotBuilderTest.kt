package com.example.mobileapp.core.telemetry

import com.example.mobileapp.core.data.local.RunSessionEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.text.SimpleDateFormat
import java.util.Locale

/**
 * JVM unit tests for the Phase 4B.5 telemetry snapshot builder. The snapshot
 * must aggregate ALL of the run's device-local day (including the session
 * just saved to Room) as ABSOLUTE values, so re-syncing the same day is
 * idempotent server-side.
 */
class DailyActivitySnapshotBuilderTest {

    private fun session(
        startedAt: Long,
        durationSeconds: Long,
        totalSteps: Int,
        capturedHexCount: Int = 0
    ) = RunSessionEntity(
        startedAt = startedAt,
        endedAt = startedAt + durationSeconds * 1000,
        durationSeconds = durationSeconds,
        totalSteps = totalSteps,
        distanceMeters = 0.0,
        caloriesBurned = 0,
        capturedHexCount = capturedHexCount,
        capturedHexIdsJson = "",
        xpEarned = 0
    )

    /**
     * Parses in the DEVICE-DEFAULT timezone — the builder itself keys days
     * by the device-local calendar, so the fixtures must follow the same
     * clock or the date filtering breaks on non-UTC machines.
     */
    private fun timestamp(dateKey: String, hour: Int, minute: Int = 0): Long {
        val format = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US)
        return format.parse("$dateKey $hour:$minute")!!.time
    }

    @Test
    fun `single session aggregates to a full snapshot`() {
        val start = timestamp("2026-09-05", 8)
        val snapshot = DailyActivitySnapshotBuilder.build(
            sessions = listOf(session(start, durationSeconds = 45 * 60, totalSteps = 5000, capturedHexCount = 2)),
            goalSteps = 6000,
            hexesOwned = 7,
            forTimestampMillis = start
        )!!

        assertEquals("2026-09-05", snapshot.activity_date)
        assertEquals(5000, snapshot.steps)
        assertEquals(45, snapshot.active_minutes)
        assertEquals(6000, snapshot.goal_steps)
        assertFalse(snapshot.goal_completed)
        assertEquals(7, snapshot.hexes_owned)
        assertEquals(2, snapshot.hexes_captured)
        // Not observable by the device in v1 — must stay null ("unknown"),
        // never a possibly-wrong zero.
        assertNull(snapshot.hexes_lost)
        assertNull(snapshot.defense_steps)
    }

    @Test
    fun `multiple sessions same day are summed as absolute day totals`() {
        val morning = timestamp("2026-09-05", 7)
        val evening = timestamp("2026-09-05", 19)
        val snapshot = DailyActivitySnapshotBuilder.build(
            sessions = listOf(
                session(morning, durationSeconds = 20 * 60, totalSteps = 2000, capturedHexCount = 1),
                session(evening, durationSeconds = 40 * 60, totalSteps = 4500, capturedHexCount = 3)
            ),
            goalSteps = 6000,
            hexesOwned = 9,
            forTimestampMillis = evening
        )!!

        assertEquals(6500, snapshot.steps)          // 2000 + 4500, not a delta
        assertEquals(60, snapshot.active_minutes)   // 20 + 40
        assertEquals(4, snapshot.hexes_captured)    // 1 + 3
        assertTrue(snapshot.goal_completed)         // 6500 >= 6000
    }

    @Test
    fun `sessions from other local days are excluded`() {
        val today = timestamp("2026-09-05", 10)
        val yesterday = timestamp("2026-09-04", 10)
        val snapshot = DailyActivitySnapshotBuilder.build(
            sessions = listOf(
                session(yesterday, durationSeconds = 60 * 60, totalSteps = 9999, capturedHexCount = 5),
                session(today, durationSeconds = 30 * 60, totalSteps = 1000)
            ),
            goalSteps = 6000,
            hexesOwned = 3,
            forTimestampMillis = today
        )!!

        assertEquals("2026-09-05", snapshot.activity_date)
        assertEquals(1000, snapshot.steps)
        assertEquals(0, snapshot.hexes_captured)
    }

    @Test
    fun `minutes are rounded from seconds not truncated`() {
        val start = timestamp("2026-09-05", 9)
        val snapshot = DailyActivitySnapshotBuilder.build(
            sessions = listOf(session(start, durationSeconds = 90, totalSteps = 100)),
            goalSteps = 6000,
            hexesOwned = 0,
            forTimestampMillis = start
        )!!
        assertEquals(2, snapshot.active_minutes) // 90 s -> 1.5 min -> 2
    }

    @Test
    fun `no session on the date returns null`() {
        val otherDay = timestamp("2026-09-04", 10)
        assertNull(
            DailyActivitySnapshotBuilder.build(
                sessions = listOf(session(otherDay, durationSeconds = 60, totalSteps = 100)),
                goalSteps = 6000,
                hexesOwned = 0,
                forTimestampMillis = timestamp("2026-09-05", 10)
            )
        )
        assertNull(
            DailyActivitySnapshotBuilder.build(
                sessions = emptyList(),
                goalSteps = 6000,
                hexesOwned = 0,
                forTimestampMillis = timestamp("2026-09-05", 10)
            )
        )
    }

    @Test
    fun `local day window spans midnight to midnight device-local`() {
        val elevenPm = timestamp("2026-09-05", 23, 30)

        val (start, end) = DailyActivitySnapshotBuilder.localDayWindow(elevenPm)
        assertEquals(elevenPm - (23 * 60 + 30) * 60 * 1000L, start)
        assertEquals(start + 24 * 60 * 60 * 1000L, end)
        // The date key of any timestamp inside the window matches the snapshot date.
        assertEquals(
            DailyActivitySnapshotBuilder.localDateKey(start),
            DailyActivitySnapshotBuilder.localDateKey(start + 1000)
        )
    }
}
