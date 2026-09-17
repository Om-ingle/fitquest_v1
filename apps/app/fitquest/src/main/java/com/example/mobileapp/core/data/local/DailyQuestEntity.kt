package com.example.mobileapp.core.data.local

import androidx.room.Entity

/**
 * One day's quest, for one account.
 *
 * The primary key is composite `(ownerSubject, id)` because the id is derived
 * from the calendar, not from the user: [RoomQuestRepository] builds it as
 * `"${today}_steps_3k"`, so it is identical for every account on the same day.
 * With `id` alone as the key, the first account to open the app would own the
 * day's quest rows and every other account would be shown (and would progress)
 * those same rows.
 */
@Entity(tableName = "daily_quests", primaryKeys = ["ownerSubject", "id"])
data class DailyQuestEntity(
    val ownerSubject: String = LEGACY_UNOWNED_SUBJECT,
    val id: String,
    val title: String,
    val description: String,
    val targetMetric: String, // "STEPS", "HEXES", "DURATION"
    val targetValue: Int,
    val currentProgress: Int = 0,
    val isCompleted: Boolean = false,
    val rewardXp: Int = 50,
    val dateString: String // YYYY-MM-DD
)
