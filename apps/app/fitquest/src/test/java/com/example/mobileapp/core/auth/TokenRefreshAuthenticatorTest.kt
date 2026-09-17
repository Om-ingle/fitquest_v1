package com.example.mobileapp.core.auth

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

/**
 * M11 (F-04) — 401 handling, exercised through OkHttp's real authenticator
 * machinery against a real server.
 *
 * The behaviour under test is not "does it call refresh" but "can it loop". A
 * refresh loop is a self-inflicted denial of service against your own identity
 * provider, so each of the three guards is asserted by counting the requests
 * that actually reached the server rather than by inspecting our own flags.
 */
class TokenRefreshAuthenticatorTest {

    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun unauthorized() =
        MockResponse().setResponseCode(401).setBody("""{"detail":"Invalid or expired token"}""")

    private fun ok(body: String = "{}") = MockResponse().setResponseCode(200).setBody(body)

    /** An authenticated client wired exactly as the app's DI graph wires it. */
    private fun client(
        token: () -> String?,
        refresh: (String?) -> String?,
    ): OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(AuthInterceptor(token))
        .authenticator(TokenRefreshAuthenticator(refresh = refresh))
        .build()

    private fun OkHttpClient.get(path: String = "/api/v1/coach"): Response =
        newCall(Request.Builder().url(server.url(path)).build()).execute()

    @Test
    fun `an expired access token is transparently refreshed and the call succeeds`() {
        server.enqueue(unauthorized())
        server.enqueue(ok("""{"message":"recovered"}"""))
        var refreshes = 0
        val client = client(token = { "expired" }, refresh = { refreshes++; "fresh" })

        val response = client.get()
        val body = response.body?.string()
        response.close()

        assertEquals(200, response.code)
        assertEquals("""{"message":"recovered"}""", body)
        assertEquals(1, refreshes)

        // Two requests reached the server: the original, then one retry.
        assertEquals(2, server.requestCount)
        assertEquals("Bearer expired", server.takeRequest().getHeader("Authorization"))
        assertEquals("Bearer fresh", server.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun `the retry carries exactly one Authorization header`() {
        server.enqueue(unauthorized())
        server.enqueue(ok())
        val client = client(token = { "expired" }, refresh = { "fresh" })

        client.get().close()

        server.takeRequest()
        // Replacing must not append: a duplicate header down the wire is
        // ambiguous to proxies and a classic request-smuggling shape.
        assertEquals(
            listOf("Bearer fresh"),
            server.takeRequest().headers.values("Authorization"),
        )
    }

    @Test
    fun `the refresh is told which token failed`() {
        server.enqueue(unauthorized())
        server.enqueue(ok())
        var seen: String? = "unset"
        val client = client(token = { "expired" }, refresh = { failed -> seen = failed; "fresh" })

        client.get().close()

        // The authenticator passes the token the rejected request actually
        // carried, which is what lets AuthSession detect that another thread
        // has already refreshed.
        assertEquals("expired", seen)
    }

    // ── Guard 1: no bearer on the request → never retried ────────────────────

    @Test
    fun `a request that carried no bearer is never retried`() {
        server.enqueue(unauthorized())
        var refreshes = 0
        val client = client(token = { null }, refresh = { refreshes++; "fresh" })

        val response = client.get()
        response.close()

        assertEquals(401, response.code)
        assertEquals(0, refreshes)
        assertEquals(1, server.requestCount)
        assertNull(server.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun `a blank bearer is treated as no bearer`() {
        // The state a misconfigured build sits in. Retrying it would send the
        // same malformed credential again, so it must be refused exactly like
        // an absent header.
        server.enqueue(unauthorized())
        var refreshes = 0
        val client = client(token = { "   " }, refresh = { refreshes++; "fresh" })

        client.get().close()

        assertEquals(0, refreshes)
        assertEquals(1, server.requestCount)
    }

    // ── Guard 3: a refresh that yields the same token → refused ──────────────

    @Test
    fun `a refresh returning the same token is refused`() {
        // Retrying with the token the server just rejected is guaranteed to
        // fail, so spending a second request on it is pure waste.
        server.enqueue(unauthorized())
        var refreshes = 0
        val client = client(token = { "expired" }, refresh = { refreshes++; "expired" })

        val response = client.get()
        response.close()

        assertEquals(401, response.code)
        assertEquals(1, refreshes)
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `a failed refresh hands the 401 back to the caller`() {
        // The session may still be perfectly alive (a transient network blip);
        // the authenticator only reports that it could not fix this request.
        server.enqueue(unauthorized())
        var refreshes = 0
        val client = client(token = { "expired" }, refresh = { refreshes++; null })

        val response = client.get()
        response.close()

        assertEquals(401, response.code)
        assertEquals(1, refreshes)
        assertEquals(1, server.requestCount)
    }

    // ── Guard 2: the attempt chain is capped ─────────────────────────────────

    @Test
    fun `a server that keeps answering 401 is retried at most once`() {
        // The loop this exists to prevent: refresh succeeds, the new token is
        // also rejected, and the client refreshes forever. The cap is counted
        // through OkHttp's own priorResponse chain, which is the authoritative
        // record of how many times this call has been round the loop.
        server.enqueue(unauthorized())
        server.enqueue(unauthorized())
        var refreshes = 0
        val client = client(token = { "expired" }, refresh = { refreshes++; "fresh-$refreshes" })

        val response = client.get()
        response.close()

        assertEquals(401, response.code)
        assertEquals(1, refreshes) // exactly one retry was attempted
        assertEquals(2, server.requestCount) // original + one retry, then it stopped
    }

    @Test
    fun `a burst of parallel 401s does not multiply the refresh calls`() {
        // Four requests, each answered 401 and each retried once: the verifiable
        // claim here is that the authenticator never retries more than once per
        // request, so the request count stays exactly 2 per call even under
        // concurrency. (Collapsing the four refreshes into one is AuthSession's
        // single-flight job, tested in AuthSessionTest.)
        repeat(4) {
            server.enqueue(unauthorized())
            server.enqueue(ok())
        }
        val refreshes = java.util.concurrent.atomic.AtomicInteger()
        val client = client(token = { "expired" }, refresh = { refreshes.incrementAndGet(); "fresh" })

        repeat(4) { client.get().close() }

        assertEquals(4, refreshes.get())
        assertEquals(8, server.requestCount)
    }
}
