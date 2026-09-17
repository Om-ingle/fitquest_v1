package com.example.mobileapp.core.data.local

import android.util.Log
import com.example.mobileapp.core.auth.IdentityProvider
import kotlinx.coroutines.flow.Flow

/**
 * Persistence for the active-run recovery checkpoint.
 *
 * Kept deliberately small — it only manages the single in-progress row that
 * survives process death. Completed runs continue to use
 * [RunSessionRepository] (Room -> RunSyncer).
 *
 * One row per account, so [clearActiveRun] only ever deletes the signed-in
 * account's row: an account that signs out mid-run leaves its checkpoint
 * behind, and the account that signs in next gets `null` from [getActiveRun]
 * rather than being offered a run it never started.
 */
interface ActiveRunRepository {
    fun observeActiveRun(): Flow<ActiveRunEntity?>
    suspend fun getActiveRun(): ActiveRunEntity?
    suspend fun saveActiveRun(entity: ActiveRunEntity)
    suspend fun clearActiveRun()
}

class RoomActiveRunRepository(
    private val dao: ActiveRunDao,
    private val identity: IdentityProvider,
) : ActiveRunRepository {

    override fun observeActiveRun(): Flow<ActiveRunEntity?> =
        identity.ownedFlow<ActiveRunEntity?>(null) { owner -> dao.observeActiveRun(owner) }

    override suspend fun getActiveRun(): ActiveRunEntity? {
        val owner = identity.currentSubject() ?: return null
        return dao.getActiveRun(owner)
    }

    override suspend fun saveActiveRun(entity: ActiveRunEntity) {
        val owner = identity.currentSubject()
        if (owner == null) {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("ActiveRunRepository", "saveActiveRun"))
            return
        }
        dao.upsert(entity.copy(ownerSubject = owner))
    }

    override suspend fun clearActiveRun() {
        val owner = identity.currentSubject()
        if (owner == null) {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("ActiveRunRepository", "clearActiveRun"))
            return
        }
        dao.clear(owner)
    }
}
