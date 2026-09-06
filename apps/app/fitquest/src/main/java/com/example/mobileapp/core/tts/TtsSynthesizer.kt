package com.example.mobileapp.core.tts

/**
 * M8.4 — seam over the platform text-to-speech engine, so the speech
 * coordinator ([CoachingSpeechController]) is fully JVM-testable. The real
 * implementation ([AndroidTtsSynthesizer]) wraps the native
 * `android.speech.tts.TextToSpeech`; unit tests drive a fake.
 *
 * Every method is deliberately best-effort: an implementation must never
 * throw to its caller (engine errors, a missing voice or a dead TTS service
 * are swallowed/logged, never a crash), and the app must keep running if TTS
 * is entirely unavailable.
 */
interface TtsSynthesizer {

    /**
     * Whether the underlying engine has finished binding and is able to speak
     * right now. Starts `false` (init is asynchronous) and flips to `true`
     * once the engine reports success.
     */
    val isReady: Boolean

    /**
     * Registers a callback invoked whenever [isReady] changes. Implementations
     * must also invoke it once with the current value on registration, so a
     * late subscriber (the coordinator starts after the engine) never waits
     * forever on an engine that already became ready.
     */
    fun setOnReadyChanged(listener: (Boolean) -> Unit)

    /**
     * Speaks [text]. When [flushPrevious] is `true` the current (or queued)
     * utterance is replaced first — this is how a newer coaching message cuts
     * off an older one still being read. Safe to call from any thread;
     * silently ignored while [isReady] is `false`.
     */
    fun speak(text: String, flushPrevious: Boolean)

    /** Stops any current utterance immediately. Safe to call at any time. */
    fun stop()

    /**
     * Releases the underlying engine (idempotent; safe to call repeatedly and
     * from any thread). Called when the app-scoped owner is torn down.
     */
    fun release()
}
