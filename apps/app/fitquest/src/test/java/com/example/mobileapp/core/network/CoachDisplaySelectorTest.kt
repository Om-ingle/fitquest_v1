package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M8.5 — the pure freshness selector that decides what the Home coach card shows
 * between the LIVE push slot ([LiveCoachStore]) and the pull cache
 * ([CoachCache]). Cases A/B/C from the M8.5 spec, plus the edge behaviour:
 *
 *  - A: an OLD live push loses to a FRESH pull of a NEWER context (the no-push
 *       fallback un-shadows the card);
 *  - B: a FRESH live push of a NEWER context beats a STALE pull;
 *  - C: the SAME context fingerprint preserves the live-push presentation;
 *  - missing fingerprints / indeterminate timestamps degrade to generated_at or
 *    to the pre-M8.5 live default — never a crash.
 */
class CoachDisplaySelectorTest {

    private fun response(
        message: String,
        fingerprint: String? = "fix-e-v1:ctxA",
        generatedAt: String? = "2026-09-06T10:00:00.000000",
    ) = CoachResponse(
        generated_at = generatedAt,
        message = message,
        context_fingerprint = fingerprint,
    )

    private fun success(response: CoachResponse) = CoachFetcher.Outcome.Success(response)

    private fun shown(display: CoachDisplay): CoachResponse? =
        (display.outcome as? CoachFetcher.Outcome.Success)?.response

    // ── A: old live push vs fresh pull of a newer context ────────────────────

    @Test
    fun `A old live push loses to a fresh pull for a newer context`() {
        // stale live: run A credited hours ago; fresh pull: run B just synced.
        val staleLive = response(message = "stale live for run A", fingerprint = "ctx:runA",
            generatedAt = "2026-09-06T09:00:00.000000")
        val freshPull = success(response(message = "fresh pull for run B", fingerprint = "ctx:runB",
            generatedAt = "2026-09-06T11:00:00.000000"))

        val display = CoachDisplaySelector.select(staleLive, freshPull)

        assertTrue(display.outcome is CoachFetcher.Outcome.Success)
        assertEquals("fresh pull for run B", shown(display)?.message)
        assertFalse("a pull fallback is never branded live", display.isLive)
    }

    // ── B: new live push of a newer context vs a stale pull ──────────────────

    @Test
    fun `B a new live push for a newer context beats a stale pull`() {
        val freshLive = response(message = "new live after run B", fingerprint = "ctx:runB",
            generatedAt = "2026-09-06T11:00:00.000000")
        val stalePull = success(response(message = "stale pull for run A", fingerprint = "ctx:runA",
            generatedAt = "2026-09-06T09:00:00.000000"))

        val display = CoachDisplaySelector.select(freshLive, stalePull)

        assertTrue(display.outcome is CoachFetcher.Outcome.Success)
        assertEquals("new live after run B", shown(display)?.message)
        assertTrue("a genuinely newest live push keeps the live heading", display.isLive)
    }

    // ── C: same context preserves the live-push presentation ─────────────────

    @Test
    fun `C same context keeps the live push even when the cached pull is newer`() {
        val live = response(message = "live wording", fingerprint = "ctx:runA",
            generatedAt = "2026-09-06T10:00:00.000000")
        // Same context; the pull was generated slightly later but for the SAME
        // server fingerprint — the card must not churn away from the live view.
        val pull = success(response(message = "pull wording same ctx", fingerprint = "ctx:runA",
            generatedAt = "2026-09-06T10:05:00.000000"))

        val display = CoachDisplaySelector.select(live, pull)

        assertEquals("live wording", shown(display)?.message)
        assertTrue(display.isLive)
    }

    @Test
    fun `C same context keeps the live push when it is the newer generation`() {
        val live = response(message = "live wording", fingerprint = "ctx:runA",
            generatedAt = "2026-09-06T10:05:00.000000")
        val pull = success(response(message = "pull wording same ctx", fingerprint = "ctx:runA",
            generatedAt = "2026-09-06T10:00:00.000000"))

        val display = CoachDisplaySelector.select(live, pull)

        assertEquals("live wording", shown(display)?.message)
        assertTrue(display.isLive)
    }

    // ── Freshness fallbacks when fingerprints are absent ─────────────────────

    @Test
    fun `different contexts decide by generated_at when fingerprints are absent`() {
        val live = response(message = "live no fp", fingerprint = null,
            generatedAt = "2026-09-06T09:00:00.000000")
        val pull = success(response(message = "pull no fp newer", fingerprint = null,
            generatedAt = "2026-09-06T11:00:00.000000"))

        val display = CoachDisplaySelector.select(live, pull)

        assertEquals("pull no fp newer", shown(display)?.message)
        assertFalse(display.isLive)
    }

