package com.example.mobileapp.features.capture

import cafe.adriel.voyager.core.model.ScreenModel
import com.example.mobileapp.core.capture.HexCaptureEngine
import com.example.mobileapp.core.data.local.AchievementRepository
import com.example.mobileapp.core.data.local.ActiveRunRepository
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
import com.example.mobileapp.core.network.models.RunSyncPayload
import com.example.mobileapp.core.network.models.RunSyncPayloadCodec
import com.example.mobileapp.core.run.ActiveRunController
import com.example.mobileapp.core.run.ActiveRunStatusResolver
import com.example.mobileapp.core.run.HexStepsCodec
import com.example.mobileapp.core.run.RunMetrics
import com.example.mobileapp.core.run.RunTiming
import com.example.mobileapp.core.telemetry.DailyActivitySnapshotBuilder
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
    private val mapTerritoryFetcher: MapTerritoryFetcher,
    private val activeRunController: ActiveRunController,
    private val activeRunRepository: ActiveRunRepository
) : ScreenModel, ContainerHost<CaptureState, Nothing> {

    private val screenModelScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private val captureThresholdSteps = 1
    private var timerJob: Job? = null
    // Guards against duplicate finish/sync when Stop & Finish is tapped twice
    // while the first finalization (Room save + network sync) is still running.
    private var finalizeInFlight = false

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

                    val distanceMeters = RunMetrics.distanceMeters(snapshot.sessionSteps)
                    val calories = RunMetrics.calories(snapshot.sessionSteps)

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

        // --- Process-death recovery detection on screen entry ---
        // Decide once per screen creation: a LIVE engine (process-local
        // re-entry) wins; otherwise a Room checkpoint becomes a user-facing
        // "Previous run found" prompt rather than being silently discarded.
        screenModelScope.launch {
            val checkpoint = activeRunRepository.getActiveRun()
            when (ActiveRunStatusResolver.resolve(
                isEngineTracking = hexCaptureEngine.state.value.isTracking,
                checkpointExists = checkpoint != null
            )) {
                com.example.mobileapp.core.run.ActiveRunStatus.LIVE -> {
                    // Engine is mid-run in this process: adopt it. Nothing to
                    // prompt — the service/controller already own the run.
                    val timing = activeRunController.currentTiming()
                    val runId = activeRunController.currentRunId()
                    if (runId != null && timing != null) {
                        activeRunController.startRun(runId, timing) // idempotent; re-ensures service
                        startTimer()
                    }
                }
                com.example.mobileapp.core.run.ActiveRunStatus.RECOVERABLE -> {
                    intent {
                        reduce { state.copy(pendingRecovery = checkpoint) }
                    }
                }
                com.example.mobileapp.core.run.ActiveRunStatus.NONE -> Unit
            }
        }
    }

    fun onToggleTracking() {
        // Reads the authoritative state and delegates to an intent-based helper
        // (avoids nesting an intent inside an intent).
        if (container.stateFlow.value.isTracking) {
            finishActiveRun()
        } else {
            startNewRun()
        }
    }

    fun onTogglePause() = intent {
        if (!state.isTracking) return@intent
        if (state.isPaused) {
            activeRunController.resume()
            reduce { state.copy(isPaused = false) }
        } else {
            activeRunController.pause()
            reduce { state.copy(isPaused = true) }
        }
    }

    // ── Recovery actions ────────────────────────────────────────────────────

    /**
     * Resume a run recovered from a Room checkpoint after process death. Seeds
     * the engine with the checkpoint's steps + partial hex map (so that
     * territory is not lost), re-attaches the run identity/timing, and brings
     * the foreground service back up. The paused flag is preserved so a run
     * that died while paused stays paused (elapsed frozen) until resumed.
     */
    fun onResumeRecovery() = intent {
        val checkpoint = state.pendingRecovery ?: return@intent
        val timing = RunTiming.fromCheckpoint(checkpoint)
        // Seed engine first so the controller's immediate checkpoint and the
        // service's first tick already see the restored counters.
        hexCaptureEngine.resumeTracking(
            initialSessionSteps = checkpoint.sessionSteps,
            initialHexesToSteps = HexStepsCodec.decode(checkpoint.hexesToStepsJson)
        )
        activeRunController.startRun(checkpoint.runId, timing)

        reduce {
            state.copy(
                isTracking = true,
                isPaused = checkpoint.isPaused,
                durationSeconds = timing.elapsedSeconds(),
                distanceMeters = checkpoint.distanceMeters,
                caloriesBurned = RunMetrics.calories(checkpoint.sessionSteps),
                sessionSteps = checkpoint.sessionSteps,
                pendingRecovery = null
            )
        }
        startTimer()
    }

    /**
     * Explicitly discard a recovered run. No RunSessionEntity is created — the
     * user chose to abandon it — and the checkpoint row is cleared so the app
     * returns to a fresh standby state.
     */
    fun onDiscardRecovery() = intent {
        if (state.pendingRecovery == null) return@intent
        activeRunController.finishRun()
        reduce {
            state.copy(
                pendingRecovery = null,
                isTracking = false,
                isPaused = false,
                durationSeconds = 0L,
                distanceMeters = 0.0,
                caloriesBurned = 0,
                sessionSteps = 0
            )
        }
    }

    // ── Run lifecycle ───────────────────────────────────────────────────────

    private fun startNewRun() = intent {
        if (container.stateFlow.value.isTracking || finalizeInFlight) return@intent
        finalizeInFlight = false
        val runId = UUID.randomUUID().toString()
        val timing = RunTiming.starting()
        activeRunController.startRun(runId, timing)
        reduce {
            state.copy(
                isTracking = true,
                isPaused = false,
                durationSeconds = 0L,
                distanceMeters = 0.0,
                caloriesBurned = 0,
                pendingRecovery = null
            )
        }
        hexCaptureEngine.startTracking()
        startTimer()
    }

    private fun finishActiveRun() = intent {
        if (finalizeInFlight) return@intent
        finalizeInFlight = true
        timerJob?.cancel()
        val endTime = System.currentTimeMillis()
        val timing = activeRunController.currentTiming() ?: RunTiming.starting(endTime)
        val startedAt = timing.startedAtMillis
        val durationSeconds = timing.elapsedSeconds(endTime)

        val totalSteps = hexCaptureEngine.state.value.sessionSteps
        val finalStepsMap = hexCaptureEngine.state.value.hexesToSteps
        val capturedHexes = state.sessionCapturedHexes
        val distance = RunMetrics.distanceMeters(totalSteps)
        val calories = RunMetrics.calories(totalSteps)

        hexCaptureEngine.stopTracking()

        // End-of-day territory count for the telemetry snapshot: this
        // run's captures plus the persisted Room mirror.
        val hexesOwnedEndOfDay =
            (capturedHexes + state.historicalCapturedHexes).distinct().size

        // The backend is the authority for competitive XP (50/new hex,
        // 10/defended, 100/stolen — see the FastAPI run-sync service).
        // This local formula is only a PROVISIONAL estimate shown when
        // the backend is unreachable; a successful sync replaces it.
        val provisionalXp = (capturedHexes.size * 50) + ((totalSteps / 100) * 10) + 20

        val session = RunSessionEntity(
            id = UUID.randomUUID().toString(),
            startedAt = startedAt,
            endedAt = endTime,
            durationSeconds = durationSeconds,
            totalSteps = totalSteps,
            distanceMeters = distance,
            caloriesBurned = calories,
            capturedHexCount = capturedHexes.size,
            capturedHexIdsJson = capturedHexes.joinToString(","),
            xpEarned = provisionalXp,
            isSynced = false
        )

        screenModelScope.launch(Dispatchers.IO) {
            // Save the run locally FIRST so it survives even if the backend is
            // unreachable (offline Room gameplay preserved) and so clearing the
            // active-run checkpoint below can never lose the finished session.
            runSessionRepository.saveSession(session)

            // Run is durably recorded — the checkpoint is no longer needed for
            // recovery. Stop the service (removes notification, clears row).
            activeRunController.finishRun()

            // Phase 4B.5 telemetry: aggregate the run's device-local day
            // from Room (the just-saved session included) into an
            // absolute snapshot that rides the same sync request.
            val dayWindow = DailyActivitySnapshotBuilder.localDayWindow(session.startedAt)
            val dailyActivity = DailyActivitySnapshotBuilder.build(
                sessions = runSessionRepository.getSessionsBetween(dayWindow.first, dayWindow.second),
                goalSteps = userProfileRepository.getProfile().dailyStepGoal,
                hexesOwned = hexesOwnedEndOfDay,
                forTimestampMillis = session.startedAt
            )

            // Build the exact outbound payload (incl. run_id = this session's
            // id) and persist it BEFORE the sync attempt so a failed sync can
            // later be replayed byte-identically by RunReconciler on the next
            // foreground (Fix A) — the payload survives even a process death
            // between here and markSynced.
            val hexesToSteps = finalStepsMap.filterValues { it >= captureThresholdSteps }
            val payload = RunSyncPayload(
                total_session_steps = totalSteps,
                hexes_to_steps = hexesToSteps,
                daily_activity = dailyActivity,
                run_id = session.id
            )
            runSessionRepository.setPendingSyncPayload(session.id, RunSyncPayloadCodec.toJson(payload))

            var finalSession = session
            var syncSummary: com.example.mobileapp.core.network.models.RunSyncSummary? = null
            when (val outcome = runSyncer.syncRun(payload)) {
                is RunSyncer.SyncOutcome.Success -> {
                    // already_processed can only happen if this run_id was
                    // already committed server-side by a lost earlier attempt —
                    // keep the local xp rather than overwriting it with zeroes.
                    val authoritativeXp =
                        if (outcome.summary.already_processed) session.xpEarned
                        else outcome.summary.xp_earned
                    runSessionRepository.markSynced(session.id, authoritativeXp)
                    finalSession = session.copy(xpEarned = authoritativeXp, isSynced = true)
                    syncSummary = outcome.summary
                }
                is RunSyncer.SyncOutcome.HttpError,
                is RunSyncer.SyncOutcome.NetworkError -> {
                    // Keep the provisional estimate; the run stays unsynced in
                    // Room with its stored payload, and RunReconciler replays it
                    // on the next foreground.
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
                durationSeconds = durationSeconds
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

            // Finalization done (for better or worse: synced or left offline).
            // Clear the in-flight guard so a fresh run can start afterwards.
            finalizeInFlight = false
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
                // Re-derive elapsed from the wall clock each second; never
                // accumulate it. Falls back to the existing displayed value if
                // the controller is momentarily not active.
                val elapsed = activeRunController.currentTiming()?.elapsedSeconds()
                intent {
                    if (state.isTracking) {
                        reduce {
                            state.copy(durationSeconds = elapsed ?: state.durationSeconds)
                        }
                    }
                }
                delay(1000)
            }
        }
    }

    override fun onDispose() {
        timerJob?.cancel()
        sharedMapFetchJob?.cancel()
        screenModelScope.cancel()
        // NOTE: hexCaptureEngine.stopTracking() is intentionally NOT called
        // here. Disposing the screen must not end a run — the engine, the
        // ActiveRunController and the foreground service keep the run alive in
        // the background. A later re-entry detects the LIVE engine and adopts
        // it. Ending the run only ever happens via an explicit Stop & Finish.
    }
}
