package com.example.mobileapp.core.data.local

import androidx.room.Entity

/**
 * One achievement track, for one account.
 *
 * The primary key is composite `(ownerSubject, id)` because the ids are fixed
 * constants (`"first_hex"`, `"streak_7"`, …) shared by every account, and
 * `ensureDefaultAchievements` inserts them with `OnConflictStrategy.IGNORE`.
 * With `id` alone as the key that IGNORE would silently skip creating the rows
 * for the second account, leaving that account with no achievements at all;
 * and progress updates, which are keyed by id, would advance the first
 * account's unlocked state.
 */
@Entity(tableName = "achievements", primaryKeys = ["ownerSubject", "id"])
data class AchievementEntity(
    val ownerSubject: String = LEGACY_UNOWNED_SUBJECT,
    val id: String,
    val title: String,
    val description: String,
    val category: String, // "CONQUEST", "ENDURANCE", "STREAK"
    val iconName: String,
    val currentProgress: Int = 0,
    val maxProgress: Int,
    val isUnlocked: Boolean = false,
    val unlockedAt: Long? = null
)
