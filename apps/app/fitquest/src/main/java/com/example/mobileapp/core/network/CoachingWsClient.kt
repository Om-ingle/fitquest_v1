package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse
import com.google.gson.Gson
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicInteger

/**
 * M8.3B — real-time coaching WebSocket client (backend `/api/v1/ws/coaching`).
 *
 * The client only ever RECEIVES. The server pushes two envelope types (M8.2
 * raw triggers + M8.3A AI coaching messages); REST stays the request channel
 * and `GET /api/v1/coach` is untouched. It is deliberately small and never
 * crashes: unknown/malformed frames are ignored (logged), and any socket
 * failure just leaves [LiveCoachStore] empty so the app keeps working on the
 * normal pull/offline path.
 *
 * Transport seam: the client talks to a [CoachingSocketFactory] — a tiny
 * interface with a real OkHttp implementation
 * ([OkHttpCoachingSocketFactory]) and a scripted fake in unit tests, so no
 * test touches a network. Callbacks arrive on the transport's own threads and
 * are forwarded thread-safely (parsing is stateless; publishing goes through
 * [LiveCoachStore]'s thread-safe StateFlow; completion of a
 * [CompletableDeferred] resumes the owner coroutine on its own dispatcher).
 *
 * Lifecycle: [connect] / [disconnect] are idempotent. One logical connection
 * exists per process (Koin singleton); MainActivity calls connect() on
 * onStart and disconnect() on onStop, so tab navigation inside the activity
 * never duplicates or drops it, and going to the background closes it.
 *
 * Reconnect: after an unexpected close/failure the client retries with a
 * conservative, capped exponential backoff ([retryDelayMs]) up to
 * [maxReconnectAttempts] consecutive failures, then stays disconnected until
 * the next [connect]. A deliberate [disconnect] cancels the run and never
 * reconnects. Coalescing/cooldown of pushes is a backend concern (M8.3A);
 * this client only needs to stay alive to receive them.
 */
class CoachingWsClient(
    private val url: String,
    private val socketFactory: CoachingSocketFactory,
    private val messageParser: (String) -> CoachingWsMessage,
    private val onLiveCoach: (CoachResponse) -> Unit,
    private val onStatusChanged: (CoachingWsStatus) -> Unit = {},
    private val scope: CoroutineScope,
    private val initialBackoffMs: Long = DEFAULT_INITIAL_BACKOFF_MS,
    private val backoffMultiplier: Long = DEFAULT_BACKOFF_MULTIPLIER,
    private val maxBackoffMs: Long = DEFAULT_MAX_BACKOFF_MS,
    private val maxReconnectAttempts: Int = DEFAULT_MAX_RECONNECT_ATTEMPTS,
    private val sleeper: suspend (Long) -> Unit = { delay(it) },
) {

    @Volatile
    private var running = false

    @Volatile
    private var runJob: Job? = null

    private val attempts = AtomicInteger(0)

    /** Exponential backoff with a hard cap — pure and unit-testable. */
    fun retryDelayMs(attempt: Int): Long {
        var delayMs = initialBackoffMs
        var steps = attempt
        while (steps > 1 && delayMs < maxBackoffMs) {
            delayMs *= backoffMultiplier
            steps--
        }
        return if (delayMs > maxBackoffMs) maxBackoffMs else delayMs
    }

    /** Start (or restart) the receive/reconnect loop. No-op if already running. */
    fun connect() {
        synchronized(stateLock) {
            if (running) return
            running = true
            attempts.set(0)
            runJob = scope.launch { runLoop() }
        }
    }

    /** Stop the loop and close the socket. No reconnect is scheduled. */
    fun disconnect() {
        val job: Job?
        synchronized(stateLock) {
            running = false
            job = runJob
            runJob = null
        }
        job?.cancel()
        onStatusChanged(CoachingWsStatus.IDLE)
    }

    /**
     * Single owner of the connection: open, receive, and on an unexpected
     * terminal event back off and retry up to [maxReconnectAttempts]. Parked
     * at a [CompletableDeferred] while a healthy socket stays open. Tests
     * drive this directly (runBlocking + a scripted factory + a no-op
     * [sleeper]) for deterministic reconnect assertions.
     */
    internal suspend fun runLoop() {
        var socket: CoachingSocket? = null
        try {
            while (running) {
                onStatusChanged(CoachingWsStatus.CONNECTING)
                val terminal = CompletableDeferred<TerminalOutcome>()
                val callbacks = connectionCallbacks(terminal)
                socket = try {
                    socketFactory.connect(url, callbacks)
                } catch (t: CancellationException) {
                    throw t
                } catch (t: Throwable) {
                    // A factory that throws is treated as a failed connect, so
                    // the backoff budget applies instead of a hard crash.
                    callbacks.onFailure(t)
                    null
                }
                terminal.await()
                socket = null
                if (!running) break

                val failures = attempts.incrementAndGet()
                if (failures > maxReconnectAttempts) {
                    // Bounded retries exhausted — stay disconnected until the
                    // next explicit connect() (e.g. the next foreground).
                    running = false
                    onStatusChanged(CoachingWsStatus.DISCONNECTED)
                    break
                }
                sleeper(retryDelayMs(failures))
            }
        } finally {
            try {
                socket?.close(CLOSE_NORMAL, "client shutdown")
            } catch (_: Throwable) {
                // Closing is best-effort; the socket may already be gone.
            }
        }
    }

    private fun connectionCallbacks(
        terminal: CompletableDeferred<TerminalOutcome>
    ): CoachingSocketCallbacks = object : CoachingSocketCallbacks {
        override fun onOpen() {
            if (!running) return
            // A successful connection is a liveness reset for the backoff
            // budget: a healthy socket that later drops gets a fresh window.
            attempts.set(0)
            onStatusChanged(CoachingWsStatus.CONNECTED)
        }

        override fun onMessage(text: String) {
            if (!running) return
            attempts.set(0)
            when (val message = messageParser(text)) {
                is CoachingWsMessage.LiveCoach -> onLiveCoach(message.response)
                CoachingWsMessage.Ignored,
                CoachingWsMessage.Malformed -> Unit // never publish unusable content
            }
        }

        override fun onClosed(code: Int, reason: String) {
            terminal.complete(TerminalOutcome.Closed)
        }

        override fun onFailure(cause: Throwable) {
            terminal.complete(TerminalOutcome.Failed)
        }
    }

    private enum class TerminalOutcome { Closed, Failed }

    private companion object {
        const val CLOSE_NORMAL = 1000
        const val DEFAULT_INITIAL_BACKOFF_MS = 1_000L
        const val DEFAULT_BACKOFF_MULTIPLIER = 2L
        const val DEFAULT_MAX_BACKOFF_MS = 30_000L
        const val DEFAULT_MAX_RECONNECT_ATTEMPTS = 5
    }
}

