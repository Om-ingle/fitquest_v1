package com.example.mobileapp.core.tts

import com.example.mobileapp.core.network.LiveCoachStore
import com.example.mobileapp.core.network.models.CoachResponse
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M8.4 — the app-scoped coordinator over a fake [TtsSynthesizer]. These are
 * the new-message / dedupe / lifecycle tests; the real engine adapter
 * ([AndroidTtsSynthesizer]) is framework glue and is not constructible in a
 * JVM unit test (android.speech.tts), exactly like the OkHttp socket adapter.
 *
 * The coordinator runs its collector on Dispatchers.Unconfined (the same
 * deterministic pattern as the M8.3B WebSocket tests), so a publish to the
 * real [LiveCoachStore] resumes the collector synchronously on the test
 * thread — no real network, no time-based waits.
 */
class CoachingSpeechControllerTest {

    private fun response(
        message: String,
        fingerprint: String = "fix-e-v1:abc",
        generatedAt: String = "2026-09-06T12:00:00.000000",
    ) = CoachResponse(
        generated_at = generatedAt,
        message = message,
        context_fingerprint = fingerprint
    )

    /** Records every speak/stop/release and can fake engine readiness/errors. */
    private class FakeSynthesizer : TtsSynthesizer {
        override var isReady: Boolean = false
        val spoken = mutableListOf<Pair<String, Boolean>>()
        var stopCalls = 0
            private set
        var releaseCalls = 0
            private set
        var throwOnSpeak = false
        private var readyListener: ((Boolean) -> Unit)? = null

        val spokenTexts: List<String>
            get() = spoken.map { it.first }

        override fun setOnReadyChanged(listener: (Boolean) -> Unit) {
            readyListener = listener
            listener(isReady)
        }

        fun becomeReady(value: Boolean) {
            isReady = value
            readyListener?.invoke(value)
        }

        override fun speak(text: String, flushPrevious: Boolean) {
            if (throwOnSpeak) throw RuntimeException("tts engine exploded")
            spoken.add(text to flushPrevious)
        }

        override fun stop() {
            stopCalls++
        }

        override fun release() {
            releaseCalls++
        }
    }

    private class Harness(
        val store: LiveCoachStore,
        val fake: FakeSynthesizer,
        val controller: CoachingSpeechController,
    )

    private fun harness(ready: Boolean = true): Harness {
        val store = LiveCoachStore()
        val fake = FakeSynthesizer().apply { isReady = ready }
        val controller = CoachingSpeechController(
            liveCoachStore = store,
            synthesizer = fake,
            gate = CoachingSpeechGate(),
            scope = CoroutineScope(Dispatchers.Unconfined)
        )
        controller.start()
        return Harness(store, fake, controller)
    }

    // ── 1. A genuinely new live message is spoken ────────────────────────────

    @Test
    fun `a new live message is spoken once and replaces any prior utterance`() {
        val h = harness()
        h.store.publish(response(message = "Great run today — recover well!"))

        assertEquals(listOf("Great run today — recover well!"), h.fake.spokenTexts)
        // flushPrevious=true: a newer coaching message cuts off an older one.
        assertEquals(true, h.fake.spoken.single().second)
    }

    // ── 2. A duplicate message is NOT re-spoken ──────────────────────────────

    @Test
    fun `a redelivered duplicate message is not spoken again`() {
        val h = harness()
        h.store.publish(response(message = "Take a short recovery walk."))
        // Distinct object (new generated_at) but identical content + fingerprint
        // — the sort of replay a reconnect could deliver. Must be silent.
        h.store.publish(
            response(message = "Take a short recovery walk.", generatedAt = "2026-09-06T12:01:00.000000")
        )

        assertEquals(listOf("Take a short recovery walk."), h.fake.spokenTexts)
    }

    // ── 3. A different / newer message IS spoken ─────────────────────────────

    @Test
    fun `a different newer message is spoken after an earlier one`() {
        val h = harness()
        h.store.publish(response(message = "First message."))
        h.store.publish(response(message = "Second, brand-new advice."))

        assertEquals(
            listOf("First message.", "Second, brand-new advice."),
            h.fake.spokenTexts
        )
    }

    @Test
    fun `same wording under a new context fingerprint is treated as new`() {
        val h = harness()
        h.store.publish(response(message = "Keep it up!", fingerprint = "fix-e-v1:ctxA"))
        h.store.publish(response(message = "Keep it up!", fingerprint = "fix-e-v1:ctxB"))

        assertEquals(2, h.fake.spoken.size)
    }

    // ── 4. Recomposition / navigation / stale state never re-trigger speech ──

