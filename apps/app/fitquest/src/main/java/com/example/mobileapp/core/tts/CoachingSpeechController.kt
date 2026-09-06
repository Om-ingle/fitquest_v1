package com.example.mobileapp.core.tts

import com.example.mobileapp.core.network.LiveCoachStore
import com.example.mobileapp.core.network.models.CoachResponse
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch

/**
 * M8.4 — the app-scoped coordinator that turns each genuinely NEW live
 * `coaching_message` into spoken coaching.
 *
 * The speech trigger REUSES the existing M8.3B state flow — there is no
 * parallel coaching pipeline. [CoachingWsClient] decodes a `coaching_message`
 * and calls `LiveCoachStore.publish`; [LiveCoachStore.message] is exactly the
 * state through which that message reaches the Home UI. This coordinator just
 * collects that same flow at the APP level (Koin singleton, process scope),
 * deliberately NOT inside any screen composition, so:
 *
 * - recomposition / tab navigation / Home → Profile → Home / returning to Home
 *   can never re-trigger speech (they publish nothing);
 * - a fresh push is spoken even when the user is on another tab or mid-run,
 *   because the push itself is the trigger, not the screen being visible.
 *
 * New-message detection is delegated to [CoachingSpeechGate] (bounded
 * in-memory dedupe on `context_fingerprint` + content — no DB persistence).
 * Readiness of the engine is observed via [TtsSynthesizer.setOnReadyChanged]:
 * if a fresh message arrives before the engine has finished binding it is kept
 * as a single "latest wins" pending text and spoken when the engine becomes
 * ready (a newer message while still pending simply replaces it). If the
 * engine never becomes ready (init failure / TTS unavailable), nothing is ever
 * spoken and nothing crashes.
 *
 * M8.4 adds no settings UI (see ADR 0005: the app has no settings surface and
 * the spec forbids inventing one); [enabled] is a programmatic seam that
 * defaults to ON. Disabling stops any current utterance and prevents speech
 * while leaving [LiveCoachStore] and the coaching card completely unaffected.
 */
class CoachingSpeechController(
    private val liveCoachStore: LiveCoachStore,
    private val synthesizer: TtsSynthesizer,
    private val gate: CoachingSpeechGate,
    private val scope: CoroutineScope,
) {

    /** Master switch. Default ON. Disabling prevents speech without touching the coaching state flow. */
    var enabled: Boolean = true
        set(value) {
            if (field == value) return
            field = value
            if (!value) {
                pendingText = null
                runCatching { synthesizer.stop() }
            }
        }

    @Volatile
    private var synthesizerReady = false

    private var pendingText: String? = null

    private var collectJob: Job? = null

    /**
     * Starts observing live pushes. Idempotent — safe to call more than once
     * (navigation/activity recreation never duplicates the collector). The
     * engine reports its current readiness on registration.
     */
    fun start() {
        if (collectJob?.isActive == true) return
        synthesizer.setOnReadyChanged(::onSynthesizerReady)
        collectJob = scope.launch {
            // drop(1): never speak whatever the store already held before we
            // subscribed (a stale retained message from an earlier foreground
            // must not be re-read on app start or reconnect).
            liveCoachStore.message
                .drop(1)
                .collect { response -> onCoachingMessage(response) }
        }
    }

    /** Stops observing; a later [start] begins fresh. */
    fun stop() {
        collectJob?.cancel()
        collectJob = null
    }

    /** Stops any utterance currently being read. */
    fun stopSpeaking() {
        runCatching { synthesizer.stop() }
    }

    /** Stops observation, stops speech, and releases the engine (idempotent). */
    fun release() {
        stop()
        stopSpeaking()
        runCatching { synthesizer.release() }
    }

    private fun onCoachingMessage(response: CoachResponse?) {
        if (response == null || !enabled) return
        when (val decision = gate.decide(response)) {
            is CoachingSpeechGate.Decision.Silent -> Unit
            is CoachingSpeechGate.Decision.Speak -> deliver(decision.text)
        }
    }

    private fun deliver(text: String) {
        if (synthesizerReady) {
            // flushPrevious = true: a newer message replaces the older one
            // still being read rather than queueing behind it.
            runCatching { synthesizer.speak(text, flushPrevious = true) }
        } else {
            // Latest wins: if several fresh messages arrive while the engine is
            // still binding, only the most recent is kept for when it is ready.
            pendingText = text
        }
    }

    private fun onSynthesizerReady(ready: Boolean) {
        synthesizerReady = ready
        if (!ready) return
        val pending = pendingText
        if (pending != null && enabled) {
            pendingText = null
            runCatching { synthesizer.speak(pending, flushPrevious = true) }
        }
    }
}