/**
 * Connection health, for logging/tests. Not surfaced in the Home UI — a dead
 * socket degrades silently to the pull/offline path.
 */
enum class CoachingWsStatus { IDLE, CONNECTING, CONNECTED, DISCONNECTED }

/** Guard for the [CoachingWsClient] state (connect/disconnect idempotency). */
private val stateLock = Any()

// ── Minimal injectable transport seam ────────────────────────────────────────

/** A live outbound handle returned by [CoachingSocketFactory.connect]. */
interface CoachingSocket {
    fun close(code: Int, reason: String)
}

/** Sink a socket reports into (invoked on the transport's own threads). */
interface CoachingSocketCallbacks {
    fun onOpen()
    fun onMessage(text: String)
    fun onClosed(code: Int, reason: String)
    fun onFailure(cause: Throwable)
}

/**
 * Very small seam so [CoachingWsClient] is fully unit-testable with a fake
 * (no network). The real implementation is [OkHttpCoachingSocketFactory].
 */
interface CoachingSocketFactory {
    /** Begin connecting; returns immediately. The outcome arrives via callbacks. */
    fun connect(url: String, callbacks: CoachingSocketCallbacks): CoachingSocket
}

// ── Message parsing ──────────────────────────────────────────────────────────

/**
 * Result of decoding one inbound WebSocket frame. Only a [LiveCoach] carries
 * content the UI can show; everything else is safely ignored.
 */
sealed interface CoachingWsMessage {
    /** A valid `coaching_message` whose coach maps to the existing
     *  [CoachResponse] and passes the same shape validation the pull fetcher
     *  uses (message non-blank, recommendation present). */
    data class LiveCoach(val response: CoachResponse) : CoachingWsMessage

    /** Valid JSON but not a publishable coaching message: a raw M8.2
     *  `coaching_trigger`, an unknown type, or a coaching_message whose coach
     *  violates the shape. Ignored by the UI for now. */
    object Ignored : CoachingWsMessage

    /** The frame could not be parsed as JSON at all. Ignored; never a crash. */
    object Malformed : CoachingWsMessage
}

/**
 * Decodes the stable server envelope(s) into [CoachingWsMessage]. The outer
 * DTO models ONLY what M8.3B needs — `type` plus the existing `coach`
 * [CoachResponse]; the raw `trigger` object and any future fields are left
 * unmodeled (Gson ignores them), so no second coaching schema is invented.
 */
object CoachingWsMessageParser {

    /** Backend M8.3A envelope type carrying the AI message. */
    const val TYPE_COACHING_MESSAGE = "coaching_message"

    private val gson = Gson()

    private class EnvelopeDto(
        val type: String? = null,
        val coach: CoachResponse? = null,
    )

    fun parse(text: String): CoachingWsMessage {
        if (text.isBlank()) return CoachingWsMessage.Malformed
        val envelope = try {
            gson.fromJson(text, EnvelopeDto::class.java)
        } catch (e: Exception) {
            return CoachingWsMessage.Malformed
        } ?: return CoachingWsMessage.Malformed

        if (envelope.type?.trim() != TYPE_COACHING_MESSAGE) {
            return CoachingWsMessage.Ignored
        }
        val coach = envelope.coach ?: return CoachingWsMessage.Ignored
        // Same validation as CoachFetcher: never surface an unusable response.
        if (coach.message.isNullOrBlank() || coach.recommendation == null) {
            return CoachingWsMessage.Ignored
        }
        return CoachingWsMessage.LiveCoach(coach)
    }
}
