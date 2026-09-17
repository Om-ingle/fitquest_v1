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
    /**
     * Whether the live run is currently paused (F-02). While paused the engine
     * still resolves the current hex so the map keeps showing where the user
     * is, but it accrues nothing: no steps, no hex registration, no buffer
     * drain. Holding the flag in the snapshot is what keeps the engine and the
     * UI from ever disagreeing about it — `CaptureScreenModel` mirrors this
     * field rather than tracking its own copy.
     */
    val isPaused: Boolean = false,
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
     *
     * A paused run discards the delta outright (F-02): the sensor reports the
     * delta per event, so nothing has to be reconciled later and resuming can
     * never produce a catch-up jump. Critically, the delta is NOT banked into
     * [sessionSteps] or [pendingStepsBeforeHex] for later removal — banking
     * would break the exactly-once accounting invariant.
     */
    fun applyStepDelta(delta: Int): HexCaptureSnapshot {
        if (!isTracking || isPaused) return this
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
     *
     * While paused the fix still updates the displayed position, current hex
     * and nearby ring — the user must be able to see where they are — but it
     * neither registers territory nor drains the buffer (F-02). Draining while
     * paused would attribute buffered steps to a hex the user is standing still
     * in, and registering would capture hexes the paused run never earned.
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
        if (!isTracking || isPaused || hexId == null) return updated

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

/**
 * The slice of the capture engine that the active-run lifecycle depends on.
 *
 * [ActiveRunController] needs exactly two things from the engine: the live
 * tallies it checkpoints, and the ability to release a session it can no longer
 * attribute. Declaring only those two makes the controller's account-switch
 * decision testable in a JVM test — the real [HexCaptureEngine] cannot be
 * constructed there, since it takes a `Context`-bound sensor stack and a native
 * h3 indexer. Same declared-type discipline as the rest of the DI graph.
 */
interface RunSessionEngine {
    /** The live capture state; [ActiveRunController] reads its tallies. */
    val state: StateFlow<HexCaptureSnapshot>

    /**
     * Releases the live session without persisting its hex tallies. See
     * [HexCaptureEngine.discardSession].
     */
    fun discardSession()
}

class HexCaptureEngine(
    private val stepSensorManager: StepSensorManager,
    private val locationTrackingManager: LocationTrackingManager,
    private val hexRepository: HexRepository,
    private val hexIndexer: HexIndexer,
) : RunSessionEngine {
    private val h3Resolution = 10
    private val nearbyRingSize = 2

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val _state = MutableStateFlow(HexCaptureSnapshot())
    override val state: StateFlow<HexCaptureSnapshot> = _state.asStateFlow()

    private var locationJob: Job? = null
    private var stepsJob: Job? = null

    // Deliberately NO `init { startLocationMonitoring() }`: the engine must not
    // arm a high-accuracy GPS subscription merely by being constructed (F-10).
    // This is a Koin `single` injected by MainActivity for cold-start routing,
    // so a construction-time arm turned on continuous location collection on
    // every launch and — because nothing released it on the Home path — kept it
    // running for the whole process lifetime with no run active. Arming is now
    // strictly demand-driven: the capture screen arms it while visible, and
    // startTracking() re-arms it for a run (which outlives the screen).

    /**
     * Arms the location subscription. Idempotent — an existing subscription is
     * cancelled first.
     *
     * Public because ownership is shared: the engine needs a live fix while a
     * run is active, and the capture screen needs one while it is on-screen so
     * the standby map can show the current hex. Whoever no longer needs it
     * calls [stopLocationMonitoring] (F-10).
     */
    fun startLocationMonitoring() {
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

    /**
     * Releases the location subscription.
     *
     * `observeLocations()` is a `callbackFlow` whose `awaitClose` removes the
     * location updates, so cancelling this job is the only thing that actually
     * stops high-accuracy GPS. Without it the subscription ran for the whole
     * process lifetime — continuous location collection and battery drain with
     * no run active (F-10).
     */
    fun stopLocationMonitoring() {
        locationJob?.cancel()
        locationJob = null
    }

    /**
     * Records the run's paused state. Called by [CaptureScreenModel] alongside
     * the controller's timing pause, so the pause that freezes the clock also
     * freezes step, distance, calorie and territory accrual (F-02). Idempotent
     * — [MutableStateFlow] conflates an unchanged value, so this never emits a
     * spurious snapshot.
     */
    fun setPaused(paused: Boolean) {
        _state.update { it.copy(isPaused = paused) }
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
                isPaused = false,
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
     *
     * [isPaused] restores the checkpoint's pause state: a run that died while
     * paused must come back paused, accruing nothing until the user resumes
     * (M10 exit criterion 3).
     */
    fun resumeTracking(
        initialSessionSteps: Int,
        initialHexesToSteps: Map<String, Int>,
        isPaused: Boolean = false
    ) {
        if (_state.value.isTracking) return

        _state.update { snapshot ->
            val seeded = initialHexesToSteps.toMutableMap()
            snapshot.currentHexId?.let { hexId ->
                if (!seeded.containsKey(hexId)) seeded[hexId] = 0
            }
            snapshot.copy(
                isTracking = true,
                isPaused = isPaused,
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

    /**
     * Ends the run: stops step collection and releases the location
     * subscription (F-10 — the subscription belongs to the run and must not
     * outlive it), then merges the session's hex tallies into Room and clears
     * the live counters.
     */
    fun stopTracking() {
        endSession(persistHexTallies = true)
    }

    /**
     * Ends the run WITHOUT persisting its hex tallies.
     *
     * For the case where the account changes mid-run. The tallies in
     * [HexCaptureSnapshot.hexesToSteps] were earned by the account that started
     * the run, and by the time this is called that account's session is gone, so
     * [HexRepository] has no subject to attribute them to — merging them would
     * either be dropped or land on whoever signs in next. The run's persisted
     * checkpoint is deliberately NOT touched: it stays owned by the account that
     * started it, so that account recovers the run on its next sign-in. Only the
     * live, in-process state (sensors, counters) is released here.
     */
    override fun discardSession() {
        endSession(persistHexTallies = false)
    }

    private fun endSession(persistHexTallies: Boolean) {
        if (!_state.value.isTracking) return

        stepsJob?.cancel()
        stepsJob = null
        stopLocationMonitoring()

        if (persistHexTallies) {
            val finishedSession = _state.value.hexesToSteps
            scope.launch {
                if (finishedSession.isNotEmpty()) {
                    hexRepository.mergeSessionHexes(finishedSession)
                }
            }
        }

        _state.update {
            it.copy(
                isTracking = false,
                isPaused = false,
                sessionSteps = 0,
                hexesToSteps = emptyMap(),
                pendingStepsBeforeHex = 0
            )
        }
    }
}
