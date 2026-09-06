package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

@Dao
interface HexDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: CapturedHexEntity)

    @Query("SELECT * FROM captured_hexes WHERE hexId = :hexId LIMIT 1")
    suspend fun getByHexId(hexId: String): CapturedHexEntity?

    @Query("SELECT * FROM captured_hexes ORDER BY totalSteps DESC")
    fun observeAllCapturedHexes(): Flow<List<CapturedHexEntity>>

    // One-shot snapshot for RunReconciler's legacy reconstruction budget.
    @Query("SELECT * FROM captured_hexes")
    suspend fun getAllCapturedHexes(): List<CapturedHexEntity>

    @Transaction
    suspend fun addSteps(hexId: String, steps: Int, timestamp: Long) {
        val current = getByHexId(hexId)
        val merged = CapturedHexEntity(
            hexId = hexId,
            totalSteps = (current?.totalSteps ?: 0) + steps,
            lastUpdated = timestamp
        )
        upsert(merged)
    }
}

