package com.example.mobileapp.core.sensors

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
import android.os.Looper
import android.util.Log
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

class LocationTrackingManager(
    context: Context,
    private val fusedLocationProviderClient: FusedLocationProviderClient =
        LocationServices.getFusedLocationProviderClient(context)
) {
    @SuppressLint("MissingPermission")
    fun observeLocations(
        updateIntervalMs: Long = 2_000L,
        minUpdateIntervalMs: Long = 1_000L
    ): Flow<Location> = callbackFlow {
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, updateIntervalMs)
            .setMinUpdateIntervalMillis(minUpdateIntervalMs)
            .build()

        val callback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                result.lastLocation?.let { trySend(it) }
            }
        }

        try {
            // Missing ACCESS_FINE/COARSE_LOCATION makes this throw a
            // SecurityException synchronously. The capture engine can be
            // constructed before permissions are granted (onboarding "Skip for
            // Now", permissions revoked while the process is alive), so the
            // failure must never crash the app: subscribe best-effort and emit
            // no fixes until a later subscription attempt succeeds (the engine
            // re-arms on each run start).
            fusedLocationProviderClient.requestLocationUpdates(request, callback, Looper.getMainLooper())
        } catch (e: SecurityException) {
            Log.w(TAG, "Location permission not granted; location monitoring disabled (best-effort)", e)
        } catch (e: RuntimeException) {
            Log.e(TAG, "Location subscription unavailable; location monitoring disabled (best-effort)", e)
        }
        awaitClose {
            try {
                fusedLocationProviderClient.removeLocationUpdates(callback)
            } catch (e: RuntimeException) {
                // Permission may have been revoked mid-flow; teardown is
                // best-effort and must not crash the cancelling coroutine.
                Log.w(TAG, "Location update teardown failed (best-effort)", e)
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun getLastLocation(onResult: (Location?) -> Unit) {
        try {
            fusedLocationProviderClient.lastLocation
                .addOnSuccessListener { loc -> onResult(loc) }
                .addOnFailureListener { onResult(null) }
        } catch (e: Exception) {
            onResult(null)
        }
    }

    private companion object {
        const val TAG = "LocationTracking"
    }
}
