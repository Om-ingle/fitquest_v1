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
    val nearbyHexIds: List<String> = emptyList(),
    /**
     * Steps taken while no hex was known yet (no GPS fix / indexer down), kept
     * in the run total and buffered here for exactly-once attribution to the
     * first hex that becomes available. UI ignores this field; it exists so the
     * buffer is mutated atomically with the rest of the state.
     */
    val pendingStepsBeforeHex: Int = 0
) {
    /**
     * Accounts a freshly detected step delta. While a hex is known the delta is
     * attributed to that hex (existing behavior); before the first hex it is
     * retained in [sessionSteps] and buffered in [pendingStepsBeforeHex] instead
     * of being silently dropped (M9.2 P1-1). Deltas outside a run (the sensor
     * flow is only collected between start/stop tracking) are ignored, matching
     * the collector lifecycle and protecting against a late delta after stop.
     */
    fun applyStepDelta(delta: Int): HexCaptureSnapshot {
        if (!isTracking) return this
        val targetHex = currentHexId
        return if (targetHex != null) {
            val updated = hexesToSteps.toMutableMap()
            updated[targetHex] = (updated[targetHex] ?: 0) + delta
            copy(sessionSteps = sessionSteps + delta, hexesToSteps = updated)
        } else {
            copy(
                sessionSteps = sessionSteps + delta,
                pendingStepsBeforeHex = pendingStepsBeforeHex + delta
            )
        }
    }

    /**
     * Applies a location fix. Existing behavior: while tracking, the current hex
     * is registered in [hexesToSteps] the first time it is seen. Additionally,
     * when buffered pre-hex steps exist and a hex has just become known, those
     * steps are attributed to that hex exactly once and the buffer is cleared —
     * they are never added to [sessionSteps] again (no double count).
     */
    fun applyLocationUpdate(
        hexId: String?,
        nearby: List<String>,
        location: GeoPoint
    ): HexCaptureSnapshot {
        val updated = copy(
            currentLocation = location,
            currentHexId = hexId,
            nearbyHexIds = nearby
        )
        if (!isTracking || hexId == null) return updated

        val hexMap = hexesToSteps.toMutableMap()
        if (!hexMap.containsKey(hexId)) {
            hexMap[hexId] = 0
        }
        val buffered = pendingStepsBeforeHex
        if (buffered > 0) {
            hexMap[hexId] = (hexMap[hexId] ?: 0) + buffered
            return updated.copy(hexesToSteps = hexMap, pendingStepsBeforeHex = 0)
        }
        return updated.copy(hexesToSteps = hexMap)
    }
}

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
            snapshot.applyLocationUpdate(hexId, nearby, GeoPoint(latitude, longitude))
        }
    }

    fun startTracking() {
        if (_state.value.isTracking) return

        _state.update {
            val initialHexMap = it.currentHexId?.let { hexId -> mapOf(hexId to 0) } ?: emptyMap()
            it.copy(
                isTracking = true,
                sessionSteps = 0,
                hexesToSteps = initialHexMap,
                pendingStepsBeforeHex = 0
            )
        }

        // Re-arm the location subscription at run start. Best-effort: when the
        // engine was constructed before location permission was granted (e.g.
        // onboarding "Skip for Now"), the initial silent subscription emits
        // nothing — starting a run re-attempts it so a freshly granted run gets
        // a live GPS fix instead of a permanently dead monitor.
        startLocationMonitoring()
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
                hexesToSteps = seeded,
                // Pre-hex steps from before a process death are not part of any
                // hex; they live in sessionSteps (persisted above). The buffer
                // is not checkpointed, so it restarts empty for the new session.
                pendingStepsBeforeHex = 0
            )
        }

        // Same re-arm rationale as [startTracking].
        startLocationMonitoring()
        startStepsCollection()
    }

    private fun startStepsCollection() {
        stepsJob?.cancel()
        stepsJob = scope.launch {
            stepSensorManager.observeStepDeltas().collect { delta ->
                _state.update { snapshot ->
                    snapshot.applyStepDelta(delta)
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
                hexesToSteps = emptyMap(),
                pendingStepsBeforeHex = 0
            )
        }
    }
}
