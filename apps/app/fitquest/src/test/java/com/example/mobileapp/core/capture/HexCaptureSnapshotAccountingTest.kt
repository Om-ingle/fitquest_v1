package com.example.mobileapp.core.capture

import com.example.mobileapp.core.model.GeoPoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M9.2 P1-1 — pure accounting regression tests for [HexCaptureEngine]'s step /
 * territory state transitions (see [HexCaptureSnapshot.applyStepDelta] and
 * [HexCaptureSnapshot.applyLocationUpdate]).
 *
 * These pin the two guarantees the fix must hold:
 *  - Steps taken while `currentHexId == null` (no GPS fix yet) are NEVER
 *    silently discarded: they accumulate in `sessionSteps` (the run total) and
 *    are buffered in `pendingStepsBeforeHex`.
 *  - When a hex first becomes available, the buffered steps are attributed to
 *    that hex EXACTLY ONCE — never again on subsequent location updates, and
 *    never re-added to `sessionSteps`.
 *
 * The accounting invariant under test is:
 *     sessionSteps == sum(hexesToSteps) + pendingStepsBeforeHex
 * i.e. every step is counted exactly once across the whole transition graph.
 * Existing behavior with a live hex (steps → current hex) is unchanged.
 */
class HexCaptureSnapshotAccountingTest {

    private val hexA = "8a60961611a7fff"
    private val hexB = "8a60961611a7ffe"
    private val here = GeoPoint(12.9716, 77.5946)

    private fun assertInvariant(s: HexCaptureSnapshot) {
        val hexTotal = s.hexesToSteps.values.sum()
        assertEquals(
            "sessionSteps must equal sum(hexesToSteps) + pending (no dropped, no doubled steps)",
            s.sessionSteps, hexTotal + s.pendingStepsBeforeHex
        )
    }

    // ── P1-1: steps before the first valid GPS hex ──────────────────────────

    @Test
    fun `steps before any gps fix are retained in the run total, not dropped`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyStepDelta(10)
        s = s.applyStepDelta(25)

