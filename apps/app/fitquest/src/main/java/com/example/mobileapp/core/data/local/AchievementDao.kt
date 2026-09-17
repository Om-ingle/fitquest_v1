package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * All access to `achievements`, scoped to one account.
 *
 * The ids are fixed constants shared by every account, so every statement
 * names the owner as well. [insertDefaultAchievements] keeps
 * `OnConflictStrategy.IGNORE`, which is what makes the composite key matter:
 * IGNORE skips a row that already exists, and with `(owner, id)` as the key the
 * rows that already exist are only ever the SAME account's — so each account
 * gets its own copy of the default set on first sign-in instead of the second
 * account silently receiving none.
 */
@Dao
interface AchievementDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertDefaultAchievements(achievements: List<AchievementEntity>)

    @Query("SELECT * FROM achievements WHERE ownerSubject = :owner ORDER BY isUnlocked DESC, id ASC")
    fun observeAllAchievements(owner: String): Flow<List<AchievementEntity>>

    @Query("SELECT * FROM achievements WHERE ownerSubject = :owner AND id = :id LIMIT 1")
    suspend fun getById(owner: String, id: String): AchievementEntity?

    @Query(
        "UPDATE achievements SET currentProgress = :progress, isUnlocked = :unlocked, " +
            "unlockedAt = :unlockedAt WHERE ownerSubject = :owner AND id = :id"
    )
    suspend fun updateAchievementProgress(
        owner: String,
        id: String,
        progress: Int,
        unlocked: Boolean,
        unlockedAt: Long?,
    )
}
