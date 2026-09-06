package com.example.mobileapp.core.tts

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/**
 * M8.4 — the real [TtsSynthesizer] over the native Android engine
 * (`android.speech.tts.TextToSpeech`). Native only: no cloud TTS, no API
 * keys, no paid/external dependency — exactly the SRS §15.3 MVP ("AI response
 * text -> Android TTS -> spoken coaching").
 *
 * Ownership & lifecycle:
 * - The [TextToSpeech] is created with the APPLICATION context (Koin resolves
 *   it via `androidContext()`), so it never holds an Activity and cannot leak
 *   a screen across navigation. It lives as long as the process, which is why
 *   navigation/recomposition never re-initialises it ([CoachingSpeechController]
 *   is the one Koin singleton that owns it).
 * - Init is asynchronous and some devices report ERROR before a later SUCCESS
 *   (the engine retries its service binding). [isReady] therefore only flips to
 *   `true` after a SUCCESS, and [setOnReadyChanged] is how the coordinator
 *   learns of the flip. A final ERROR simply leaves [isReady] false — the app
 *   is unaffected, nothing speaks, nothing crashes.
 * - Language: on SUCCESS we prefer the device default locale. LANG_MISSING_DATA
 *   / LANG_NOT_SUPPORTED is logged, not fatal — the engine falls back to an
 *   installed voice. If no voice at all can speak, [speak] is silently a no-op
 *   and the framework reports utterance errors, which we only log.
 *
 * Every framework call is wrapped in [runCatching] so a dead TTS service, a
 * missing voice or an init failure can never crash the caller (the WebSocket
 * live-coaching path, run sync and the UI all keep working without TTS).
 */
class AndroidTtsSynthesizer(
    context: Context,
) : TtsSynthesizer {

    private val appContext = context.applicationContext

    private val readyListener = AtomicReference<(Boolean) -> Unit>()
    @Volatile
    private var ready = false

    private var lastInitSucceeded = false
    private var configured = false
    private var released = false

    @Volatile
    private var engine: TextToSpeech? = null

    private val utteranceCounter = AtomicInteger(0)

    init {
        // onInit may arrive on a binder thread — or, for a broken engine,
        // synchronously INSIDE this constructor. Both orders are handled:
        // onInitStatus records the result; after the engine reference is
        // assigned we re-check and configure if a SUCCESS already happened.
        val created = try {
            TextToSpeech(appContext) { status -> onInitStatus(status) }
        } catch (t: Throwable) {
            Log.w(TAG, "TTS construction failed — coaching voice disabled", t)
            null
        }
        synchronized(this) {
            engine = created
            if (created != null && lastInitSucceeded) {
                configureAndMarkReadyLocked()
            }
        }
    }

    private fun onInitStatus(status: Int) {
        synchronized(this) {
            if (released) return
            if (status == TextToSpeech.SUCCESS) {
                lastInitSucceeded = true
                // Guard: if the constructor has already assigned the engine,
                // configure now; otherwise the constructor's final block will.
                if (engine != null) configureAndMarkReadyLocked()
            } else {
                // Not fatal: some engines retry binding and deliver a SUCCESS
                // later; if they never do, we simply never become ready.
                Log.w(TAG, "TTS init status=$status (not ready; not fatal)")
            }
        }
    }

    /** Must be called while holding [this]'s monitor, only after engine is set. */
    private fun configureAndMarkReadyLocked() {
        if (configured) {
            setReady(true)
            return
        }
        configured = true
        val t = engine ?: return
        // Prefer the device's own voice. Missing data on the requested locale
        // is not fatal — the engine falls back to an installed voice.
        val languageResult = runCatching { t.setLanguage(Locale.getDefault()) }
            .getOrDefault(TextToSpeech.LANG_AVAILABLE)
        if (languageResult == TextToSpeech.LANG_MISSING_DATA ||
            languageResult == TextToSpeech.LANG_NOT_SUPPORTED
        ) {
            Log.w(TAG, "Default language unavailable (result=$languageResult); engine will fall back")
        }
        runCatching { t.setOnUtteranceProgressListener(utteranceListener) }
        setReady(true)
    }

    private fun setReady(next: Boolean) {
        if (ready == next) return
        ready = next
        readyListener.get()?.invoke(next)
    }

    private val utteranceListener = object : UtteranceProgressListener() {
        override fun onStart(utteranceId: String?) {
            Log.d(TAG, "utterance started id=$utteranceId")
        }

        override fun onDone(utteranceId: String?) {
            Log.d(TAG, "utterance done id=$utteranceId")
        }

        override fun onError(utteranceId: String?) {
            Log.w(TAG, "utterance error id=$utteranceId")
        }

        @Deprecated("Deprecated in Java")
        override fun onError(utteranceId: String?, errorCode: Int) {
            Log.w(TAG, "utterance error id=$utteranceId code=$errorCode")
        }

        override fun onStop(utteranceId: String?, interrupted: Boolean) {
            Log.d(TAG, "utterance stopped id=$utteranceId interrupted=$interrupted")
        }
    }

    override val isReady: Boolean
        get() = ready

    override fun setOnReadyChanged(listener: (Boolean) -> Unit) {
        readyListener.set(listener)
        // Report current state immediately so a late subscriber never waits.
        listener(ready)
    }

    override fun speak(text: String, flushPrevious: Boolean) {
        val t = engine
        if (!ready || t == null || text.isBlank()) return
        val id = "fq-coach-${utteranceCounter.incrementAndGet()}"
        val params = Bundle().apply {
            putString(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, id)
        }
        val queueMode = if (flushPrevious) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
        val result = runCatching {
            t.speak(text, queueMode, params, id)
        }
        if (result.isFailure) {
            Log.w(TAG, "TTS speak failed", result.exceptionOrNull())
        } else {
            // First ~60 chars (single line) so device logs can confirm WHAT was
            // handed to the engine without dumping a full coaching message.
            val snippet = text.take(60).replace('\n', ' ')
            Log.d(TAG, "speak queued id=$id flush=$flushPrevious chars=${text.length} text=\"$snippet\"")
        }
    }

    override fun stop() {
        val t = engine ?: return
        runCatching { t.stop() }
            .onFailure { Log.w(TAG, "TTS stop failed", it) }
    }

    override fun release() {
        synchronized(this) {
            if (released) return
            released = true
        }
        readyListener.set(null)
        val t = engine
        engine = null
        if (t != null) {
            runCatching { t.shutdown() }
                .onFailure { Log.w(TAG, "TTS shutdown failed", it) }
        }
        setReady(false)
    }

    private companion object {
        const val TAG = "CoachingTts"
    }
}
