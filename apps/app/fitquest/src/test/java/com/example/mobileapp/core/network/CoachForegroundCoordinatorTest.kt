package com.example.mobileapp.core.network

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M8.5 — foreground ordering (case E): the live channel is opened BEFORE
 * unsynced runs are replayed, and reconciliation + the post-replay pull refresh
 * still happen when opening the channel fails. Dependencies are injected as
 * function handles, so ordering is asserted with no WebSocket/Room/network.
 */
class CoachForegroundCoordinatorTest {

    @Test
    fun `E the live channel is opened before reconciliation begins`() = runBlocking {
        val events = mutableListOf<String>()
        val coordinator = CoachForegroundCoordinator(
            openLiveChannel = { events += "open-live-channel" },
            reconcileUnsyncedRuns = {
                events += "reconcile"
                false // nothing newly credited
            },
            refreshPullAfterNewRun = { events += "refresh-pull" },
        )

        coordinator.onForeground()

        assertEquals(listOf("open-live-channel", "reconcile"), events)
    }

    @Test
    fun `E reconciliation still proceeds when opening the live channel throws`() = runBlocking {
        val events = mutableListOf<String>()
        val coordinator = CoachForegroundCoordinator(
            openLiveChannel = {
                events += "open-live-channel"
                throw RuntimeException("socket factory exploded")
            },
            reconcileUnsyncedRuns = {
                events += "reconcile"
                true
            },
            refreshPullAfterNewRun = { events += "refresh-pull" },
        )

        coordinator.onForeground()

        // A channel failure must never abort the replay (or the pull catch-up).
        assertEquals(listOf("open-live-channel", "reconcile", "refresh-pull"), events)
    }

    @Test
    fun `the pull cache is refreshed once after a newly credited run`() = runBlocking {
        var refreshCalls = 0
        val coordinator = CoachForegroundCoordinator(
            openLiveChannel = {},
            reconcileUnsyncedRuns = { true }, // a run was just marked synced
            refreshPullAfterNewRun = { refreshCalls++ },
        )

        coordinator.onForeground()

        assertEquals(1, refreshCalls)
    }

    @Test
    fun `no pull refresh when reconciliation credits nothing`() = runBlocking {
        var refreshCalls = 0
        val coordinator = CoachForegroundCoordinator(
            openLiveChannel = {},
            reconcileUnsyncedRuns = { false }, // nothing to replay / nothing synced
            refreshPullAfterNewRun = { refreshCalls++ },
        )

        coordinator.onForeground()

        assertEquals("no new context -> no repeated LLM request", 0, refreshCalls)
    }

    @Test
    fun `a replay that fails to sync anything does not trigger a pull refresh`() = runBlocking {
        var refreshCalls = 0
        val coordinator = CoachForegroundCoordinator(
            openLiveChannel = {},
            reconcileUnsyncedRuns = { false }, // e.g. network down, rows still unsynced
            refreshPullAfterNewRun = { refreshCalls++ },
        )

        coordinator.onForeground()

        assertEquals(0, refreshCalls)
    }

    @Test
    fun `the coordinator never opens the channel twice for one foreground`() {
        var openCalls = 0
        val coordinator = CoachForegroundCoordinator(
            openLiveChannel = { openCalls++ },
            reconcileUnsyncedRuns = { false },
            refreshPullAfterNewRun = {},
        )

        runBlocking { coordinator.onForeground() }

        assertEquals(1, openCalls)
    }

    @Test
    fun `reconcile is always attempted even when nothing needs refreshing`() {
        var reconcileCalls = 0
        val coordinator = CoachForegroundCoordinator(
            openLiveChannel = {},
            reconcileUnsyncedRuns = {
                reconcileCalls++
                false
            },
            refreshPullAfterNewRun = {},
        )

        runBlocking { coordinator.onForeground() }

        assertTrue(reconcileCalls >= 1)
    }
}
