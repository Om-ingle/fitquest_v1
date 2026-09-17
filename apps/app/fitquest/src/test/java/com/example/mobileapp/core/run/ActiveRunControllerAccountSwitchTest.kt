package com.example.mobileapp.core.run

import com.example.mobileapp.core.auth.IdentityProvider
import com.example.mobileapp.core.capture.HexCaptureSnapshot
import com.example.mobileapp.core.capture.RunSessionEngine
import com.example.mobileapp.core.data.local.ActiveRunEntity
import com.example.mobileapp.core.data.local.ActiveRunRepository
import com.example.mobileapp.core.session.AccountScopeGuard
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The account-switch rule for a run that is still in progress.
 *
 * Two things have to be true at once when the account changes mid-run, and they
 * pull in opposite directions:
 *
 *  * The run must stop being LIVE. Its sensors, its foreground notification and
 *    its in-memory tallies belong to an account that is no longer signed in;
 *    leaving it active drops the next account onto somebody else's run screen.
 *  * The run must NOT be deleted. The checkpoint row is how the account that
 *    started it gets it back, so tearing down the run must not clear it.
 *
 * The teardown path already deleted the checkpoint unconditionally — that is
 * correct when a run finishes and wrong when the account changes — so this pins
 * the difference. It is the one decision in this class that can destroy a user's
 * data, which is why [RunServiceLauncher] and [RunSessionEngine] are seams: it is
 * reachable here without a Context, a foreground service or a sensor stack.
 */
class ActiveRunControllerAccountSwitchTest {

    private companion object {
        const val ACCOUNT_A = "11111111-1111-4111-8111-111111111111"
        const val ACCOUNT_B = "22222222-2222-4222-8222-222222222222"
    }

    private class MutableIdentity(initial: String? = null) : IdentityProvider {
        private val state = MutableStateFlow(initial)
        override fun currentSubject(): String? = state.value
        override val subject: Flow<String?> = state
        fun become(subject: String?) {
            state.value = subject
        }
    }

    private class FakeActiveRunRepository : ActiveRunRepository {
        val saved = mutableListOf<ActiveRunEntity>()
        var clearCalls = 0
            private set

        override fun observeActiveRun(): Flow<ActiveRunEntity?> = MutableStateFlow(saved.lastOrNull())
        override suspend fun getActiveRun(): ActiveRunEntity? = saved.lastOrNull()
        override suspend fun saveActiveRun(entity: ActiveRunEntity) {
            saved += entity
        }

        override suspend fun clearActiveRun() {
            clearCalls++
            saved.clear()
        }
    }

    private class FakeEngine : RunSessionEngine {
        private val _state = MutableStateFlow(HexCaptureSnapshot())
        override val state: StateFlow<HexCaptureSnapshot> = _state

        var discardCalls = 0
            private set

        fun beginTracking(steps: Int) {
            _state.value = HexCaptureSnapshot(isTracking = true, sessionSteps = steps)
        }

        override fun discardSession() {
            discardCalls++
            _state.value = _state.value.copy(isTracking = false, sessionSteps = 0)
        }
    }

    private class RecordingLauncher : RunServiceLauncher {
        val actions = mutableListOf<String>()
        override fun launch(action: String) {
            actions += action
        }
    }

    private data class Fixture(
        val identity: MutableIdentity,
        val repository: FakeActiveRunRepository,
        val engine: FakeEngine,
        val launcher: RecordingLauncher,
        val controller: ActiveRunController,
    )

    private fun fixture(signedInAs: String? = ACCOUNT_B): Fixture {
        val identity = MutableIdentity(signedInAs)
        val repository = FakeActiveRunRepository()
        val engine = FakeEngine()
        val launcher = RecordingLauncher()
        // Armed: this class tests the account-switch teardown, not the
        // fail-closed gate. A closed guard refuses startRun outright, so every
        // test here would pass vacuously — there would be no live run to tear
        // down. The refusal itself is covered by AccountScopeFailClosedTest.
        val guard = AccountScopeGuard().apply { setActive(true) }
        return Fixture(
            identity, repository, engine, launcher,
            ActiveRunController(repository, engine, identity, launcher, guard)
        )
    }

