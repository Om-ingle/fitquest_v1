package com.example.mobileapp.features.capture

import cafe.adriel.voyager.core.model.ScreenModel
import com.example.mobileapp.core.capture.HexCaptureEngine
import com.example.mobileapp.core.data.local.AchievementRepository
import com.example.mobileapp.core.data.local.HexRepository
import com.example.mobileapp.core.data.local.QuestRepository
import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.data.local.UserProfileRepository
import com.example.mobileapp.core.geo.HexGeoJsonMapper
import com.example.mobileapp.core.geo.HexIndexer
import com.example.mobileapp.core.network.MapTerritoryFetcher
import com.example.mobileapp.core.network.RunSyncer
import com.example.mobileapp.core.network.ViewportBounds
import com.example.mobileapp.core.network.ViewportChangeDetector
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.orbitmvi.orbit.ContainerHost
import org.orbitmvi.orbit.container
import org.orbitmvi.orbit.syntax.simple.intent
import org.orbitmvi.orbit.syntax.simple.reduce
import java.util.UUID

class CaptureScreenModel(
    private val hexCaptureEngine: HexCaptureEngine,
    private val hexRepository: HexRepository,
    private val hexIndexer: HexIndexer,
    private val userProfileRepository: UserProfileRepository,
    private val runSessionRepository: RunSessionRepository,
    private val questRepository: QuestRepository,
    private val achievementRepository: AchievementRepository,
    private val runSyncer: RunSyncer,
    private val mapTerritoryFetcher: MapTerritoryFetcher
) : ScreenModel, ContainerHost<CaptureState, Nothing> {

    private val screenModelScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private val captureThresholdSteps = 1
    private var timerJob: Job? = null
    private var sessionStartTime: Long = 0L

    // Shared-map viewport state
    private var lastFetchedBounds: ViewportBounds? = null
    private var sharedMapFetchJob: Job? = null

    companion object {
        // Mirror of the backend's MIN_DETAIL_ZOOM (apps/api map service):
        // below this zoom the server returns an aggregated placeholder.
        const val MIN_DETAIL_ZOOM = 14.0
    }

    override val container = screenModelScope.container<CaptureState, Nothing>(CaptureState())

    init {
        // --- Engine snapshot → UI state (runs on Default dispatcher already via engine) ---
        hexCaptureEngine.state
            .onEach { snapshot ->
                intent {
                    val newSessionHexes = snapshot.hexesToSteps
                        .filterValues { it >= captureThresholdSteps }
                        .keys
                        .toList()

                    // Compute GeoJSON strings on background to prevent frame drops
                    val currentGeoJson = snapshot.currentHexId?.let {
                        HexGeoJsonMapper.toGeoJsonString(hexIndexer, listOf(it))
                    } ?: ""

                    val nearbyGeoJson = if (snapshot.nearbyHexIds.isNotEmpty()) {
                        HexGeoJsonMapper.toGeoJsonString(hexIndexer, snapshot.nearbyHexIds)
                    } else ""

                    val distanceMeters = snapshot.sessionSteps * 0.75
                    val calories = (snapshot.sessionSteps * 0.04).toInt()

                    reduce {
                        val allCaptured = (newSessionHexes + state.historicalCapturedHexes).distinct()
                        val capturedGeoJson = if (allCaptured.isNotEmpty()) {
                            HexGeoJsonMapper.toGeoJsonString(hexIndexer, allCaptured)
                        } else ""

                        state.copy(
                            isTracking = snapshot.isTracking,
                            currentLocation = snapshot.currentLocation,
                            currentHexId = snapshot.currentHexId,
                            sessionSteps = snapshot.sessionSteps,
                            distanceMeters = distanceMeters,
                            caloriesBurned = calories,
                            sessionCapturedHexes = newSessionHexes,
                            allCapturedHexes = allCaptured,
                            capturedHexGeoJson = capturedGeoJson,
                            currentHexGeoJson = currentGeoJson,
                            nearbyHexGeoJson = nearbyGeoJson
                        )
                    }
                }
            }
            .launchIn(screenModelScope)

        // --- Persisted hexes from Room ---
        hexRepository.observeCapturedHexes()
            .onEach { persisted ->
                intent {
                    reduce {
                        val history = persisted.map { it.hexId }
                        val allCaptured = (state.sessionCapturedHexes + history).distinct()
                        val capturedGeoJson = if (allCaptured.isNotEmpty()) {
                            HexGeoJsonMapper.toGeoJsonString(hexIndexer, allCaptured)
                        } else ""

                        state.copy(
                            historicalCapturedHexes = history,
                            allCapturedHexes = allCaptured,
                            capturedHexGeoJson = capturedGeoJson
                        )
                    }
                }
            }
            .launchIn(screenModelScope)
    }

    fun onToggleTracking() = intent {
        if (state.isTracking) {
            timerJob?.cancel()
            val endTime = System.currentTimeMillis()
            val totalSteps = hexCaptureEngine.state.value.sessionSteps
            val finalStepsMap = hexCaptureEngine.state.value.hexesToSteps
            val capturedHexes = state.sessionCapturedHexes
            val duration = state.durationSeconds
            val distance = state.distanceMeters
            val calories = state.caloriesBurned

            hexCaptureEngine.stopTracking()

            // The backend is the authority for competitive XP (50/new hex,
            // 10/defended, 100/stolen — see the FastAPI run-sync service).
            // This local formula is only a PROVISIONAL estimate shown when
            // the backend is unreachable; a successful sync replaces it.
            val provisionalXp = (capturedHexes.size * 50) + ((totalSteps / 100) * 10) + 20

            val session = RunSessionEntity(
                id = UUID.randomUUID().toString(),
                startedAt = sessionStartTime,
                endedAt = endTime,
                durationSeconds = duration,
                totalSteps = totalSteps,
                distanceMeters = distance,
                caloriesBurned = calories,
                capturedHexCount = capturedHexes.size,
                capturedHexIdsJson = capturedHexes.joinToString(","),
                xpEarned = provisionalXp,
                isSynced = false
            )

            screenModelScope.launch(Dispatchers.IO) {
                // Save the run locally FIRST so it survives even if the
                // backend is unreachable (offline Room gameplay preserved).
                runSessionRepository.saveSession(session)

                // Then attempt the backend sync: run -> DTO -> FastAPI ->
                // Supabase -> authoritative summary -> local reconciliation.
                val hexesToSteps = finalStepsMap.filterValues { it >= captureThresholdSteps }
                var finalSession = session
                var syncSummary: com.example.mobileapp.core.network.models.RunSyncSummary? = null
                when (val outcome = runSyncer.syncRun(totalSteps, hexesToSteps)) {
                    is RunSyncer.SyncOutcome.Success -> {
                        val authoritativeXp = outcome.summary.xp_earned
                        runSessionRepository.markSynced(session.id, authoritativeXp)
                        finalSession = session.copy(xpEarned = authoritativeXp, isSynced = true)
                        syncSummary = outcome.summary
                    }
                    is RunSyncer.SyncOutcome.HttpError,
                    is RunSyncer.SyncOutcome.NetworkError -> {
                        // Keep the provisional estimate; the unsynced run
                        // stays in Room. No automatic retry is implemented.
                    }
                }
                val earnedXp = finalSession.xpEarned

                // Update user profile stats & streak (XP reconciled above)
                val updatedProfile = userProfileRepository.recordCompletedSession(
                    steps = totalSteps,
                    distanceMeters = distance,
                    calories = calories,
                    hexCount = capturedHexes.size,
                    xp = earnedXp
                )

                // Update daily quests
                questRepository.recordActivity(
                    steps = totalSteps,
                    hexCount = capturedHexes.size,
                    durationSeconds = duration
                )

                // Evaluate achievements
                val allHexCount = hexRepository.observeCapturedHexes().first().size
                val totalSessions = runSessionRepository.observeSessionCount().first()
                val unlocked = achievementRepository.evaluateAchievements(
                    totalHexes = allHexCount,
                    lifetimeSteps = updatedProfile.totalLifetimeSteps,
                    totalSessions = totalSessions,
                    currentStreak = updatedProfile.currentStreak
                )

                intent {
                    reduce {
                        state.copy(
                            isTracking = false,
                            isPaused = false,
                            showSummaryDialog = true,
                            latestCompletedSession = finalSession,
                            syncSummary = syncSummary,
                            unlockedAchievements = unlocked
                        )
                    }
                }
            }
        } else {
            sessionStartTime = System.currentTimeMillis()
            reduce {
                state.copy(
                    isTracking = true,
                    isPaused = false,
                    durationSeconds = 0L,
                    distanceMeters = 0.0,
                    caloriesBurned = 0
                )
            }
            hexCaptureEngine.startTracking()
            startTimer()
        }
    }

    fun onTogglePause() = intent {
        val newPaused = !state.isPaused
        reduce { state.copy(isPaused = newPaused) }
    }

    fun dismissSummaryDialog() = intent {
        reduce {
            state.copy(
                showSummaryDialog = false,
                latestCompletedSession = null,
                syncSummary = null,
                unlockedAchievements = emptyList()
            )
        }
    }

    /**
     * Called by the map when the camera settles (first style load + every
     * camera-idle) with the visible bounds. Fetches server territory for the
     * viewport, deduplicated by [ViewportChangeDetector]. A failure only
     * flags [CaptureState.sharedMapFetchFailed] — it never crashes the run
     * or blocks local tracking.
     */
    fun onViewportChanged(bounds: ViewportBounds) = intent {
        // Mirror the backend: below MIN_DETAIL_ZOOM the response is an
        // aggregated placeholder — clear the shared layers rather than
        // pretending it contains detail hexes.
        if (bounds.zoomLevel < MIN_DETAIL_ZOOM) {
            reduce {
                state.copy(
                    multiplayerGeoJson = "",
                    myServerHexesGeoJson = "",
                    isFetchingSharedMap = false,
                    sharedMapFetchFailed = false
                )
            }
            return@intent
        }

        if (!ViewportChangeDetector.shouldFetch(lastFetchedBounds, bounds)) return@intent
        lastFetchedBounds = bounds

        sharedMapFetchJob?.cancel()
        sharedMapFetchJob = screenModelScope.launch(Dispatchers.IO) {
            intent { reduce { state.copy(isFetchingSharedMap = true) } }

            when (val outcome = mapTerritoryFetcher.fetchViewport(bounds)) {
                is MapTerritoryFetcher.Outcome.Success -> {
                    // Split into my vs rival territory and build labeled
                    // GeoJSON on this background thread (JNI work off UI).
                    val mine = outcome.response.hexes.filter { it.is_owned_by_me }
                    val rivals = outcome.response.hexes.filterNot { it.is_owned_by_me }
                    val myGeoJson = if (mine.isEmpty()) "" else HexGeoJsonMapper.toLabeledGeoJsonString(
                        hexIndexer, mine.associate { it.hex_id to "YOU" }
                    )
                    val rivalGeoJson = if (rivals.isEmpty()) "" else HexGeoJsonMapper.toLabeledGeoJsonString(
                        hexIndexer, rivals.associate { it.hex_id to it.king_username }
                    )

                    // Wholesale replacement — no stale feature accumulation.
                    intent {
                        reduce {
                            state.copy(
                                multiplayerGeoJson = rivalGeoJson,
                                myServerHexesGeoJson = myGeoJson,
                                isFetchingSharedMap = false,
                                sharedMapFetchFailed = false
                            )
                        }
                    }
                }
                is MapTerritoryFetcher.Outcome.HttpError,
                is MapTerritoryFetcher.Outcome.NetworkError -> {
                    // Keep whatever was rendered before; surface the failure.
                    intent {
                        reduce {
                            state.copy(
                                isFetchingSharedMap = false,
                                sharedMapFetchFailed = true
                            )
                        }
                    }
                }
            }
        }
    }

    private fun startTimer() {
        timerJob?.cancel()
        timerJob = screenModelScope.launch {
            while (isActive) {
                delay(1000)
                intent {
                    if (state.isTracking && !state.isPaused) {
                        reduce { state.copy(durationSeconds = state.durationSeconds + 1) }
                    }
                }
            }
        }
    }

    override fun onDispose() {
        timerJob?.cancel()
        sharedMapFetchJob?.cancel()
        hexCaptureEngine.stopTracking()
        screenModelScope.cancel()
    }
}