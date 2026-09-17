package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * All access to `daily_quests`, scoped to one account.
 *
 * The id is `"${date}_${slug}"`, so it is the same for every account on a given
 * day — every statement names the owner as well, and [updateProgress] is keyed
 * by `(owner, id)` so a progress write can only ever advance the row belonging
 * to the account that earned it.
 */
@Dao
interface DailyQuestDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertQuests(quests: List<DailyQuestEntity>)

    @Query("SELECT * FROM daily_quests WHERE ownerSubject = :owner AND dateString = :date ORDER BY isCompleted ASC")
    fun observeQuestsForDate(owner: String, date: String): Flow<List<DailyQuestEntity>>

    @Query("SELECT * FROM daily_quests WHERE ownerSubject = :owner AND dateString = :date")
    suspend fun getQuestsForDate(owner: String, date: String): List<DailyQuestEntity>

    @Query(
        "UPDATE daily_quests SET currentProgress = :progress, isCompleted = :completed " +
            "WHERE ownerSubject = :owner AND id = :id"
    )
    suspend fun updateProgress(owner: String, id: String, progress: Int, completed: Boolean)
}