    @Test
    fun `a message retained before start is never re-read aloud`() {
        val store = LiveCoachStore()
        val fake = FakeSynthesizer().apply { isReady = true }
        store.publish(response(message = "stale from a previous foreground"))
        val controller = CoachingSpeechController(
            liveCoachStore = store,
            synthesizer = fake,
            gate = CoachingSpeechGate(),
            scope = CoroutineScope(Dispatchers.Unconfined)
        )

        controller.start() // must NOT speak the retained value

        assertEquals(emptyList<String>(), fake.spokenTexts)

        store.publish(response(message = "a real new push", fingerprint = "fix-e-v1:next"))
        assertEquals(listOf("a real new push"), fake.spokenTexts)
    }

    @Test
    fun `start is idempotent - recomposition and re-entry never duplicate speech`() {
        val h = harness()
        h.controller.start()
        h.controller.start()

        h.store.publish(response(message = "one push"))

        assertEquals(listOf("one push"), h.fake.spokenTexts)
    }

    // ── 5. Engine not ready yet: newest pending message spoken when ready ────

    @Test
    fun `messages before readiness are kept and only the newest is spoken when ready`() {
        val h = harness(ready = false)

        h.store.publish(response(message = "oldest while binding", fingerprint = "f1"))
        h.store.publish(response(message = "newest while binding", fingerprint = "f2"))

        assertEquals(emptyList<String>(), h.fake.spokenTexts)

        h.fake.becomeReady(true)

        // The latest-wins pending was replaced, so only the newest is read.
        assertEquals(listOf("newest while binding"), h.fake.spokenTexts)
    }

    @Test
    fun `speech resumes for later messages after the engine reports ready late`() {
        val h = harness(ready = false)
        h.store.publish(response(message = "while unavailable", fingerprint = "f1"))
        h.store.publish(response(message = "still unavailable", fingerprint = "f2"))

        h.fake.becomeReady(true) // engine finally binds (e.g. a retry succeeded)
        assertEquals(listOf("still unavailable"), h.fake.spokenTexts)

        h.store.publish(response(message = "after ready", fingerprint = "f3"))
        assertEquals(listOf("still unavailable", "after ready"), h.fake.spokenTexts)
    }

    // ── 6. TTS init failure / unavailable engine never crashes ──────────────

    @Test
    fun `an engine that never becomes ready never speaks and never crashes`() {
        val h = harness(ready = false)
        h.store.publish(response(message = "m1", fingerprint = "f1"))
        h.store.publish(response(message = "m2", fingerprint = "f2"))
        h.store.publish(response(message = "m3", fingerprint = "f3"))

        assertEquals(emptyList<String>(), h.fake.spokenTexts)
        // The store/UI flow is completely unaffected by TTS being unavailable.
        assertEquals("m3", h.store.message.value?.message)
    }

    @Test
    fun `an engine error while speaking never crashes the coordinator`() {
        val h = harness()
        h.fake.throwOnSpeak = true
        h.store.publish(response(message = "m1", fingerprint = "f1")) // swallowed

        h.fake.throwOnSpeak = false
        h.store.publish(response(message = "m2", fingerprint = "f2"))

        assertEquals(listOf("m2"), h.fake.spokenTexts)
    }

    @Test
    fun `a blank message is never handed to the engine`() {
        val h = harness()
        h.store.publish(CoachResponse(message = "   "))
        h.store.publish(CoachResponse())

        assertEquals(emptyList<String>(), h.fake.spokenTexts)
    }

    // ── 7. Disabling prevents speech without affecting coaching messages ────

    @Test
    fun `disabling stops speech and coaching messages still flow to the ui`() {
        val h = harness()
        h.store.publish(response(message = "heard", fingerprint = "f1"))
        assertEquals(listOf("heard"), h.fake.spokenTexts)

        h.controller.enabled = false
        assertEquals("disabling stops any current utterance", 1, h.fake.stopCalls)

        h.store.publish(response(message = "silent while disabled", fingerprint = "f2"))
        assertEquals(listOf("heard"), h.fake.spokenTexts)
        // The coaching state itself is untouched — the Home card still updates.
        assertEquals("silent while disabled", h.store.message.value?.message)

        h.controller.enabled = true
        h.store.publish(response(message = "new after re-enable", fingerprint = "f3"))
        assertEquals(listOf("heard", "new after re-enable"), h.fake.spokenTexts)
    }

    // ── 8. Lifecycle cleanup ─────────────────────────────────────────────────

    @Test
    fun `release stops observation stops speech and releases the engine`() {
        val h = harness()
        h.store.publish(response(message = "first", fingerprint = "f1"))
        assertEquals(1, h.fake.spoken.size)

        h.controller.release()

        assertTrue(h.fake.stopCalls >= 1)
        assertEquals(1, h.fake.releaseCalls)

        h.store.publish(response(message = "after release", fingerprint = "f2"))
        assertEquals("collector stopped: no speech after release", 1, h.fake.spoken.size)
    }
}
