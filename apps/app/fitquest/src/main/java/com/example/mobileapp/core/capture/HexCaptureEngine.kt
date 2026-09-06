package com.example.mobileapp.core.capture

import com.example.mobileapp.core.data.local.HexRepository
import com.example.mobileapp.core.geo.HexIndexer
import com.example.mobileapp.core.model.GeoPoint
import com.example.mobileapp.core.sensors.LocationTrackingManager
import com.example.mobileapp.core.sensors.StepSensorManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class HexCaptureSnapshot(
    val isTracking: Boolean = false,
    val currentHexId: String? = null,
    val currentLocation: GeoPoint? = null,
    val sessionSteps: Int = 0,
    val hexesToSteps: Map<String, Int> = emptyMap(),
    val nearbyHexIds: List<String> = emptyList()
)

class HexCaptureEngine(
    private val stepSensorManager: StepSensorManager,
    private val locationTrackingManager: LocationTrackingManager,
    private val hexRepository: HexRepository,
    private val hexIndexer: HexIndexer,
) {
    private val h3Resolution = 10
    private val nearbyRingSize = 2

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val _state = MutableStateFlow(HexCaptureSnapshot())
    val state: StateFlow<HexCaptureSnapshot> = _state.asStateFlow()

    private var locationJob: Job? = null
    private var stepsJob: Job? = null

    init {
        startLocationMonitoring()
    }

    private fun startLocationMonitoring() {
        locationJob?.cancel()
        locationJob = scope.launch {
            // First attempt to get the user's real last known location immediately
            locationTrackingManager.getLastLocation { loc ->
                if (loc != null && _state.value.currentLocation == null) {
                    handleLocation(loc.latitude, loc.longitude)
                }
            }

            // Continuously observe real GPS location updates
            locationTrackingManager.observeLocations().collect { location ->
                handleLocation(location.latitude, location.longitude)
            }
        }
    }

    private fun handleLocation(latitude: Double, longitude: Double) {
        val hexId = if (hexIndexer.isAvailable()) {
            hexIndexer.latLngToHexId(latitude, longitude, h3Resolution)
        } else null

        val nearby = if (hexIndexer.isAvailable()) {
            hexIndexer.getHexesInRadius(latitude, longitude, h3Resolution, nearbyRingSize)
        } else emptyList()

        _state.update { snapshot ->
            val updated = snapshot.copy(
                currentLocation = GeoPoint(latitude, longitude),
                currentHexId = hexId,
                nearbyHexIds = nearby
            )

            if (snapshot.isTracking && hexId != null) {
                val hexMap = snapshot.hexesToSteps.toMutableMap()
                if (!hexMap.containsKey(hexId)) {
                    hexMap[hexId] = 0
                }
                updated.copy(hexesToSteps = hexMap)
            } else {
                updated
            }
        }
    }

    fun startTracking() {
        if (_state.value.isTracking) return

        _state.update {
            val initialHexMap = it.currentHexId?.let { hexId -> mapOf(hexId to 0) } ?: emptyMap()
            it.copy(
                isTracking = true,
                sessionSteps = 0,
                hexesToSteps = initialHexMap
            )
        }

        startStepsCollection()
    }

    /**
     * Restarts step collection for a run recovered from a Room checkpoint,
     * seeding the session counters with the checkpoint's values so partial
     * steps/territory captured before a process death are not lost. This is
     * intentionally separate from [startTracking], which begins a fresh run at
     * zero. A no-op if the engine is already tracking (live session wins).
     */
    fun resumeTracking(
        initialSessionSteps: Int,
        initialHexesToSteps: Map<String, Int>
    ) {
        if (_state.value.isTracking) return

        _state.update { snapshot ->
            val seeded = initialHexesToSteps.toMutableMap()
            snapshot.currentHexId?.let { hexId ->
                if (!seeded.containsKey(hexId)) seeded[hexId] = 0
            }
            snapshot.copy(
                isTracking = true,
                sessionSteps = initialSessionSteps.coerceAtLeast(0),
                hexesToSteps = seeded
            )
        }

        startStepsCollection()
    }

    private fun startStepsCollection() {
        stepsJob?.cancel()
        stepsJob = scope.launch {
            stepSensorManager.observeStepDeltas().collect { delta ->
                _state.update { snapshot ->
                    val targetHex = snapshot.currentHexId ?: return@update snapshot
                    val updated = snapshot.hexesToSteps.toMutableMap()
                    updated[targetHex] = (updated[targetHex] ?: 0) + delta
                    snapshot.copy(
                        sessionSteps = snapshot.sessionSteps + delta,
                        hexesToSteps = updated
                    )
                }
            }
        }
    }

    fun stopTracking() {
        if (!_state.value.isTracking) return

        stepsJob?.cancel()
        stepsJob = null

        val finishedSession = _state.value.hexesToSteps
        scope.launch {
            if (finishedSession.isNotEmpty()) {
                hexRepository.mergeSessionHexes(finishedSession)
            }
        }

        _state.update {
            it.copy(
                isTracking = false,
                sessionSteps = 0,
                hexesToSteps = emptyMap()
            )
        }
    }
}
