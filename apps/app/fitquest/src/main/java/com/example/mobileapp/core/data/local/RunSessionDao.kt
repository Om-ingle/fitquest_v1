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

    // Marking synced also clears the stored replay payload: the server has
    // confirmed this run, so there is nothing left to replay.
    @Query("UPDATE run_sessions SET xpEarned = :xpEarned, isSynced = 1, pendingSyncPayloadJson = NULL WHERE id = :sessionId")
    suspend fun markSynced(sessionId: String, xpEarned: Int)

    // Persist the exact outbound payload (with run_id = session id) so a later
    // failed-sync retry can replay byte-identical data (Fix A).
    @Query("UPDATE run_sessions SET pendingSyncPayloadJson = :json WHERE id = :sessionId")
    suspend fun setPendingSyncPayload(sessionId: String, json: String)

    // Unsynced sessions, oldest first, for foreground reconciliation (Fix A).
    @Query("SELECT * FROM run_sessions WHERE isSynced = 0 ORDER BY startedAt ASC")
    suspend fun getUnsynced(): List<RunSessionEntity>

    // Synced sessions — used to infer which hexes the server already knows
    // about when best-effort reconstructing legacy (payload-less) runs.
    @Query("SELECT * FROM run_sessions WHERE isSynced = 1")
    suspend fun getSyncedSessions(): List<RunSessionEntity>

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
