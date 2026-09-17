package com.example.mobileapp.core.data.local

import android.util.Log
import com.example.mobileapp.core.auth.IdentityProvider
import kotlinx.coroutines.flow.Flow

interface RunSessionRepository {
    suspend fun saveSession(session: RunSessionEntity)
    suspend fun markSynced(sessionId: String, xpEarned: Int)
    suspend fun setPendingSyncPayload(sessionId: String, json: String)
    suspend fun getSessionsBetween(start: Long, end: Long): List<RunSessionEntity>
    suspend fun getUnsynced(): List<RunSessionEntity>
    suspend fun getSyncedSessions(): List<RunSessionEntity>
    fun observeRecentSessions(limit: Int = 10): Flow<List<RunSessionEntity>>
    fun observeAllSessions(): Flow<List<RunSessionEntity>>
    fun observeSessionCount(): Flow<Int>
    fun observeLifetimeSteps(): Flow<Int?>
    fun observeLifetimeDistance(): Flow<Double?>
}

/**
 * Run history, filed under the signed-in account.
 *
 * Every method resolves the account from [IdentityProvider] itself rather than
 * taking it from the caller. That is the whole point: the run screen, the
 * reconciler and the coach cache all read "my runs" and none of them should be
 * able to ask for anyone else's, so the owner is not a parameter they can get
 * wrong. The one-shot reads refuse when nobody is signed in; the observers
 * switch to the new account's rows when the account changes.
 */
class RoomRunSessionRepository(
    private val runSessionDao: RunSessionDao,
    private val identity: IdentityProvider,
) : RunSessionRepository {

    override suspend fun saveSession(session: RunSessionEntity) {
        val owner = identity.currentSubject() ?: return refuse("saveSession")
        // Stamp the owner rather than trusting the entity's: a finished run is
        // built by the capture screen, which has no business knowing which
        // account is signed in, so the value it passes is a placeholder.
        runSessionDao.insertSession(session.copy(ownerSubject = owner))
    }

    override suspend fun markSynced(sessionId: String, xpEarned: Int) {
        val owner = identity.currentSubject() ?: return refuse("markSynced")
        runSessionDao.markSynced(owner, sessionId, xpEarned)
    }

    override suspend fun setPendingSyncPayload(sessionId: String, json: String) {
        val owner = identity.currentSubject() ?: return refuse("setPendingSyncPayload")
        runSessionDao.setPendingSyncPayload(owner, sessionId, json)
    }

    override suspend fun getSessionsBetween(start: Long, end: Long): List<RunSessionEntity> {
        val owner = identity.currentSubject() ?: return refuseAndReturn("getSessionsBetween", emptyList())
        return runSessionDao.getSessionsBetween(owner, start, end)
    }

    override suspend fun getUnsynced(): List<RunSessionEntity> {
        val owner = identity.currentSubject() ?: return refuseAndReturn("getUnsynced", emptyList())
        return runSessionDao.getUnsynced(owner)
    }

    override suspend fun getSyncedSessions(): List<RunSessionEntity> {
        val owner = identity.currentSubject() ?: return refuseAndReturn("getSyncedSessions", emptyList())
        return runSessionDao.getSyncedSessions(owner)
    }

    override fun observeRecentSessions(limit: Int): Flow<List<RunSessionEntity>> =
        identity.ownedFlow(emptyList()) { owner -> runSessionDao.observeRecentSessions(owner, limit) }

    override fun observeAllSessions(): Flow<List<RunSessionEntity>> =
        identity.ownedFlow(emptyList()) { owner -> runSessionDao.observeAllSessions(owner) }

    override fun observeSessionCount(): Flow<Int> =
        identity.ownedFlow(0) { owner -> runSessionDao.observeSessionCount(owner) }

    override fun observeLifetimeSteps(): Flow<Int?> =
        identity.ownedFlow(null) { owner -> runSessionDao.observeLifetimeSteps(owner) }

    override fun observeLifetimeDistance(): Flow<Double?> =
        identity.ownedFlow(null) { owner -> runSessionDao.observeLifetimeDistance(owner) }

    private fun refuse(action: String) {
        Log.w(OWNER_LOG_TAG, ownerlessRefusal("RunSessionRepository", action))
    }

    private fun <T> refuseAndReturn(action: String, value: T): T {
        refuse(action)
        return value
    }
}
