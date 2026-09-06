package com.example.mobileapp.core.network.models

import com.google.gson.Gson

/**
 * JSON (de)serializer for [RunSyncPayload] so the exact outbound payload can be
 * stored in Room before the first sync and later replayed byte-identically by
 * [com.example.mobileapp.core.network.RunReconciler] (Fix A).
 *
 * The data-class field names are already snake_case to match the wire format,
 * so Gson's default reflection round-trips with no naming policy. [fromJson]
 * returns null on any malformed input rather than throwing, so a corrupt row
 * can never crash reconciliation.
 */
object RunSyncPayloadCodec {

    private val gson = Gson()

    fun toJson(payload: RunSyncPayload): String = gson.toJson(payload)

    fun fromJson(json: String): RunSyncPayload? = try {
        gson.fromJson(json, RunSyncPayload::class.java)
    } catch (_: Exception) {
        null
    }
}
