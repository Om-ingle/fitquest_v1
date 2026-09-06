package com.example.mobileapp.core.network

import com.example.mobileapp.core.data.local.CapturedHexEntity
import com.example.mobileapp.core.data.local.HexRepository
import com.example.mobileapp.core.data.local.RunSessionEntity
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.network.models.LeaderboardResponse
import com.example.mobileapp.core.network.models.MapViewportResponse
import com.example.mobileapp.core.network.models.RunSyncPayload
import com.example.mobileapp.core.network.models.RunSyncPayloadCodec
import com.example.mobileapp.core.network.models.RunSyncSummary
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

/**
 * JVM unit tests for foreground reconciliation of unsynced runs (Fix A):
 * exact replay of persisted payloads, deterministic best-effort reconstruction
 * of legacy payload-less rows, single "mark synced on confirmed success" rule,
 * and the server-side already_processed signal preserving local XP.
 */
class RunReconcilerTest {

    // ── Fakes ────────────────────────────────────────────────────────────────

    private class FakeApi(
        private val behavior: suspend (RunSyncPayload) -> RunSyncSummary
    ) : FitQuestApi {
        val received = mutableListOf<RunSyncPayload>()
        override suspend fun syncRunSession(payload: RunSyncPayload): RunSyncSummary {
            received += payload
            return behavior(payload)
        }

        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double, zoomLevel: Double
        ): MapViewportResponse = MapViewportResponse(is_aggregated = true)

        override suspend fun getLeaderboard(limit: Int): LeaderboardResponse =
            LeaderboardResponse(metric = "hexes", total_players = 0)

        override suspend fun getRecommendations():
            com.example.mobileapp.core.network.models.RecommendationResponse =
            throw UnsupportedOperationException()

