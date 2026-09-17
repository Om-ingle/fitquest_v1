package com.example.mobileapp.core.auth

import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

/**
 * M11 (F-04) — the bearer interceptor, asserted on the wire.
 *
 * Every test here drives a real [OkHttpClient] against a real server and then
 * reads what actually arrived. That matters because the failure modes this
 * guards against are all visible only in the sent bytes: a header that was
 * added twice, a token captured at construction instead of read per call, or a
 * blank token sent as `Bearer ` (which is not "no identity", it is a malformed
 * credential).
 */
class AuthInterceptorTest {

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

    /** Sends one GET through [interceptors] in order and returns what arrived. */
    private fun send(vararg interceptors: Interceptor): RecordedRequest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        val builder = OkHttpClient.Builder()
        interceptors.forEach { builder.addInterceptor(it) }
        builder.build()
            .newCall(Request.Builder().url(server.url("/api/v1/coach")).build())
            .execute()
            .close()
        return server.takeRequest()
    }

    @Test
    fun `the session token is attached as a bearer header`() {
        val recorded = send(AuthInterceptor { "access-token-1" })

        assertEquals("Bearer access-token-1", recorded.getHeader("Authorization"))
    }

    @Test
    fun `a null token sends no header at all`() {
        val recorded = send(AuthInterceptor { null })

        assertNull(recorded.getHeader("Authorization"))
    }

    @Test
    fun `a blank token is not sent as a malformed bearer`() {
        // `Authorization: Bearer ` is not the same as no identity: it is a
        // credential the server must spend time rejecting, and some proxies
        // treat it as a malformed request rather than a 401.
        assertNull(send(AuthInterceptor { "" }).getHeader("Authorization"))
        assertNull(send(AuthInterceptor { "   " }).getHeader("Authorization"))
    }

    @Test
    fun `surrounding whitespace on the token is stripped`() {
        // A token pasted into an env file very often carries a trailing space,
        // and a bearer value with one is rejected by a strict parser.
        val recorded = send(AuthInterceptor { "  access-token-1\n" })

        assertEquals("Bearer access-token-1", recorded.getHeader("Authorization"))
    }

    @Test
    fun `an existing Authorization header is replaced not duplicated`() {
        // A duplicate Authorization header is ambiguous to every proxy on the
        // path and is a classic request-smuggling shape, so `.header()` is used
        // deliberately over `.addHeader()`. This is the test that would fail if
        // someone "fixed" that to addHeader.
        val staleHeader = Interceptor { chain ->
            chain.proceed(
                chain.request().newBuilder()
                    .header(AuthInterceptor.AUTHORIZATION, "Bearer stale-token")
                    .build()
            )
        }

        val recorded = send(staleHeader, AuthInterceptor { "access-token-1" })

        assertEquals(listOf("Bearer access-token-1"), recorded.headers.values("Authorization"))
    }

    @Test
    fun `the token is read per call so a refresh is picked up immediately`() {
        // The interceptor must not capture the token at construction: after a
        // refresh, the very next request has to carry the new one, without any
        // call site being rewired.
        var token: String? = "access-token-1"
        val interceptor = AuthInterceptor { token }
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        val client = OkHttpClient.Builder().addInterceptor(interceptor).build()

        client.newCall(Request.Builder().url(server.url("/api/v1/coach")).build()).execute().close()
        token = "access-token-2" // as AuthSession.adopt would leave it
        client.newCall(Request.Builder().url(server.url("/api/v1/coach")).build()).execute().close()

        assertEquals("Bearer access-token-1", server.takeRequest().getHeader("Authorization"))
        assertEquals("Bearer access-token-2", server.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun `signing out stops the header being sent`() {
        var token: String? = "access-token-1"
        val client = OkHttpClient.Builder().addInterceptor(AuthInterceptor { token }).build()
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Not authenticated"}"""))

        client.newCall(Request.Builder().url(server.url("/api/v1/coach")).build()).execute().close()
        token = null // as AuthSession.signOut would leave it
        val response = client.newCall(Request.Builder().url(server.url("/api/v1/coach")).build()).execute()
        val status = response.code
        response.close()

        assertEquals("Bearer access-token-1", server.takeRequest().getHeader("Authorization"))
        assertNull(server.takeRequest().getHeader("Authorization"))
        // Signed out is a server-side answer, not a local short-circuit.
        assertEquals(401, status)
    }

    // ── The bearer parser the 401 guard relies on ───────────────────────────

    @Test
    fun `only a real bearer header yields a token`() {
        // This is guard 1 of TokenRefreshAuthenticator: a request that carried
        // no bearer must never be retried, or the refresh call itself would
        // re-enter the authenticator.
        assertEquals("abc", "Bearer abc".bearerToken())
        assertEquals("abc", "bearer abc".bearerToken()) // scheme is case-insensitive
        assertEquals("abc", "  Bearer   abc  ".bearerToken())

        assertNull(null.bearerToken())
        assertNull("".bearerToken())
        assertNull("Bearer".bearerToken())
        assertNull("Bearer ".bearerToken())
        assertNull("Basic abc".bearerToken())
        assertNull("abc".bearerToken())
    }
}
