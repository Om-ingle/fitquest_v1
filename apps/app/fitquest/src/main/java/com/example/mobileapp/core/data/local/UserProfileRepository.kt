package com.example.mobileapp.core.data.local

import android.util.Log
import com.example.mobileapp.core.auth.IdentityProvider
import kotlinx.coroutines.flow.Flow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

interface UserProfileRepository {
    fun observeProfile(): Flow<UserProfileEntity?>
    suspend fun getProfile(): UserProfileEntity
    suspend fun saveProfile(profile: UserProfileEntity)
    suspend fun completeOnboarding()
    suspend fun updateDailyGoal(goal: Int)
    suspend fun recordCompletedSession(
        steps: Int,
        distanceMeters: Double,
        calories: Int,
        hexCount: Int,
        xp: Int
    ): UserProfileEntity
}

/**
 * The account's profile, keyed by account.
 *
 * This class is where the observed isolation defect actually lived. It used to
 * read and write `WHERE id = "local_user"` — one row on the device, shared by
 * every account that ever signed in, holding the level, the lifetime totals,
 * the streak AND `isOnboardingCompleted`. Signing in as a different account
 * therefore showed that account the previous one's stats, and let it skip
 * onboarding.
 *
 * Now the account is the primary key. An account with no row on this device gets
 * one created on first read ([getProfile]), freshly defaulted — which is what
 * makes onboarding unskippable for a new account: there is no other account's
 * "already onboarded" flag it could inherit.
 */
class RoomUserProfileRepository(
    private val userDao: UserDao,
    private val identity: IdentityProvider,
) : UserProfileRepository {

    override fun observeProfile(): Flow<UserProfileEntity?> =
        identity.ownedFlow<UserProfileEntity?>(null) { owner -> userDao.observeProfile(owner) }

    /**
     * The signed-in account's profile, created with defaults on first read.
     *
     * Cold-start routing depends on this: no row means a brand-new account on
     * this device, which means onboarding. Persisting the default immediately is
     * deliberate — it makes the account's existence durable, so the row the user
     * is about to fill in during onboarding is the one onboarding writes to.
     *
     * With no session there is no account to create a row for, so a transient
     * default is returned and NOTHING is written. Callers reach here only behind
     * the auth gate, and the returned value is a display placeholder; writing it
     * would create a profile owned by nobody.
     */
    override suspend fun getProfile(): UserProfileEntity {
        val owner = identity.currentSubject()
        if (owner == null) {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("UserProfileRepository", "getProfile (not persisted)"))
            return UserProfileEntity(lastActiveDate = todayString())
        }
        val existing = userDao.getProfileById(owner)
        if (existing != null) return existing
        val created = UserProfileEntity(ownerSubject = owner, lastActiveDate = todayString())
        userDao.upsertProfile(created)
        return created
    }

    override suspend fun saveProfile(profile: UserProfileEntity) {
        val owner = identity.currentSubject()
        if (owner == null) {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("UserProfileRepository", "saveProfile"))
            return
        }
        // Stamp rather than trust: onboarding builds a profile without knowing
        // which account is signed in, and the caller must not be able to write
        // into another account's row by passing its id.
        userDao.upsertProfile(profile.copy(ownerSubject = owner))
    }

    override suspend fun completeOnboarding() {
        val current = getProfile()
        saveProfile(current.copy(isOnboardingCompleted = true))
    }

    override suspend fun updateDailyGoal(goal: Int) {
        val owner = identity.currentSubject()
        if (owner == null) {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("UserProfileRepository", "updateDailyGoal"))
            return
        }
        userDao.updateDailyGoal(owner, goal)
    }

    override suspend fun recordCompletedSession(
        steps: Int,
        distanceMeters: Double,
        calories: Int,
        hexCount: Int,
        xp: Int
    ): UserProfileEntity {
        val current = getProfile()
        val today = todayString()

        // Streak calculation
        val isConsecutive = isConsecutiveDay(current.lastActiveDate, today)
        val isSameDay = current.lastActiveDate == today
        val newStreak = when {
            isSameDay -> current.currentStreak
            isConsecutive -> current.currentStreak + 1
            else -> 1
        }
        val longestStreak = maxOf(newStreak, current.longestStreak)

        val newLifetimeSteps = current.totalLifetimeSteps + steps
        val newLifetimeDistance = current.totalDistanceMeters + distanceMeters
        val newLifetimeCalories = current.totalCalories + calories
        val newTotalXp = current.xp + xp

        // Simple level progression formula: Level = 1 + (XP / 250)
        val newLevel = 1 + (newTotalXp / 250)

        val updated = current.copy(
            totalLifetimeSteps = newLifetimeSteps,
            totalDistanceMeters = newLifetimeDistance,
            totalCalories = newLifetimeCalories,
            xp = newTotalXp,
            level = newLevel,
            currentStreak = newStreak,
            longestStreak = longestStreak,
            lastActiveDate = today
        )
        saveProfile(updated)
        return updated
    }

    private fun todayString(): String {
        return SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
    }

    private fun isConsecutiveDay(prevDateStr: String, currentDateStr: String): Boolean {
        if (prevDateStr.isEmpty()) return false
        return try {
            val format = SimpleDateFormat("yyyy-MM-dd", Locale.US)
            val prev = format.parse(prevDateStr)?.time ?: return false
            val curr = format.parse(currentDateStr)?.time ?: return false
            val diffHours = (curr - prev) / (1000 * 60 * 60)
            diffHours in 20..48
        } catch (_: Exception) {
            false
        }
    }
}
