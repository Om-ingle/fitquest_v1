package com.example.mobileapp.core.network

import com.example.mobileapp.core.auth.AuthInterceptor
import com.example.mobileapp.core.auth.TokenRefreshAuthenticator
import java.net.ProtocolException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * M11 (F-04) — the coaching WebSocket handshake, asserted on the wire.
 *
 * The push channel used to identify its user with a `?user_id=` query parameter.
 * M11 removed that and the handshake now carries the same verified bearer token
 * every REST call does. These tests drive the REAL OkHttp WebSocket stack
 * against a real server and read the actual upgrade request, because the two
 * things that must hold — that the token is present in the header, and that it
 * is absent from the URL — are only observable in the bytes that were sent.
 *
 * Why the URL matters: a query string is written to every access log, proxy log
 * and crash report on the path, and a bearer token that leaks into a log is a
 * credential someone else can use until it expires. A header is not logged by
 * default, and an interceptor is the only thing that can put one there.
 */
class CoachingHandshakeAuthTest {

    private lateinit var server: MockWebServer
    private var client: OkHttpClient? = null

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        // Unlike a synchronous REST call, the WebSocket connect path really
        // does use OkHttp's dispatcher executor, so it is shut down rather than
        // leaked into the rest of the JVM's test run.
        runCatching { client?.dispatcher?.executorService?.shutdown() }
        server.shutdown()
    }

    /** The app's client: the bearer interceptor is the only source of identity. */
    private fun tokenClient(token: () -> String?): OkHttpClient =
        OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor(token))
            .build()
            .also { client = it }

    private fun coachingUrl(): String = coachingWsUrl(server.url("/").toString())

    /** Accepts one upgrade, counting it. */
    private fun acceptUpgrade(opened: CountDownLatch) {
        server.enqueue(
            MockResponse().withWebSocketUpgrade(
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        opened.countDown()
                    }
                }
            )
        )
    }

    private class RecordingCallbacks(private val opened: CountDownLatch) : CoachingSocketCallbacks {
        override fun onOpen() = opened.countDown()
        override fun onMessage(text: String) = Unit
        override fun onClosed(code: Int, reason: String) = Unit
        override fun onFailure(cause: Throwable) = Unit
    }

    private fun connect(wsClient: OkHttpClient) {
        OkHttpCoachingSocketFactory(wsClient).connect(coachingUrl(), RecordingCallbacks(CountDownLatch(1)))
    }

    private fun nextRequest(): RecordedRequest? = server.takeRequest(5, TimeUnit.SECONDS)

    /**
     * The backend's rule, on the server side: no bearer, no upgrade.
     *
     * The FitQuest backend refuses before `accept()`, which a real client sees
     * as a rejected upgrade rather than a 1008 close — so that is what this
     * serves, and the client must react to the framing it really gets.
     */
    private fun requireBearer(opened: CountDownLatch) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (request.getHeader("Authorization") == null) {
                    MockResponse().setResponseCode(403)
                        .setBody("""{"detail":"Not authenticated"}""")
                } else {
                    MockResponse().withWebSocketUpgrade(
                        object : WebSocketListener() {
                            override fun onOpen(webSocket: WebSocket, response: Response) {
                                opened.countDown()
                            }
                        }
                    )
                }
        }
    }

    @Test
    fun `the handshake carries the session bearer token`() {
        val upgrade = CountDownLatch(1)
        val factory = CountDownLatch(1)
        acceptUpgrade(upgrade)
        OkHttpCoachingSocketFactory(tokenClient { "access-token-1" })
            .connect(coachingUrl(), RecordingCallbacks(factory))

        val request = nextRequest()

        assertTrue("the upgrade never opened", upgrade.await(5, TimeUnit.SECONDS))
        assertTrue("the factory never reported the socket open", factory.await(5, TimeUnit.SECONDS))
        assertEquals("Bearer access-token-1", request?.getHeader("Authorization"))
        assertEquals("/api/v1/ws/coaching", request?.path)
    }

    @Test
    fun `the handshake names no user and puts no credential in the url`() {
        val upgrade = CountDownLatch(1)
        acceptUpgrade(upgrade)
        connect(tokenClient { "access-token-1" })

        val request = nextRequest()
        val url = request?.requestUrl.toString()

        // No query string at all — the structural guarantee that neither a
        // token nor a user id can be in one.
        assertNull(request?.requestUrl?.query)
        assertTrue("the url must not carry a token: $url", !url.contains("token", ignoreCase = true))
        assertTrue("the url must not name the user: $url", !url.contains("user_id", ignoreCase = true))
        assertTrue(url.endsWith("/api/v1/ws/coaching"))
        assertTrue(upgrade.await(5, TimeUnit.SECONDS))
    }

    @Test
    fun `a signed-out client presents no credential`() {
        // The handshake still goes out — the client does not decide who may
        // connect. The backend answers it with close code 1008, which the client
        // treats as terminal (see CoachingWsClientTest).
        val upgrade = CountDownLatch(1)
        acceptUpgrade(upgrade)
        connect(tokenClient { null })

        val request = nextRequest()

        assertNull(request?.getHeader("Authorization"))
        assertEquals("/api/v1/ws/coaching", request?.path)
        assertTrue(upgrade.await(5, TimeUnit.SECONDS))
    }

    @Test
    fun `a reconnect after a refresh presents the new token`() {
        // The interceptor reads the token at call time, so a socket that
        // reconnects after a token refresh authenticates with the new token
        // without any call site being rewired.
        val opened = CountDownLatch(2)
        var token: String? = "access-token-1"
        val wsClient = tokenClient { token }
        acceptUpgrade(opened)
        acceptUpgrade(opened)

        connect(wsClient)
        val first = nextRequest()

        token = "access-token-2" // as AuthSession.adopt would leave it
        connect(wsClient)
        val second = nextRequest()

        assertEquals("Bearer access-token-1", first?.getHeader("Authorization"))
        assertEquals("Bearer access-token-2", second?.getHeader("Authorization"))
        assertTrue("both upgrades should have opened", opened.await(5, TimeUnit.SECONDS))
    }

    @Test
    fun `a handshake rejected with 401 is retried with a refreshed token`() {
        // The push channel reconnects on its own for the life of the app, so it
        // will eventually reconnect holding an access token that has expired.
        // The handshake must refresh and retry exactly like a REST call, or the
        // user silently loses live coaching every time their token ages out.
        val upgrade = CountDownLatch(1)
        var refreshes = 0
        val wsClient = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor { "expired" })
            .authenticator(TokenRefreshAuthenticator(refresh = { refreshes++; "fresh" }))
            .build()
        client = wsClient
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Invalid token"}"""))
        acceptUpgrade(upgrade)

        connect(wsClient)

        val rejected = nextRequest()
        val accepted = nextRequest()
        assertTrue("the retried handshake never opened", upgrade.await(5, TimeUnit.SECONDS))
        assertEquals("Bearer expired", rejected?.getHeader("Authorization"))
        assertEquals("Bearer fresh", accepted?.getHeader("Authorization"))
        assertEquals(1, refreshes)
    }

    @Test
    fun `a server that requires the token accepts an authenticated handshake`() {
        val opened = CountDownLatch(1)
        requireBearer(opened)
        val factory = CountDownLatch(1)

        OkHttpCoachingSocketFactory(tokenClient { "access-token-1" })
            .connect(coachingUrl(), RecordingCallbacks(factory))

        assertTrue("the authenticated handshake must be accepted", factory.await(5, TimeUnit.SECONDS))
        assertTrue(opened.await(5, TimeUnit.SECONDS))
        assertEquals("Bearer access-token-1", nextRequest()?.getHeader("Authorization"))
    }

    @Test
    fun `a server that requires the token refuses a signed-out handshake`() {
        // The end-to-end shape of "signed out means no push channel": the socket
        // is never accepted, and what the client sees is a failed handshake —
        // not a 1008 close, because the backend refuses before accept().
        val opened = CountDownLatch(1)
        requireBearer(opened)
        val failed = CountDownLatch(1)
        var failure: Throwable? = null

        OkHttpCoachingSocketFactory(tokenClient { null }).connect(
            coachingUrl(),
            object : CoachingSocketCallbacks {
                override fun onOpen() = Unit
                override fun onMessage(text: String) = Unit
                override fun onClosed(code: Int, reason: String) = Unit
                override fun onFailure(cause: Throwable) {
                    failure = cause
                    failed.countDown()
                }
            },
        )

        assertTrue("the refusal must surface as a failed handshake", failed.await(5, TimeUnit.SECONDS))
        assertEquals(false, opened.await(200, TimeUnit.MILLISECONDS))
        assertTrue(
            "expected OkHttp's rejected upgrade, got $failure",
            failure is ProtocolException,
        )
        // The request did go out — unauthenticated. The client does not decide
        // who may connect; the server does.
        assertNull(nextRequest()?.getHeader("Authorization"))
    }
}
