package com.example.mobileapp.core.data.local

import kotlinx.coroutines.flow.Flow

interface HexRepository {
    fun observeCapturedHexes(): Flow<List<CapturedHexEntity>>
    suspend fun mergeSessionHexes(sessionHexesToSteps: Map<String, Int>)
    // One-shot snapshot of the cumulative per-hex totals (RunReconciler legacy
    // reconstruction budget). Room suspend queries run on Room's executor.
    suspend fun getCapturedHexes(): List<CapturedHexEntity>
}

class RoomHexRepository(
    private val hexDao: HexDao
) : HexRepository {
    override fun observeCapturedHexes(): Flow<List<CapturedHexEntity>> = hexDao.observeAllCapturedHexes()

    override suspend fun mergeSessionHexes(sessionHexesToSteps: Map<String, Int>) {
        val now = System.currentTimeMillis()
        sessionHexesToSteps.forEach { (hexId, steps) ->
            hexDao.addSteps(hexId = hexId, steps = steps, timestamp = now)
        }
    }

    override suspend fun getCapturedHexes(): List<CapturedHexEntity> = hexDao.getAllCapturedHexes()
}

