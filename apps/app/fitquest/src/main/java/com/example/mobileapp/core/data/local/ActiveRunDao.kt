package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * DAO for the [ActiveRunEntity] checkpoint table, scoped to one account.
 *
 * REPLACE conflict on insert guarantees no duplicate checkpoint can exist for
 * the same account, even if a stale writer races a fresh run start. The lookup
 * is by owner rather than `LIMIT 1` over the whole table: there can be one row
 * per account at the same time (an account that signs out mid-run leaves its
 * checkpoint behind), so an unfiltered read could hand one account the run
 * another account is still in the middle of.
 */
@Dao
interface ActiveRunDao {

    @Query("SELECT * FROM active_run WHERE ownerSubject = :owner LIMIT 1")
    fun observeActiveRun(owner: String): Flow<ActiveRunEntity?>

    @Query("SELECT * FROM active_run WHERE ownerSubject = :owner LIMIT 1")
    suspend fun getActiveRun(owner: String): ActiveRunEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: ActiveRunEntity)

    @Query("DELETE FROM active_run WHERE ownerSubject = :owner")
    suspend fun clear(owner: String)
}
