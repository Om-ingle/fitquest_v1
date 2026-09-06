package com.example.mobileapp.core.tts

import com.example.mobileapp.core.network.models.CoachResponse

/**
 * M8.4 — decides which incoming coaching message is genuinely NEW speech.
 *
 * The speech trigger is the existing M8.3B live slot: every new
 * `coaching_message` the WebSocket decodes is published to
 * `LiveCoachStore.message`, and the coordinator ([CoachingSpeechController])
 * asks this gate what to do. The gate is a pure, in-memory, bounded dedupe:
 *
 * - A message is speakable only if it carries real coaching text (the live
 *   parser already guarantees non-blank, but a defensive blank guard costs
 *   nothing and keeps the gate total).
 * - "Genuinely new" is decided on the CoachResponse identity we already have:
 *   the deterministic backend `context_fingerprint` (the digest of the context
 *   the message was grounded in) plus the normalized message content. A
 *   redelivered copy of the same message — a reconnect replay, a trigger
 *   fan-out duplicate, a backend retry that regenerates the same text — has the
 *   same key and is suppressed. A genuinely different message (new context
 *   and/or new content) speaks.
 * - The key set is SMALL and IN-MEMORY (a bounded recent-history ring, newest
 *   accepted, oldest evicted). TTS history is never persisted to the database;
 *   on process death the set is gone and the app forgets what it already said
 *   (correct: a brand-new process has no reason to treat its first push as old
 *   news, and LiveCoachStore is empty at cold start anyway).
 * - The text actually spoken is a light, TTS-only normalization of
 *   `response.message` (markdown ticks/bold/links and stray line breaks read
 *   awkwardly aloud). It is applied ONLY to the copy handed to the engine —
 *   the Home coach card keeps rendering the backend message byte-for-byte.
 */
class CoachingSpeechGate(
    private val recentCapacity: Int = 16,
) {

    private val recentOrder = ArrayDeque<Pair<String, String>>()
    private val recentKeys = HashSet<Pair<String, String>>()

    sealed interface Decision {
        /** Duplicate of something already spoken, or unspeakable content. */
        object Silent : Decision

        /** A genuinely new coaching message, with the text to read aloud. */
        data class Speak(val text: String) : Decision
    }

    /**
     * Classifies [response]. A `Speak` decision also records the message as
     * spoken, so a later redelivery of the same message returns `Silent`.
     * Calling this never throws.
     */
    fun decide(response: CoachResponse): Decision {
        val text = speechText(response) ?: return Decision.Silent
        val key = (response.context_fingerprint.orEmpty()) to text
        synchronized(this) {
            if (key in recentKeys) return Decision.Silent
            recentOrder.addLast(key)
            recentKeys.add(key)
            while (recentKeys.size > recentCapacity) {
                recentKeys.remove(recentOrder.removeFirst())
            }
        }
        return Decision.Speak(text)
    }

    /**
     * Returns the text that would be read aloud for [response], or `null` when
     * the message carries nothing speakable. Pure — used by [decide].
     */
    fun speechText(response: CoachResponse): String? {
        val raw = response.message?.trim().orEmpty()
        if (raw.isEmpty()) return null
        return normalizeForSpeech(raw)
    }

    private fun normalizeForSpeech(raw: String): String {
        var s = raw
            // Inline code backticks and **bold** markers should not be read.
            .replace("`", "")
            .replace("**", "")
        // Markdown links "[label](url)": reading a URL aloud is noise, so keep
        // only the label. Work on the whole match (no capturing-group access).
        s = MARKDOWN_LINK_REPLACER.replace(s) { m ->
            val label = m.value.substringAfter('[').substringBefore(']')
            label.ifEmpty { m.value }
        }
        // The unicode ellipsis is spoken inconsistently; make it a pause.
        s = s.replace('…', '.')
        // Any newline / tab / run of spaces becomes one space.
        s = s.replace(Regex("\\s+"), " ").trim()
        return s
    }

    private companion object {
        val MARKDOWN_LINK_REPLACER = Regex("\\[[^]]+]\\([^)]*\\)")
    }
}
