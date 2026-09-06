package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.network.models.CoachRetrievalInfo
import com.example.mobileapp.core.network.models.FitnessContextResponse
import com.example.mobileapp.core.network.models.Recommendation
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M8.3B focused JVM tests. No network: message parsing is exercised on raw
 * JSON text and the client is driven over a scripted in-memory
 * [FakeSocketFactory] with an Unconfined scope and a no-op backoff sleeper, so
 * connect/reconnect/disconnect are fully deterministic on the test thread.
 */
class CoachingWsClientTest {

    // ── Fixtures ────────────────────────────────────────────────────────────

    private val userId = "00000000-0000-0000-0000-000000000001"

    private val context = FitnessContextResponse(
        user_id = userId,
        total_lifetime_steps = 1000,
        hexes_owned = 1,
        recent_captures_7d = 1,
        last_capture_at = null,
        total_defense_steps = 0
    )

    private val recommendation = Recommendation(
        type = "RECOVERY",
        title = "Nice run — recover well",
        description = "You just finished 1,000 steps.",
        target_metric = "steps",
        target_value = 2000,
        difficulty = "easy",
        reason_code = "RUN_DONE",
        reason = "total_lifetime_steps=1000"
    )

    private fun coachResponse(message: String = "Nice run! Keep the momentum.") = CoachResponse(
        generated_at = "2026-09-06T10:20:05.000000",
        message = message,
        grounded = true,
        context = context,
        recommendation = recommendation,
        retrieval = CoachRetrievalInfo(retrieved_count = 3),
        context_fingerprint = "fix-e-v1:abc123",
        cached = false
    )

    /** A backend-shaped coaching_message envelope with the real CoachResponse JSON. */
    private fun coachingMessageJson(message: String = "Nice run! Keep the momentum."): String = """
        {
          "type": "coaching_message",
          "trigger": {
            "trigger_type": "workout_completed",
            "user_id": "$userId",
            "occurred_at": "2026-09-06T10:20:00.000000Z",
            "dedupe_key": "run-abc",
            "event_id": "run-abc",
            "payload": {"run_id": "run-abc"}
          },
          "coach": {
            "generated_at": "2026-09-06T10:20:05.000000",
            "message": "$message",
            "grounded": true,
            "context": {
              "user_id": "$userId",
              "total_lifetime_steps": 1000,
              "hexes_owned": 1,
              "recent_captures_7d": 1,
              "total_defense_steps": 0
            },
            "recommendation": {
              "type": "RECOVERY",
              "title": "Nice run — recover well",
              "description": "You just finished 1,000 steps.",
              "target_metric": "steps",
              "target_value": 2000,
              "difficulty": "easy",
              "reason_code": "RUN_DONE",
              "reason": "total_lifetime_steps=1000"
            },
            "retrieval": {"retrieved_count": 3},
            "context_fingerprint": "fix-e-v1:abc123",
            "cached": false
          }
        }
    """.trimIndent()

    private class FakeSocket(
        private val callbacks: CoachingSocketCallbacks,
    ) : CoachingSocket {
        var closeCalls = 0
        var opened = false
            private set

        fun open() {
            opened = true
            callbacks.onOpen()
        }

        fun deliver(text: String) = callbacks.onMessage(text)

        fun fail() = callbacks.onFailure(IOException("socket failed"))

        fun closeFromServer() = callbacks.onClosed(1001, "server going away")

        override fun close(code: Int, reason: String) {
            closeCalls++
            callbacks.onClosed(code, reason)
        }
    }

    private class FakeSocketFactory : CoachingSocketFactory {
        val sockets = mutableListOf<FakeSocket>()
        val scripts = ArrayDeque<(FakeSocket) -> Unit>()
        var connectCount = 0
            private set

        fun onNextConnect(script: (FakeSocket) -> Unit) {
            scripts.addLast(script)
        }

        override fun connect(url: String, callbacks: CoachingSocketCallbacks): CoachingSocket {
            connectCount++
            val socket = FakeSocket(callbacks)
            sockets += socket
            // A script drives this connection (fail/close), otherwise default
            // to opening it and leaving it healthy so the loop parks.
            val script = scripts.removeFirstOrNull()
            if (script != null) script(socket) else socket.open()
            return socket
        }
    }

    private class RecordingStore {
        val values = mutableListOf<CoachResponse>()
        val latest: CoachResponse? get() = values.lastOrNull()

        fun publish(response: CoachResponse) {
            values += response
        }
    }

    private fun client(
        factory: FakeSocketFactory,
        store: RecordingStore,
        maxReconnectAttempts: Int = 5,
    ): CoachingWsClient = CoachingWsClient(
        url = "ws://test/api/v1/ws/coaching",
        socketFactory = factory,
        messageParser = CoachingWsMessageParser::parse,
        onLiveCoach = store::publish,
        onStatusChanged = {},
        scope = CoroutineScope(Dispatchers.Unconfined),
        maxReconnectAttempts = maxReconnectAttempts,
        sleeper = { /* no-op: deterministic tests without real waits */ },
    )

