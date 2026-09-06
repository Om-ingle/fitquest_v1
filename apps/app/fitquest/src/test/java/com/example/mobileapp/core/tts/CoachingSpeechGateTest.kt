package com.example.mobileapp.core.tts

import com.example.mobileapp.core.network.models.CoachResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M8.4 — the pure speech gate. Decides which incoming [CoachResponse] is a
 * genuinely NEW coaching message to read aloud (bounded in-memory dedupe on
 * context_fingerprint + content, no DB persistence), and produces the
 * TTS-friendly text. No android classes involved — fully JVM-testable.
 */
class CoachingSpeechGateTest {

    private fun response(
        message: String,
        fingerprint: String = "fix-e-v1:abc123",
        generatedAt: String = "2026-09-06T10:00:00.000000",
    ) = CoachResponse(
        generated_at = generatedAt,
        message = message,
        context_fingerprint = fingerprint
    )

    @Test
    fun `a new message is speakable`() {
        val gate = CoachingSpeechGate()

        val decision = gate.decide(response(message = "Nice run! Keep it up."))

        assertTrue(decision is CoachingSpeechGate.Decision.Speak)
        assertEquals(
            "Nice run! Keep it up.",
            (decision as CoachingSpeechGate.Decision.Speak).text
        )
    }

    @Test
    fun `a redelivered duplicate is silent even as a different instance`() {
        val gate = CoachingSpeechGate()
        // Different generated_at => a distinct object the StateFlow WOULD emit,
        // so this genuinely exercises the gate (not just flow equality).
        gate.decide(response(message = "Take a recovery walk.", generatedAt = "2026-09-06T10:00:00.000000"))
        val duplicate = gate.decide(
            response(message = "Take a recovery walk.", generatedAt = "2026-09-06T10:01:00.000000")
        )

        assertTrue(duplicate is CoachingSpeechGate.Decision.Silent)
    }

    @Test
    fun `different content is spoken even back to back`() {
        val gate = CoachingSpeechGate()
        gate.decide(response(message = "Message one."))

        val second = gate.decide(response(message = "Message two, brand new advice."))

        assertTrue(second is CoachingSpeechGate.Decision.Speak)
        assertEquals(
            "Message two, brand new advice.",
            (second as CoachingSpeechGate.Decision.Speak).text
        )
    }

    @Test
    fun `identical content under a new context fingerprint is genuinely new`() {
        val gate = CoachingSpeechGate()
        gate.decide(response(message = "Aim for one short walk today.", fingerprint = "fix-e-v1:ctxA"))

        val newContext = gate.decide(
            response(message = "Aim for one short walk today.", fingerprint = "fix-e-v1:ctxB")
        )

        assertTrue(newContext is CoachingSpeechGate.Decision.Speak)
    }

    @Test
    fun `blank messages are silent and never recorded`() {
        val gate = CoachingSpeechGate()
        val blank = CoachResponse(message = "   \n  ")
        val empty = CoachResponse(message = null)

        assertTrue(gate.decide(blank) is CoachingSpeechGate.Decision.Silent)
        assertTrue(gate.decide(empty) is CoachingSpeechGate.Decision.Silent)
    }

    @Test
    fun `spoken text is normalized for reading aloud`() {
        val gate = CoachingSpeechGate()
        val decision = gate.decide(
            response(
                message = "You're at **35%** of your goal…\n\nTry a `short` walk with [a link](https://x.y)."
            )
        )

        assertEquals(
            "You're at 35% of your goal. Try a short walk with a link.",
            (decision as CoachingSpeechGate.Decision.Speak).text
        )
    }

    @Test
    fun `dedupe history is bounded not unbounded`() {
        val gate = CoachingSpeechGate(recentCapacity = 3)
        val texts = listOf("a", "b", "c", "d")
        texts.forEach { gate.decide(response(message = it)) }

        // The oldest key ("a") was evicted when "d" arrived, so a re-delivery
        // of "a" is treated as new again — memory stays small.
        val replayOldest = gate.decide(response(message = "a", generatedAt = "2026-09-06T11:00:00.000000"))

        assertTrue(replayOldest is CoachingSpeechGate.Decision.Speak)
    }

    @Test
    fun `decide never throws on degenerate inputs`() {
        val gate = CoachingSpeechGate(recentCapacity = 1)
        listOf(
            CoachResponse(),
            CoachResponse(message = ""),
            CoachResponse(message = "x", context_fingerprint = ""),
        ).forEach { gate.decide(it) }
        gate.decide(response(message = "x"))
    }
}
