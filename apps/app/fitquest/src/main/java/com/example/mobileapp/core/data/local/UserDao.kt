package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * All access to `user_profile`, scoped to one account.
 *
 * There are no defaulted `id = "local_user"` parameters any more. Every method
 * requires the owner explicitly, and the owner IS the primary key — so a call
 * that names the wrong account reads or writes a different row rather than
 * silently sharing one.
 *
 * The owner is the FIRST parameter of every statement here, including the ones
 * that carry other arguments (`updateDailyGoal`). That is not cosmetic:
 * `OwnerScopedQueryTest` enforces it across all six DAOs, so a method that does
 * not lead with an account cannot be added without the test failing — and a
 * method with no owner parameter at all would be one a caller could invoke
 * without ever deciding who the data belongs to.
 */
@Dao
interface UserDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertProfile(profile: UserProfileEntity)

    @Query("SELECT * FROM user_profile WHERE ownerSubject = :owner LIMIT 1")
    suspend fun getProfileById(owner: String): UserProfileEntity?

    @Query("SELECT * FROM user_profile WHERE ownerSubject = :owner LIMIT 1")
    fun observeProfile(owner: String): Flow<UserProfileEntity?>

    @Query("UPDATE user_profile SET isOnboardingCompleted = 1 WHERE ownerSubject = :owner")
    suspend fun setOnboardingCompleted(owner: String)

    @Query("UPDATE user_profile SET dailyStepGoal = :goal WHERE ownerSubject = :owner")
    suspend fun updateDailyGoal(owner: String, goal: Int)
}