        override suspend fun getCoach(): com.example.mobileapp.core.network.models.CoachResponse =
            throw UnsupportedOperationException()
    }

    private class FakeRunSessionRepository(
        private var unsynced: List<RunSessionEntity> = emptyList(),
        private var synced: List<RunSessionEntity> = emptyList()
    ) : RunSessionRepository {
        val marked = mutableListOf<Pair<String, Int>>()
        override suspend fun getUnsynced(): List<RunSessionEntity> = unsynced
        override suspend fun getSyncedSessions(): List<RunSessionEntity> = synced
        override suspend fun markSynced(sessionId: String, xpEarned: Int) {
            marked += sessionId to xpEarned
        }

        override suspend fun saveSession(session: RunSessionEntity) = Unit
        override suspend fun setPendingSyncPayload(sessionId: String, json: String) = Unit
        override suspend fun getSessionsBetween(start: Long, end: Long): List<RunSessionEntity> = emptyList()
        override fun observeRecentSessions(limit: Int): Flow<List<RunSessionEntity>> = emptyFlow()
        override fun observeAllSessions(): Flow<List<RunSessionEntity>> = emptyFlow()
        override fun observeSessionCount(): Flow<Int> = emptyFlow()
        override fun observeLifetimeSteps(): Flow<Int?> = emptyFlow()
        override fun observeLifetimeDistance(): Flow<Double?> = emptyFlow()
    }

    private class FakeHexRepository(
        private val captured: List<CapturedHexEntity> = emptyList()
    ) : HexRepository {
        override fun observeCapturedHexes(): Flow<List<CapturedHexEntity>> = emptyFlow()
        override suspend fun mergeSessionHexes(sessionHexesToSteps: Map<String, Int>) = Unit
        override suspend fun getCapturedHexes(): List<CapturedHexEntity> = captured
    }

    // ── Fixture helpers ──────────────────────────────────────────────────────

    private fun session(
        id: String,
        startedAt: Long = 0L,
        totalSteps: Int = 0,
        hexIds: List<String> = emptyList(),
        xp: Int = 0,
        payloadJson: String? = null
    ) = RunSessionEntity(
        id = id,
        startedAt = startedAt,
        endedAt = startedAt + 60_000,
        durationSeconds = 60,
        totalSteps = totalSteps,
        distanceMeters = 0.0,
        caloriesBurned = 0,
        capturedHexCount = hexIds.size,
        capturedHexIdsJson = hexIds.joinToString(","),
        xpEarned = xp,
        pendingSyncPayloadJson = payloadJson
    )

    private fun captured(hexId: String, steps: Int) =
        CapturedHexEntity(hexId = hexId, totalSteps = steps, lastUpdated = 0L)

    private val ok = RunSyncSummary(
        hexes_defended = 0, hexes_stolen = 0, hexes_newly_captured = 1,
        xp_earned = 50, new_total_lifetime_steps = 100
    )

    // ── Tests ────────────────────────────────────────────────────────────────

    @Test
    fun `exact stored payload is replayed and the row marked synced`() = runBlocking {
        val stored = RunSyncPayload(
            total_session_steps = 631,
            hexes_to_steps = mapOf("h111" to 300),
            daily_activity = null,
            run_id = "run-a"
        )
        val api = FakeApi { ok }
        val repo = FakeRunSessionRepository(unsynced = listOf(
            session("run-a", totalSteps = 631, hexIds = listOf("h111"),
                payloadJson = RunSyncPayloadCodec.toJson(stored))
        ))
        val reconciler = RunReconciler(RunSyncer(api), repo, FakeHexRepository())

        reconciler.reconcileUnsyncedRuns()

        // Row replayed byte-identically (run_id intact) and marked synced once.
        assertEquals(stored, api.received.single())
        assertEquals(listOf("run-a" to 50), repo.marked)
    }

    @Test
    fun `legacy row is reconstructed deterministically and marked synced`() = runBlocking {
        val api = FakeApi { ok }
        val repo = FakeRunSessionRepository(unsynced = listOf(
            session("run-a", totalSteps = 631, hexIds = listOf("h111", "h222"), xp = 120)
        ))
        val reconciler = RunReconciler(
            RunSyncer(api),
            repo,
            FakeHexRepository(listOf(captured("h111", 434), captured("h222", 284)))
        )

        reconciler.reconcileUnsyncedRuns()

        val payload = api.received.single()
        assertEquals(631, payload.total_session_steps)
        // Minted at the recorded cumulative totals -> exact defense.
        assertEquals(mapOf("h111" to 434, "h222" to 284), payload.hexes_to_steps)
        assertEquals("run-a", payload.run_id)
        assertEquals(listOf("run-a" to 50), repo.marked)
    }

    @Test
    fun `shared legacy hex mints once then reinforces without over-crediting`() = runBlocking {
        // run-a (older) and run-b both visited h111; only run-a mints the full
        // recorded total, run-b sends a zero-step defend so defense stays exact.
        val api = FakeApi { ok }
        val repo = FakeRunSessionRepository(unsynced = listOf(
            session("run-a", startedAt = 100L, totalSteps = 631, hexIds = listOf("h111", "h222")),
            session("run-b", startedAt = 200L, totalSteps = 1791, hexIds = listOf("h111", "h222", "hEx"))
        ))
        val reconciler = RunReconciler(
            RunSyncer(api),
            repo,
            FakeHexRepository(
                listOf(captured("h111", 434), captured("h222", 284), captured("hEx", 155))
            )
        )

        reconciler.reconcileUnsyncedRuns()

        assertEquals(2, api.received.size)
        assertEquals(mapOf("h111" to 434, "h222" to 284), api.received[0].hexes_to_steps)
        assertEquals(mapOf("h111" to 0, "h222" to 0, "hEx" to 155), api.received[1].hexes_to_steps)
        // Both rows are marked synced exactly once.
        assertEquals(listOf("run-a" to 50, "run-b" to 50), repo.marked)
    }

    @Test
    fun `hexes already on the server are defended at zero not re-minted`() = runBlocking {
        // A synced session previously touched hSynced, so the server already
        // holds its defense; the legacy row must not mint the cumulative value.
        val api = FakeApi { ok }
        val repo = FakeRunSessionRepository(
            unsynced = listOf(session("legacy", totalSteps = 631, hexIds = listOf("hSynced", "hNew"))),
            synced = listOf(session("old-synced", totalSteps = 750, hexIds = listOf("hSynced"), xp = 100).copy(isSynced = true))
        )
        val reconciler = RunReconciler(
            RunSyncer(api),
            repo,
            FakeHexRepository(listOf(captured("hSynced", 631), captured("hNew", 200)))
        )

        reconciler.reconcileUnsyncedRuns()

        val payload = api.received.single()
        assertEquals(200, payload.hexes_to_steps["hNew"])  // minted exactly
        assertEquals(0, payload.hexes_to_steps["hSynced"]) // never re-minted
    }

    @Test
    fun `already_processed summary keeps the local xp instead of zeroing it`() = runBlocking {
        val already = ok.copy(xp_earned = 0, already_processed = true)
        val repo = FakeRunSessionRepository(unsynced = listOf(
            session("run-a", totalSteps = 631, hexIds = listOf("h111"), xp = 999)
        ))
        val reconciler = RunReconciler(
            RunSyncer(FakeApi { already }),
            repo,
            FakeHexRepository(listOf(captured("h111", 434)))
        )

        reconciler.reconcileUnsyncedRuns()

        assertEquals(listOf("run-a" to 999), repo.marked)
    }

    @Test
    fun `failed sync leaves the row unsynced for a later retry`() = runBlocking {
        val api = FakeApi { throw IOException("no internet") }
        val repo = FakeRunSessionRepository(unsynced = listOf(
            session("run-a", totalSteps = 631, hexIds = listOf("h111"))
        ))
        val reconciler = RunReconciler(
            RunSyncer(api),
            repo,
            FakeHexRepository(listOf(captured("h111", 434)))
        )

        reconciler.reconcileUnsyncedRuns()

        // Network failure -> nothing marked synced; retried next foreground.
        assertTrue(repo.marked.isEmpty())
    }

    @Test
    fun `zero-step no-op legacy row replays with empty hexes`() = runBlocking {
        val api = FakeApi { ok.copy(hexes_newly_captured = 0, xp_earned = 0) }
        val repo = FakeRunSessionRepository(unsynced = listOf(session("noop")))
        val reconciler = RunReconciler(RunSyncer(api), repo, FakeHexRepository())

        reconciler.reconcileUnsyncedRuns()

        val payload = api.received.single()
        assertEquals(0, payload.total_session_steps)
        assertTrue(payload.hexes_to_steps.isEmpty())
        assertEquals(listOf("noop" to 0), repo.marked)
    }
}