    @Test
    fun `indeterminate timestamps fall back to the live push`() {
        val live = response(message = "live unparseable", fingerprint = "ctx:runB",
            generatedAt = "not-a-timestamp")
        val pull = success(response(message = "pull unparseable", fingerprint = "ctx:runA",
            generatedAt = "also-not-a-timestamp"))

        val display = CoachDisplaySelector.select(live, pull)

        // Cannot prove the pull is newer -> keep the live push (pre-M8.5 default).
        assertEquals("live unparseable", shown(display)?.message)
        assertTrue(display.isLive)
    }

    @Test
    fun `equal generated_at across different contexts keeps the live push`() {
        val live = response(message = "live tie", fingerprint = "ctx:runA",
            generatedAt = "2026-09-06T10:00:00.000000")
        val pull = success(response(message = "pull tie", fingerprint = "ctx:runB",
            generatedAt = "2026-09-06T10:00:00.000000"))

        val display = CoachDisplaySelector.select(live, pull)

        assertEquals("live tie", shown(display)?.message)
        assertTrue(display.isLive)
    }

    // ── No live push → the pull path exactly as before ───────────────────────

    @Test
    fun `no live push returns the pull outcome unchanged`() {
        val pull = success(response(message = "plain pull advice", fingerprint = "ctx:runA"))

        val display = CoachDisplaySelector.select(null, pull)

        assertTrue(display.outcome === pull)   // same object, nothing re-wrapped
        assertFalse(display.isLive)
    }

    @Test
    fun `no live push and no pull yet means still loading`() {
        val display = CoachDisplaySelector.select(null, null)

        assertNull(display.outcome)
        assertFalse(display.isLive)
    }

    @Test
    fun `no live push keeps an errored pull visible for retry`() {
        val pull = CoachFetcher.Outcome.NetworkError("offline")

        val display = CoachDisplaySelector.select(null, pull)

        assertTrue(display.outcome is CoachFetcher.Outcome.NetworkError)
        assertFalse(display.isLive)
    }

    // ── Live push wins while the pull is loading / failed ────────────────────

    @Test
    fun `live push is shown while the pull is still loading`() {
        val live = response(message = "live while loading", fingerprint = "ctx:runA")

        val display = CoachDisplaySelector.select(live, null)

        assertEquals("live while loading", shown(display)?.message)
        assertTrue(display.isLive)
    }

    @Test
    fun `a pull error never hides a present live push`() {
        val live = response(message = "live while pull errored", fingerprint = "ctx:runA")
        val pullError = CoachFetcher.Outcome.HttpError(503)

        val display = CoachDisplaySelector.select(live, pullError)

        assertEquals("live while pull errored", shown(display)?.message)
        assertTrue(display.isLive)
    }

    // ── generated_at sort key (the freshness clock, no java.time) ────────────

    @Test
    fun `generatedAtSortKey orders naive utc timestamps chronologically`() {
        val earlier = generatedAtSortKey("2026-09-06T09:59:00.000000")!!
        val later = generatedAtSortKey("2026-09-06T10:00:00.123456")!!
        assertTrue(later > earlier)
        // Same length regardless of whether a fractional part was serialised.
        assertEquals(earlier.length, later.length)
    }

    @Test
    fun `generatedAtSortKey treats a missing fraction as the top of the second`() {
        // Python isoformat() drops ".000000" when microseconds are zero.
        val noFraction = generatedAtSortKey("2026-09-06T10:00:00")!!
        val subSecond = generatedAtSortKey("2026-09-06T10:00:00.000001")!!
        assertTrue(subSecond > noFraction)
    }

    @Test
    fun `generatedAtSortKey normalises any fraction width to nine digits`() {
        val a = generatedAtSortKey("2026-09-06T10:00:00.1")!!          // 100 ms
        val b = generatedAtSortKey("2026-09-06T10:00:00.100000")!!     // same 100 ms
        val c = generatedAtSortKey("2026-09-06T10:00:00.2")!!          // 200 ms
        assertEquals(a, b)
        assertTrue(c > a)
    }

    @Test
    fun `generatedAtSortKey returns null for an unknown serialisation`() {
        assertNull(generatedAtSortKey(null))
        assertNull(generatedAtSortKey(""))
        assertNull(generatedAtSortKey("2026-09-06"))
        assertNull(generatedAtSortKey("2026-09-06T10:00:00.123456+00:00")) // offset never sent
        assertNull(generatedAtSortKey("garbage"))
    }
}
