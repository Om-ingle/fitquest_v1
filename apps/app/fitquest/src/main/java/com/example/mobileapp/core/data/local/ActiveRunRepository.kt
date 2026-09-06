package com.example.mobileapp.core.data.local

import kotlinx.coroutines.flow.Flow

/**
 * Persistence for the active-run recovery checkpoint.
 *
 * Kept deliberately small — it only manages the single in-progress row that
 * survives process death. Completed runs continue to use
 * [RunSessionRepository] (Room -> RunSyncer).
 */
interface ActiveRunRepository {
    fun observeActiveRun(): Flow<ActiveRunEntity?>
    suspend fun getActiveRun(): ActiveRunEntity?
    suspend fun saveActiveRun(entity: ActiveRunEntity)
    suspend fun clearActiveRun()
}

class RoomActiveRunRepository(
    private val dao: ActiveRunDao
) : ActiveRunRepository {

    override fun observeActiveRun(): Flow<ActiveRunEntity?> = dao.observeActiveRun()

    override suspend fun getActiveRun(): ActiveRunEntity? = dao.getActiveRun()

    override suspend fun saveActiveRun(entity: ActiveRunEntity) = dao.upsert(entity)

    override suspend fun clearActiveRun() = dao.clear()
}
