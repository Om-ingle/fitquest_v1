package com.example.mobileapp.core.network

import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/**
 * Real [CoachingSocketFactory] over OkHttp's WebSocket implementation
 * (M8.3B). OkHttp connects asynchronously and reports through a
 * [WebSocketListener]; this adapter only translates frames into the tiny
 * [CoachingSocketCallbacks] seam so [CoachingWsClient] stays testable without
 * OkHttp.
 */
class OkHttpCoachingSocketFactory(
    private val client: OkHttpClient,
) : CoachingSocketFactory {

    override fun connect(
        url: String,
        callbacks: CoachingSocketCallbacks,
    ): CoachingSocket {
        val request = Request.Builder().url(url).build()
        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                callbacks.onOpen()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                callbacks.onMessage(text)
            }

            // Binary frames are never sent by the push channel; ignore them.

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                callbacks.onClosed(code, reason)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                callbacks.onFailure(t)
            }
        }

        val webSocket = client.newWebSocket(request, listener)
        return object : CoachingSocket {
            override fun close(code: Int, reason: String) {
                // Best-effort: close() is already safe to call on a closed /
                // still-connecting socket (it aborts the connect attempt).
                runCatching { webSocket.close(code, reason) }
            }
        }
    }
}

/**
 * Derives the coaching WebSocket URL from the existing REST base URL:
 * `http` -> `ws`, `https` -> `wss`, preserving host/port (and any base path),
 * then appends the M8.2 endpoint path `/api/v1/ws/coaching`. Nothing is
 * hard-coded — the dev backend address comes from the same `BACKEND_BASE_URL`
 * the app already uses, so emulator (10.0.2.2) and physical-device (LAN IP)
 * builds both work and a release HTTPS backend maps to `wss`.
 *
 * OkHttp's [HttpUrl] only accepts `http`/`https` schemes, so it is used here
 * purely to parse/validate the base URL and the ws/wss string is assembled by
 * hand rather than through a scheme-changing builder.
 *
 * No `?user_id` is sent: the backend resolves a missing identity to the same
 * fixed dev user every REST call already acts as, exactly mirroring the
 * app's no-auth dev identity.
 */
fun coachingWsUrl(baseUrl: String): String {
    val httpUrl = baseUrl.toHttpUrl() // validates http(s) base + normalizes host
    val scheme = if (httpUrl.isHttps) "wss" else "ws"
    return buildString {
        append(scheme).append("://").append(httpUrl.host)
        val defaultPort = if (httpUrl.isHttps) 443 else 80
        if (httpUrl.port != defaultPort) append(':').append(httpUrl.port)
        // Preserve any base path (usually empty) before the endpoint.
        append(httpUrl.encodedPath.trimEnd('/'))
        append(WS_COACHING_ENDPOINT)
        httpUrl.encodedQuery?.let { append('?').append(it) }
    }
}

private const val WS_COACHING_ENDPOINT = "/api/v1/ws/coaching"
