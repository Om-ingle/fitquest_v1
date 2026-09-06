package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * DAO for the single-row [ActiveRunEntity] checkpoint table.
 *
 * REPLACE conflict on insert guarantees no duplicate active-run rows can
 * ever exist, even if a stale writer races a fresh run start.
 */
@Dao
interface ActiveRunDao {

    @Query("SELECT * FROM active_run LIMIT 1")
    fun observeActiveRun(): Flow<ActiveRunEntity?>

    @Query("SELECT * FROM active_run LIMIT 1")
    suspend fun getActiveRun(): ActiveRunEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: ActiveRunEntity)

    @Query("DELETE FROM active_run")
    suspend fun clear()
}
