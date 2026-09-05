package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface RunSessionDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertSession(session: RunSessionEntity)

    @Query("UPDATE run_sessions SET xpEarned = :xpEarned, isSynced = 1 WHERE id = :sessionId")
    suspend fun markSynced(sessionId: String, xpEarned: Int)

    @Query("SELECT * FROM run_sessions ORDER BY endedAt DESC")
    fun observeAllSessions(): Flow<List<RunSessionEntity>>

    // Phase 4B.5 telemetry: all sessions whose start falls in [start, end) —
    // used to aggregate a device-local day's steps/minutes for the snapshot.
    @Query("SELECT * FROM run_sessions WHERE startedAt >= :start AND startedAt < :end ORDER BY startedAt")
    suspend fun getSessionsBetween(start: Long, end: Long): List<RunSessionEntity>

    @Query("SELECT * FROM run_sessions ORDER BY endedAt DESC LIMIT :limit")
    fun observeRecentSessions(limit: Int = 10): Flow<List<RunSessionEntity>>

    @Query("SELECT COUNT(*) FROM run_sessions")
    fun observeSessionCount(): Flow<Int>

    @Query("SELECT SUM(totalSteps) FROM run_sessions")
    fun observeLifetimeSteps(): Flow<Int?>

    @Query("SELECT SUM(distanceMeters) FROM run_sessions")
    fun observeLifetimeDistance(): Flow<Double?>
}