    private fun Fixture.startRunAs(account: String?, runId: String = "run-1") {
        identity.become(account)
        engine.beginTracking(steps = 500)
        controller.startRun(runId, RunTiming(startedAtMillis = 1_000L, pausedAccumulatedMillis = 0L))
    }

    private suspend fun awaitUntil(timeoutMillis: Long = 2_000, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMillis
        while (System.currentTimeMillis() < deadline) {
            if (condition()) return
            delay(10)
        }
        org.junit.Assert.fail("condition not met within ${timeoutMillis}ms")
    }

    @Test
    fun `a run started by one account is dropped when another signs in`() {
        val f = fixture()
        f.startRunAs(ACCOUNT_B)
        assertTrue(f.controller.isActive)

        f.controller.onAccountChanged(ACCOUNT_A)

        assertFalse("Account A was left on Account B's live run", f.controller.isActive)
        assertTrue(
            "The run controller was not stopped, so the notification and sensors outlive the account",
            f.launcher.actions.contains(RunTrackingService.ACTION_STOP_RUN)
        )
        assertEquals("The live session was not released", 1, f.engine.discardCalls)
    }

    @Test
    fun `dropping the run does NOT clear the checkpoint the departing account left`() = runBlocking {
        val f = fixture()
        f.startRunAs(ACCOUNT_B)
        awaitUntil { f.repository.saved.isNotEmpty() }

        f.controller.onAccountChanged(ACCOUNT_A)
        delay(200)   // let any launched teardown reach the repository

        assertFalse(
            "Tearing the service down would delete Account B's checkpoint and lose its run",
            f.controller.shouldClearCheckpointOnStop()
        )
        assertEquals(
            "Account B's checkpoint was deleted by the account switch",
            0, f.repository.clearCalls
        )
        assertEquals(1, f.repository.saved.size)
    }

    @Test
    fun `the account that owns the run is unaffected by its own subject re-emitting`() {
        val f = fixture()
        f.startRunAs(ACCOUNT_B)

        f.controller.onAccountChanged(ACCOUNT_B)

        assertTrue("The owner's own run was dropped", f.controller.isActive)
        assertTrue(f.controller.shouldClearCheckpointOnStop())
        assertFalse(f.launcher.actions.contains(RunTrackingService.ACTION_STOP_RUN))
        assertEquals(0, f.engine.discardCalls)
    }

    @Test
    fun `signing out mid-run drops the run and keeps its checkpoint`() {
        val f = fixture()
        f.startRunAs(ACCOUNT_B)

        f.controller.onAccountChanged(null)   // signed out

        assertFalse(f.controller.isActive)
        assertFalse(f.controller.shouldClearCheckpointOnStop())
    }

    @Test
    fun `a finished run still clears its checkpoint`() = runBlocking {
        val f = fixture()
        f.startRunAs(ACCOUNT_B)
        assertTrue(f.controller.shouldClearCheckpointOnStop())

        f.controller.finishRun()
        awaitUntil { f.repository.clearCalls == 1 }

        assertFalse(f.controller.isActive)
        assertTrue(
            "finishRun must keep clearing — only an account switch preserves the row",
            f.controller.shouldClearCheckpointOnStop()
        )
    }

    @Test
    fun `the next run started after an account switch clears its checkpoint normally`() {
        val f = fixture()
        f.startRunAs(ACCOUNT_B, runId = "run-b")
        f.controller.onAccountChanged(ACCOUNT_A)
        assertFalse(f.controller.shouldClearCheckpointOnStop())

        // A starts its own run: the abandon flag must not leak into it, or A's
        // run would be abandoned in place and never cleared.
        f.startRunAs(ACCOUNT_A, runId = "run-a")

        assertTrue(f.controller.isActive)
        assertTrue(
            "The account-switch flag leaked into the next account's run",
            f.controller.shouldClearCheckpointOnStop()
        )
        assertEquals("run-a", f.controller.currentRunId())
    }

    @Test
    fun `an account change with no run active does nothing`() {
        val f = fixture()

        f.controller.onAccountChanged(ACCOUNT_A)

        assertFalse(f.controller.isActive)
        assertTrue(f.launcher.actions.isEmpty())
        assertEquals(0, f.engine.discardCalls)
        assertTrue(f.controller.shouldClearCheckpointOnStop())
    }
}