    // ── 1. Valid coaching_message decoding ───────────────────────────────────

    @Test
    fun `valid coaching_message decodes to a live coach push`() {
        val result = CoachingWsMessageParser.parse(coachingMessageJson())

        assertTrue(result is CoachingWsMessage.LiveCoach)
        val live = result as CoachingWsMessage.LiveCoach
        assertEquals("Nice run! Keep the momentum.", live.response.message)
        assertEquals(true, live.response.grounded)
    }

    // ── 2. Existing CoachResponse fields map correctly ───────────────────────

    @Test
    fun `existing coach response fields map onto the reused dto`() {
        val result = CoachingWsMessageParser.parse(coachingMessageJson())

        val mapped = (result as CoachingWsMessage.LiveCoach).response
        assertEquals(coachResponse(), mapped)
        assertEquals("2026-09-06T10:20:05.000000", mapped.generated_at)
        assertEquals(context, mapped.context)
        assertEquals(recommendation, mapped.recommendation)
        assertEquals(3, mapped.retrieval?.retrieved_count)
        assertEquals("fix-e-v1:abc123", mapped.context_fingerprint)
        assertEquals(false, mapped.cached)
    }

    // ── 3. coaching_trigger is handled safely ────────────────────────────────

    @Test
    fun `raw coaching_trigger is ignored not published`() {
        val triggerJson = """
            {"type":"coaching_trigger","trigger":{"trigger_type":"workout_completed","user_id":"$userId"}}
        """.trimIndent()

        val result = CoachingWsMessageParser.parse(triggerJson)

        assertTrue(result is CoachingWsMessage.Ignored)
    }

    // ── 4. Unknown message type is ignored ───────────────────────────────────

    @Test
    fun `unknown message type is ignored`() {
        val unknownJson = """{"type":"some_future_event","payload":{}}"""

        val result = CoachingWsMessageParser.parse(unknownJson)

        assertTrue(result is CoachingWsMessage.Ignored)
    }

    // ── 5. Malformed message does not crash ──────────────────────────────────

    @Test
    fun `malformed message is reported not a crash`() {
        assertTrue(CoachingWsMessageParser.parse("not json at all") is CoachingWsMessage.Malformed)
        assertTrue(CoachingWsMessageParser.parse("") is CoachingWsMessage.Malformed)
        // coaching_message that violates the required shape -> ignored, not published
        val noMessage = """{"type":"coaching_message","coach":{"grounded":true}}"""
        assertTrue(CoachingWsMessageParser.parse(noMessage) is CoachingWsMessage.Ignored)
    }

    // ── 6. Coaching message updates live coaching state ──────────────────────

    @Test
    fun `coaching message updates the live store`() {
        val factory = FakeSocketFactory()
        val store = RecordingStore()
        val ws = client(factory, store)
        ws.connect()

        factory.sockets.single().deliver(coachingMessageJson())

        assertEquals("Nice run! Keep the momentum.", store.latest?.message)
        ws.disconnect()
    }

    @Test
    fun `later valid message replaces the previous live one`() {
        val factory = FakeSocketFactory()
        val store = RecordingStore()
        val ws = client(factory, store)
        ws.connect()
        val socket = factory.sockets.single()

        socket.deliver(coachingMessageJson("first push"))
        socket.deliver(coachingMessageJson("second push"))

        assertEquals(listOf("first push", "second push"), store.values.map { it.message })
        ws.disconnect()
    }

    @Test
    fun `trigger unknown and malformed frames never touch the live store`() {
        val factory = FakeSocketFactory()
        val store = RecordingStore()
        val ws = client(factory, store)
        ws.connect()
        val socket = factory.sockets.single()

        socket.deliver(coachingMessageJson("real advice"))
        socket.deliver("""{"type":"coaching_trigger","trigger":{}}""")
        socket.deliver("""{"type":"future_event"}""")
        socket.deliver("utter garbage not json")

        // Only the genuine coaching_message was published, and the client is
        // still alive (subsequent real frames keep flowing).
        assertEquals(listOf("real advice"), store.values.map { it.message })
        socket.deliver(coachingMessageJson("still alive"))
        assertEquals(listOf("real advice", "still alive"), store.values.map { it.message })
        ws.disconnect()
    }

    // ── 7. Push response does not corrupt the pull CoachCache ────────────────
    // (covered in LiveCoachStoreTest — stores are independent objects)

    // ── 8. Duplicate connect does not open a second logical connection ───────

    @Test
    fun `duplicate connect calls keep one logical connection`() {
        val factory = FakeSocketFactory()
        val ws = client(factory, RecordingStore())
        ws.connect()
        ws.connect()
        ws.connect()

        assertEquals(1, factory.connectCount)
        ws.disconnect()
    }

    // ── 9. Disconnect cleanup ────────────────────────────────────────────────