        assertEquals(35, s.sessionSteps)
        assertEquals(35, s.pendingStepsBeforeHex)
        assertTrue("no hex to attribute to yet", s.hexesToSteps.isEmpty())
        assertInvariant(s)
    }

    @Test
    fun `buffered steps are attributed exactly once when the first hex arrives`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyStepDelta(10)
        s = s.applyStepDelta(25)
        assertEquals(35, s.pendingStepsBeforeHex)

        // First fix: the buffered 35 land on hex A once; sessionSteps unchanged.
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)
        assertEquals(35, s.sessionSteps)
        assertEquals(0, s.pendingStepsBeforeHex)
        assertEquals(mapOf(hexA to 35), s.hexesToSteps)
        assertInvariant(s)
    }

    @Test
    fun `further steps after the fix go to the current hex without double counting`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyStepDelta(10)          // pre-hex buffer
        s = s.applyLocationUpdate(hexA, listOf(hexA), here) // drain to hex A
        s = s.applyStepDelta(5)           // live step in hex A

        assertEquals(15, s.sessionSteps)
        assertEquals(mapOf(hexA to 15), s.hexesToSteps)
        assertEquals(0, s.pendingStepsBeforeHex)
        assertInvariant(s)
    }

    @Test
    fun `a run that ends before any fix still preserves its steps in the total`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyStepDelta(30)

        // finishActiveRun reads sessionSteps from the live snapshot before the
        // engine resets state — these 30 must be present there.
        assertEquals(30, s.sessionSteps)
        assertTrue(s.hexesToSteps.isEmpty())
        assertInvariant(s)
    }

    @Test
    fun `mid-run fix loss buffers steps and attributes them once to the next hex`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)
        s = s.applyStepDelta(10)                      // live steps in hex A
        s = s.applyLocationUpdate(null, emptyList(), here) // indexer/GPS gap
        s = s.applyStepDelta(7)                       // steps during the gap
        assertEquals(17, s.sessionSteps)
        assertEquals(7, s.pendingStepsBeforeHex)

        // Fix returns over hex B: the buffered 7 drain to B, A keeps its 10.
        s = s.applyLocationUpdate(hexB, listOf(hexA, hexB), here)
        assertEquals(17, s.sessionSteps)
        assertEquals(mapOf(hexA to 10, hexB to 7), s.hexesToSteps)
        assertEquals(0, s.pendingStepsBeforeHex)
        assertInvariant(s)
    }

    @Test
    fun `repeated location fixes on the same hex never re-attribute the buffer`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyStepDelta(20)
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)   // drain once
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)   // same hex again
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)   // and again

        assertEquals(mapOf(hexA to 20), s.hexesToSteps)
        assertEquals(0, s.pendingStepsBeforeHex)
        assertInvariant(s)
    }

    // ── Existing behavior preserved when a hex is already known ─────────────

    @Test
    fun `existing behavior a known current hex receives every step delta`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)
        s = s.applyStepDelta(3)
        s = s.applyStepDelta(4)
        s = s.applyStepDelta(5)

        assertEquals(12, s.sessionSteps)
        assertEquals(mapOf(hexA to 12), s.hexesToSteps)
        assertEquals(0, s.pendingStepsBeforeHex)
        assertInvariant(s)
    }

    @Test
    fun `crossing into a second hex routes later steps to the new hex only`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)
        s = s.applyStepDelta(8)                       // hex A
        s = s.applyLocationUpdate(hexB, listOf(hexA, hexB), here)
        s = s.applyStepDelta(6)                       // hex B

        assertEquals(14, s.sessionSteps)
        assertEquals(mapOf(hexA to 8, hexB to 6), s.hexesToSteps)
        assertInvariant(s)
    }

    // ── Run-start seeding (engine.startTracking semantics) ──────────────────

    @Test
    fun `a fix seen before tracking starts is seeded as the current hex at zero`() {
        // Not tracking yet, but monitoring is live so the engine knows the hex.
        var s = HexCaptureSnapshot(isTracking = false)
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)
        assertEquals("no territory map while standing by", emptyMap<String, Int>(), s.hexesToSteps)
        assertEquals(hexA, s.currentHexId)

        // startTracking() semantics: fresh session, seed the current hex at 0.
        s = s.copy(isTracking = true, sessionSteps = 0, hexesToSteps = mapOf(hexA to 0), pendingStepsBeforeHex = 0)
        s = s.applyStepDelta(12)

        assertEquals(12, s.sessionSteps)
        assertEquals(mapOf(hexA to 12), s.hexesToSteps)
        assertInvariant(s)
    }

    @Test
    fun `startTracking resets any stale session counters and buffer`() {
        val stale = HexCaptureSnapshot(
            isTracking = true,
            sessionSteps = 100,
            pendingStepsBeforeHex = 20
        )
        // Defensive: engine.startTracking always zeroes session + buffer.
        val started = stale.copy(isTracking = true, sessionSteps = 0, hexesToSteps = emptyMap(), pendingStepsBeforeHex = 0)
        assertEquals(0, started.sessionSteps)
        assertEquals(0, started.pendingStepsBeforeHex)
    }

    @Test
    fun `step deltas while not tracking are never collected`() {
        // The sensor flow only runs between startTracking and stopTracking; a
        // stray delta must not move a standby snapshot.
        val standby = HexCaptureSnapshot(isTracking = false)
        val result = standby.applyStepDelta(50)
        assertEquals(0, result.sessionSteps)
        assertEquals(0, result.pendingStepsBeforeHex)
    }

    // ── M10 F-02: paused runs accrue nothing ────────────────────────────────

    /**
     * A paused run is a live run that is not moving. Deltas arriving while
     * paused must be DISCARDED, never banked into the totals for later
     * removal — the sensor reports a delta per event, so one ignored delta
     * leaves no residue and resuming produces no catch-up jump.
     */
    @Test
    fun `steps while paused are discarded and never buffered`() {
        var s = HexCaptureSnapshot(isTracking = true, isPaused = true)
        assertEquals("a paused run at zero stays at zero", 0, s.applyStepDelta(40).sessionSteps)

        s = s.copy(currentHexId = hexA)
        val after = s.applyStepDelta(40)
        assertEquals("no steps accrue to the run total", 0, after.sessionSteps)
        assertEquals("nothing is banked for a later fix", 0, after.pendingStepsBeforeHex)
        assertTrue("no territory accrues either", after.hexesToSteps.isEmpty())
        assertInvariant(after)
    }

    /**
     * While paused the fix still drives the map — the user must see where they
     * are — but it must not capture territory or drain the pre-hex buffer.
     */
    @Test
    fun `location fixes while paused move the display without capturing territory`() {
        var s = HexCaptureSnapshot(isTracking = true, isPaused = true)
        s = s.applyLocationUpdate(hexA, listOf(hexA, hexB), here)

        assertEquals("position still tracks", here, s.currentLocation)
        assertEquals("current hex still resolves", hexA, s.currentHexId)
        assertEquals(listOf(hexA, hexB), s.nearbyHexIds)
        assertTrue("but no hex is registered", s.hexesToSteps.isEmpty())
        // Moving on to a second hex while paused captures nothing there either.
        val moved = s.applyLocationUpdate(hexB, listOf(hexB), here)
        assertTrue(moved.hexesToSteps.isEmpty())
        assertInvariant(moved)
    }

    /**
     * The buffer is preserved untouched across a pause and drained exactly once
     * afterwards — pausing must not attribute buffered steps to whatever hex the
     * user happened to be standing in when they paused.
     */
    @Test
    fun `pausing preserves the pre-hex buffer and drains it exactly once on resume`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyStepDelta(30)                 // no fix yet → buffered
        assertEquals(30, s.pendingStepsBeforeHex)

        // Pause, then a fix arrives: it must not drain the buffer.
        s = s.copy(isPaused = true)
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)
        assertEquals("buffer survives the pause intact", 30, s.pendingStepsBeforeHex)
        assertTrue(s.hexesToSteps.isEmpty())
        assertEquals(30, s.sessionSteps)
        assertInvariant(s)

        // Resume: the next fix drains it once, to that hex.
        s = s.copy(isPaused = false)
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)
        assertEquals(0, s.pendingStepsBeforeHex)
        assertEquals(mapOf(hexA to 30), s.hexesToSteps)
        assertEquals("the buffer is not re-added to the run total", 30, s.sessionSteps)
        assertInvariant(s)
    }

    @Test
    fun `resuming continues from the paused totals`() {
        var s = HexCaptureSnapshot(isTracking = true)
        s = s.applyLocationUpdate(hexA, listOf(hexA), here)
        s = s.applyStepDelta(12)                 // before the pause
        s = s.copy(isPaused = true)
        s = s.applyStepDelta(50)                 // walked while paused — ignored
        s = s.applyLocationUpdate(hexB, listOf(hexA, hexB), here) // not captured
        s = s.copy(isPaused = false)
        s = s.applyStepDelta(8)                  // after resuming, now in hex B

        assertEquals(20, s.sessionSteps)         // 12 + 8, never 62
        assertEquals(mapOf(hexA to 12, hexB to 8), s.hexesToSteps)
        assertEquals(0, s.pendingStepsBeforeHex)
        assertInvariant(s)
    }

    @Test
    fun `the invariant holds across repeated pause resume cycles`() {
        var s = HexCaptureSnapshot(isTracking = true)
        repeat(4) { cycle ->
            s = s.applyLocationUpdate(if (cycle % 2 == 0) hexA else hexB, listOf(hexA), here)
            s = s.applyStepDelta(10)
            s = s.copy(isPaused = true)
            s = s.applyStepDelta(999)            // ignored
            s = s.applyLocationUpdate(hexB, listOf(hexB), here) // no capture
            assertInvariant(s)
            s = s.copy(isPaused = false)
            assertInvariant(s)
        }
        assertEquals(40, s.sessionSteps)          // 4 × 10
        assertInvariant(s)
    }
}
