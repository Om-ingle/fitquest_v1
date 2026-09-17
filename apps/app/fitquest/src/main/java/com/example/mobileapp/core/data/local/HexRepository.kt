package com.example.mobileapp.core.data.local

import android.util.Log
import com.example.mobileapp.core.auth.IdentityProvider
import kotlinx.coroutines.flow.Flow

interface HexRepository {
    fun observeCapturedHexes(): Flow<List<CapturedHexEntity>>
    suspend fun mergeSessionHexes(sessionHexesToSteps: Map<String, Int>)
    // One-shot snapshot of the cumulative per-hex totals (RunReconciler legacy
    // reconstruction budget). Room suspend queries run on Room's executor.
    suspend fun getCapturedHexes(): List<CapturedHexEntity>
}

/**
 * Captured territory, filed under the signed-in account.
 *
 * The account is resolved here rather than passed in, so the capture engine —
 * which knows only about coordinates — cannot credit a hex to the wrong user,
 * and a merge that arrives with no session is dropped instead of landing on
 * whichever row happens to hold that coordinate.
 */
class RoomHexRepository(
    private val hexDao: HexDao,
    private val identity: IdentityProvider,
) : HexRepository {

    override fun observeCapturedHexes(): Flow<List<CapturedHexEntity>> =
        identity.ownedFlow(emptyList()) { owner -> hexDao.observeAllCapturedHexes(owner) }

    override suspend fun mergeSessionHexes(sessionHexesToSteps: Map<String, Int>) {
        val owner = identity.currentSubject() ?: run {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("HexRepository", "mergeSessionHexes"))
            return
        }
        val now = System.currentTimeMillis()
        sessionHexesToSteps.forEach { (hexId, steps) ->
            hexDao.addSteps(owner = owner, hexId = hexId, steps = steps, timestamp = now)
        }
    }

    override suspend fun getCapturedHexes(): List<CapturedHexEntity> {
        val owner = identity.currentSubject() ?: run {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("HexRepository", "getCapturedHexes"))
            return emptyList()
        }
        return hexDao.getAllCapturedHexes(owner)
    }
}
