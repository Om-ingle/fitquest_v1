package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * All access to `run_sessions`, scoped to one account.
 *
 * Every statement takes an `ownerSubject` and names it in its `WHERE` clause.
 * That is not a convention but an invariant: `OwnerScopedQueryTest` reflects
 * over this interface and fails if any `@Query` here omits the filter, because
 * an unfiltered one is exactly the defect this scoping exists to prevent — a
 * read that returns another account's runs, or a write that credits another
 * account's row.
 *
 * [insertSession] is the one statement without a filter, because it creates the
 * row rather than selecting one; the owner it files the row under comes from the
 * entity, which [RoomRunSessionRepository] stamps.
 */
@Dao
interface RunSessionDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertSession(session: RunSessionEntity)

    // Marking synced also clears the stored replay payload: the server has
    // confirmed this run, so there is nothing left to replay.
    @Query(
        "UPDATE run_sessions SET xpEarned = :xpEarned, isSynced = 1, pendingSyncPayloadJson = NULL " +
            "WHERE id = :sessionId AND ownerSubject = :owner"
    )
    suspend fun markSynced(owner: String, sessionId: String, xpEarned: Int)

    // Persist the exact outbound payload (with run_id = session id) so a later
    // failed-sync retry can replay byte-identical data (Fix A).
    @Query(
        "UPDATE run_sessions SET pendingSyncPayloadJson = :json " +
            "WHERE id = :sessionId AND ownerSubject = :owner"
    )
    suspend fun setPendingSyncPayload(owner: String, sessionId: String, json: String)

    // Unsynced sessions, oldest first, for foreground reconciliation (Fix A).
    @Query("SELECT * FROM run_sessions WHERE ownerSubject = :owner AND isSynced = 0 ORDER BY startedAt ASC")
    suspend fun getUnsynced(owner: String): List<RunSessionEntity>

    // Synced sessions — used to infer which hexes the server already knows
    // about when best-effort reconstructing legacy (payload-less) runs.
    @Query("SELECT * FROM run_sessions WHERE ownerSubject = :owner AND isSynced = 1")
    suspend fun getSyncedSessions(owner: String): List<RunSessionEntity>

    @Query("SELECT * FROM run_sessions WHERE ownerSubject = :owner ORDER BY endedAt DESC")
    fun observeAllSessions(owner: String): Flow<List<RunSessionEntity>>

    // Phase 4B.5 telemetry: all sessions whose start falls in [start, end) —
    // used to aggregate a device-local day's steps/minutes for the snapshot.
    @Query(
        "SELECT * FROM run_sessions WHERE ownerSubject = :owner " +
            "AND startedAt >= :start AND startedAt < :end ORDER BY startedAt"
    )
    suspend fun getSessionsBetween(owner: String, start: Long, end: Long): List<RunSessionEntity>

    @Query("SELECT * FROM run_sessions WHERE ownerSubject = :owner ORDER BY endedAt DESC LIMIT :limit")
    fun observeRecentSessions(owner: String, limit: Int): Flow<List<RunSessionEntity>>

    @Query("SELECT COUNT(*) FROM run_sessions WHERE ownerSubject = :owner")
    fun observeSessionCount(owner: String): Flow<Int>

    @Query("SELECT SUM(totalSteps) FROM run_sessions WHERE ownerSubject = :owner")
    fun observeLifetimeSteps(owner: String): Flow<Int?>

    @Query("SELECT SUM(distanceMeters) FROM run_sessions WHERE ownerSubject = :owner")
    fun observeLifetimeDistance(owner: String): Flow<Double?>
}
