package com.example.mobileapp.core.data.local

import kotlinx.coroutines.flow.Flow

interface RunSessionRepository {
    suspend fun saveSession(session: RunSessionEntity)
    suspend fun markSynced(sessionId: String, xpEarned: Int)
    fun observeRecentSessions(limit: Int = 10): Flow<List<RunSessionEntity>>
    fun observeAllSessions(): Flow<List<RunSessionEntity>>
    fun observeSessionCount(): Flow<Int>
    fun observeLifetimeSteps(): Flow<Int?>
    fun observeLifetimeDistance(): Flow<Double?>
}

class RoomRunSessionRepository(
    private val runSessionDao: RunSessionDao
) : RunSessionRepository {

    override suspend fun saveSession(session: RunSessionEntity) {
        runSessionDao.insertSession(session)
    }

    override suspend fun markSynced(sessionId: String, xpEarned: Int) {
        runSessionDao.markSynced(sessionId, xpEarned)
    }

    override fun observeRecentSessions(limit: Int): Flow<List<RunSessionEntity>> {
        return runSessionDao.observeRecentSessions(limit)
    }

    override fun observeAllSessions(): Flow<List<RunSessionEntity>> {
        return runSessionDao.observeAllSessions()
    }

    override fun observeSessionCount(): Flow<Int> {
        return runSessionDao.observeSessionCount()
    }

    override fun observeLifetimeSteps(): Flow<Int?> {
        return runSessionDao.observeLifetimeSteps()
    }

    override fun observeLifetimeDistance(): Flow<Double?> {
        return runSessionDao.observeLifetimeDistance()
    }
}
