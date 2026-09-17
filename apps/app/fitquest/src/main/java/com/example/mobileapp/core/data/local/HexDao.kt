package com.example.mobileapp.core.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

/**
 * All access to `captured_hexes`, scoped to one account.
 *
 * The scope is part of the key here, not just a filter: `hexId` is a map
 * coordinate, so it is shared between accounts by construction. Every lookup
 * therefore has to name BOTH the owner and the hex, and [addSteps] reads and
 * writes the same (owner, hex) row inside one transaction.
 */
@Dao
interface HexDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: CapturedHexEntity)

    @Query("SELECT * FROM captured_hexes WHERE ownerSubject = :owner AND hexId = :hexId LIMIT 1")
    suspend fun getByHexId(owner: String, hexId: String): CapturedHexEntity?

    @Query("SELECT * FROM captured_hexes WHERE ownerSubject = :owner ORDER BY totalSteps DESC")
    fun observeAllCapturedHexes(owner: String): Flow<List<CapturedHexEntity>>

    // One-shot snapshot for RunReconciler's legacy reconstruction budget.
    @Query("SELECT * FROM captured_hexes WHERE ownerSubject = :owner")
    suspend fun getAllCapturedHexes(owner: String): List<CapturedHexEntity>

    @Transaction
    suspend fun addSteps(owner: String, hexId: String, steps: Int, timestamp: Long) {
        val current = getByHexId(owner, hexId)
        val merged = CapturedHexEntity(
            ownerSubject = owner,
            hexId = hexId,
            totalSteps = (current?.totalSteps ?: 0) + steps,
            lastUpdated = timestamp
        )
        upsert(merged)
    }
}