    @Test
    fun `disconnect closes the socket and stops further delivery`() {
        val factory = FakeSocketFactory()
        val store = RecordingStore()
        val ws = client(factory, store)
        ws.connect()
        val socket = factory.sockets.single()
        socket.deliver(coachingMessageJson("before disconnect"))
        assertEquals(1, store.values.size)

        ws.disconnect()

        assertTrue("the socket must be closed on disconnect", socket.closeCalls > 0)
        // A late frame from the dead socket must be ignored (running == false).
        socket.deliver(coachingMessageJson("after disconnect"))
        assertEquals(1, store.values.size)
        // And no reconnect is attempted after a deliberate disconnect.
        assertEquals(1, factory.connectCount)
    }

    // ── 10. Reconnect / backoff behavior ─────────────────────────────────────

    @Test
    fun `reconnects after a failed connection attempt until a socket opens`() {
        val factory = FakeSocketFactory()
        factory.onNextConnect { it.fail() } // first connection refused
        val ws = client(factory, RecordingStore())

        ws.connect()

        // Attempt 1 failed; the no-op sleeper let it immediately retry and
        // the second connection opened and stayed healthy.
        assertEquals(2, factory.connectCount)
        assertEquals(1, factory.sockets.count { !it.opened })
        assertEquals(1, factory.sockets.count { it.opened })
        ws.disconnect()
    }

    @Test
    fun `reconnects after an unexpected close of an established connection`() {
        val factory = FakeSocketFactory()
        val ws = client(factory, RecordingStore())
        ws.connect()
        assertEquals(1, factory.connectCount)

        // Healthy connection drops unexpectedly (server restart) -> retry.
        factory.sockets.single().closeFromServer()
        assertEquals(2, factory.connectCount)
        ws.disconnect()
    }

    @Test
    fun `backoff is capped and retries are bounded not an infinite loop`() {
        val factory = FakeSocketFactory()
        // Phase 1: all attempts allowed by the budget fail immediately.
        repeat(3) { factory.onNextConnect { it.fail() } }
        val ws = client(factory, RecordingStore(), maxReconnectAttempts = 2)

        ws.connect()

        // initial + 2 bounded retries, then it gives up quietly and stops.
        assertEquals(3, factory.connectCount)
        assertTrue(factory.sockets.all { !it.opened })

        // A later connect() starts a fresh budget and can succeed (running was
        // reset when the previous loop gave up — no infinite loop, but also no
        // permanent dead socket).
        ws.connect()
        assertEquals(4, factory.connectCount)
        assertEquals(1, factory.sockets.count { it.opened })
        ws.disconnect()
    }

    @Test
    fun `exponential backoff never exceeds the cap`() {
        val ws = client(FakeSocketFactory(), RecordingStore())
        assertEquals(1000L, ws.retryDelayMs(1))
        assertEquals(2000L, ws.retryDelayMs(2))
        assertEquals(4000L, ws.retryDelayMs(3))
        // 1s * 2^9 would be 512s — the 30s cap wins.
        assertEquals(30_000L, ws.retryDelayMs(10))
    }

    // ── 11. WebSocket failure never affects the pull CoachFetcher ────────────

    @Test
    fun `a dead websocket leaves CoachFetcher fully usable`() {
        val failing = FakeSocketFactory()
        repeat(6) { failing.onNextConnect { it.fail() } }
        val store = RecordingStore()
        val ws = client(failing, store, maxReconnectAttempts = 1)
        ws.connect() // WS gives up: store stays empty
        assertNull(store.latest)

        // The pull fetcher is an independent object: a normal fetch still works.
        val api = FakePullApi { coachResponse() }
        val outcome = kotlinx.coroutines.runBlocking { CoachFetcher(api).fetchCoachMessage() }
        assertTrue(outcome is CoachFetcher.Outcome.Success)
        assertEquals("Nice run! Keep the momentum.", (outcome as CoachFetcher.Outcome.Success).response.message)
        ws.disconnect()
    }

    // ── Endpoint derivation ──────────────────────────────────────────────────

    @Test
    fun `ws url derives scheme and appends the coaching endpoint`() {
        assertEquals(
            "ws://10.0.2.2:8000/api/v1/ws/coaching",
            coachingWsUrl("http://10.0.2.2:8000/")
        )
        assertEquals(
            "wss://fitquest.example.com/api/v1/ws/coaching",
            coachingWsUrl("https://fitquest.example.com/")
        )
    }

    private class FakePullApi(
        private val behavior: () -> CoachResponse,
    ) : FitQuestApi {
        override suspend fun getCoach(): CoachResponse = behavior()

        override suspend fun syncRunSession(
            payload: com.example.mobileapp.core.network.models.RunSyncPayload
        ) = throw UnsupportedOperationException()

        override suspend fun getMapViewport(
            minLat: Double, minLng: Double, maxLat: Double, maxLng: Double, zoomLevel: Double
        ) = throw UnsupportedOperationException()

        override suspend fun getLeaderboard(limit: Int) = throw UnsupportedOperationException()

        override suspend fun getRecommendations() = throw UnsupportedOperationException()
    }
}
