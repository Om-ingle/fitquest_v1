package com.example.mobileapp.core.data.local

import androidx.room.Entity

/**
 * Cumulative steps credited to one hexagon, for one account.
 *
 * The primary key is composite `(ownerSubject, hexId)`. It has to be: a hex id
 * is a coordinate (`HexIndexer`), so two accounts walking the same street map
 * to the SAME `hexId`. With `hexId` alone as the key the second account's
 * capture would land on the first account's row — `OnConflictStrategy.REPLACE`
 * would overwrite their step total and the territory would change hands through
 * the local database rather than through the game rules.
 */
@Entity(tableName = "captured_hexes", primaryKeys = ["ownerSubject", "hexId"])
data class CapturedHexEntity(
    val ownerSubject: String = LEGACY_UNOWNED_SUBJECT,
    val hexId: String,
    val totalSteps: Int,
    val lastUpdated: Long
)
