package com.example.mobileapp.core.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * The signed-in account's game profile and its onboarding state.
 *
 * The primary key IS the account: `ownerSubject` holds the Supabase Auth user
 * id. It replaces the old fixed `id = "local_user"` singleton, which was the
 * root of the isolation defect — one row on the device meant one profile, one
 * onboarding answer and one set of lifetime totals shared by every account that
 * ever signed in. Because the row is now keyed by account, an account that has
 * never signed in on this device has no profile at all, and
 * [RoomUserProfileRepository.getProfile] creates it fresh — so a previous
 * account's completed onboarding can no longer let the next account skip
 * onboarding.
 */
@Entity(tableName = "user_profile")
data class UserProfileEntity(
    @PrimaryKey val ownerSubject: String = LEGACY_UNOWNED_SUBJECT,
    val username: String = "Scout",
    val avatarName: String = "runner_1",
    val dailyStepGoal: Int = 6000,
    val level: Int = 1,
    val xp: Int = 0,
    val currentStreak: Int = 1,
    val longestStreak: Int = 1,
    val lastActiveDate: String = "", // YYYY-MM-DD
    val totalLifetimeSteps: Int = 0,
    val totalDistanceMeters: Double = 0.0,
    val totalCalories: Int = 0,
    val isOnboardingCompleted: Boolean = false,
    val createdAt: Long = System.currentTimeMillis()
)
