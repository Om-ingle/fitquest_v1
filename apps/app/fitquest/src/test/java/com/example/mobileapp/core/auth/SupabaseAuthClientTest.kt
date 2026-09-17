package com.example.mobileapp.core.auth

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * M11 (F-04) — the Supabase Auth client against a real HTTP server.
 *
 * MockWebServer is used rather than a faked Retrofit interface because the
 * things worth asserting are on the wire: the grant type in the query string,
 * the `apikey` header, the ABSENCE of a bearer header, and that a 400 is told
 * apart from a 429. A fake interface would assert none of that.
 */
class SupabaseAuthClientTest {

    private lateinit var server: MockWebServer

    /** A fixed clock so `expires_in` arithmetic is exact, not "about now". */
    private var now = 1_000_000L

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun client(anonKey: String = "anon-key"): SupabaseAuthClient =
        SupabaseAuthClient.create(
            supabaseUrl = server.url("/").toString(),
            anonKey = anonKey,
            nowEpochSeconds = { now },
        )

    private fun tokenJson(
        access: String = "access-1",
        refresh: String = "refresh-1",
        expiresIn: Long? = 3600,
        expiresAt: Long? = null,
        userId: String = "11111111-1111-4111-8111-111111111111",
        email: String = "runner@example.com",
        includeUser: Boolean = true,
    ): String = buildString {
        append("{")
        append("\"access_token\":\"$access\",")
        append("\"token_type\":\"bearer\",")
        if (expiresIn != null) append("\"expires_in\":$expiresIn,")
        if (expiresAt != null) append("\"expires_at\":$expiresAt,")
        append("\"refresh_token\":\"$refresh\"")
        if (includeUser) {
            append(",\"user\":{\"id\":\"$userId\",\"email\":\"$email\"}")
        }
        append("}")
    }

    // ── Sign-in ─────────────────────────────────────────────────────────────

    @Test
    fun `a successful password grant yields the session`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(tokenJson()))

        val outcome = client().signInWithPassword("runner@example.com", "hunter2")

        assertTrue(outcome is SupabaseAuthClient.Outcome.Success)
        val tokens = (outcome as SupabaseAuthClient.Outcome.Success).tokens
        assertEquals("access-1", tokens.accessToken)
        assertEquals("refresh-1", tokens.refreshToken)
        assertEquals("11111111-1111-4111-8111-111111111111", tokens.userId)
        assertEquals("runner@example.com", tokens.email)
        assertEquals(now + 3600, tokens.expiresAtEpochSeconds)
    }

    @Test
    fun `the request carries the password grant, the anon key, and no bearer`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(tokenJson()))

        client(anonKey = "publishable-key").signInWithPassword("runner@example.com", "hunter2")

        val recorded = server.takeRequest()
        assertEquals("/auth/v1/token?grant_type=password", recorded.path)
        assertEquals("publishable-key", recorded.getHeader("apikey"))
        // The auth client must never carry a session token: it is the thing
        // that CREATES sessions, and a bearer here would also re-enter the 401
        // authenticator and loop.
        assertNull(recorded.getHeader("Authorization"))

        val body = recorded.body.readUtf8()
        assertTrue(body.contains("\"email\":\"runner@example.com\""))
        assertTrue(body.contains("\"password\":\"hunter2\""))
    }

    @Test
    fun `an absolute expiry wins over the relative one`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody(tokenJson(expiresIn = 3600, expiresAt = 1_700_000_000))
        )

        val outcome = client().signInWithPassword("a@b.c", "pw")

        assertEquals(
            1_700_000_000,
            (outcome as SupabaseAuthClient.Outcome.Success).tokens.expiresAtEpochSeconds,
        )
    }

    // ── Failure classification ──────────────────────────────────────────────

    @Test
    fun `a wrong password is invalid credentials, not a server error`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(400)
                .setBody("""{"error":"invalid_grant","error_description":"Invalid login credentials"}""")
        )

        assertEquals(
            SupabaseAuthClient.Outcome.InvalidCredentials,
            client().signInWithPassword("runner@example.com", "wrong"),
        )
    }

    @Test
    fun `a rate limit is a server error, not a wrong password`() = runBlocking {
        // The distinction is the whole point: telling a user their password is
        // wrong when they are merely rate-limited sends them to reset it.
        server.enqueue(MockResponse().setResponseCode(429).setBody("""{"error":"too_many_requests"}"""))

        assertEquals(
            SupabaseAuthClient.Outcome.ServerError(429),
            client().signInWithPassword("runner@example.com", "hunter2"),
        )
    }

    @Test
    fun `a 5xx is a server error`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(503).setBody("upstream down"))

        assertEquals(
            SupabaseAuthClient.Outcome.ServerError(503),
            client().signInWithPassword("runner@example.com", "hunter2"),
        )
    }

    @Test
    fun `a 2xx body missing the session fields is malformed, not success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"token_type":"bearer"}"""))

        assertEquals(
            SupabaseAuthClient.Outcome.MalformedResponse,
            client().signInWithPassword("runner@example.com", "hunter2"),
        )
    }

    @Test
    fun `a blank access token is refused rather than stored`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(tokenJson(access = "")))

        assertEquals(
            SupabaseAuthClient.Outcome.MalformedResponse,
            client().signInWithPassword("runner@example.com", "hunter2"),
        )
    }

    @Test
    fun `junk that is not json is malformed`() = runBlocking {
        // Gson's malformed-JSON failure is an IOException, so this is also the
        // test that keeps it from being reported as a network error — a
        // reachable server answering with garbage must not tell the user to
        // check their connection.
        server.enqueue(MockResponse().setResponseCode(200).setBody("<html>not json</html>"))

        assertEquals(
            SupabaseAuthClient.Outcome.MalformedResponse,
            client().signInWithPassword("runner@example.com", "hunter2"),
        )
    }

    @Test
    fun `well formed json of the wrong shape is malformed`() = runBlocking {
        // A complete, valid body that is simply not the object this endpoint
        // promises — a different failure again from junk, and still the
        // contract's fault rather than the user's.
        server.enqueue(MockResponse().setResponseCode(200).setBody("""["not","an","object"]"""))

        assertEquals(
            SupabaseAuthClient.Outcome.MalformedResponse,
            client().signInWithPassword("runner@example.com", "hunter2"),
        )
    }

    @Test
    fun `an unreachable server is a network error`() = runBlocking {
        val client = client()
        server.shutdown() // nothing is listening any more

        assertEquals(
            SupabaseAuthClient.Outcome.NetworkError,
            client.signInWithPassword("runner@example.com", "hunter2"),
        )
    }

    @Test
    fun `an unconfigured build fails without touching the network`() = runBlocking {
        val unconfigured = SupabaseAuthClient.create(supabaseUrl = "", anonKey = "")

        assertEquals(
            SupabaseAuthClient.Outcome.NotConfigured,
            unconfigured.signInWithPassword("runner@example.com", "hunter2"),
        )
        assertEquals(
            SupabaseAuthClient.Outcome.NotConfigured,
            unconfigured.refresh("refresh-1", "user-1", null),
        )
        assertEquals(0, server.requestCount)
    }

    // ── Refresh ─────────────────────────────────────────────────────────────

    @Test
    fun `a refresh uses the refresh_token grant`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(tokenJson(access = "access-2")))

        val outcome = client().refresh("refresh-1", "user-1", "runner@example.com")

        assertEquals(
            "access-2",
            (outcome as SupabaseAuthClient.Outcome.Success).tokens.accessToken,
        )
        val recorded = server.takeRequest()
        assertEquals("/auth/v1/token?grant_type=refresh_token", recorded.path)
        assertTrue(recorded.body.readUtf8().contains("\"refresh_token\":\"refresh-1\""))
    }

    @Test
    fun `a refresh response without a user keeps the identity we already hold`() = runBlocking {
        // Supabase is not contractually obliged to repeat `user` here. Treating
        // its absence as malformed would sign out a user whose token is fine.
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody(tokenJson(access = "access-2", includeUser = false))
        )

        val outcome = client().refresh("refresh-1", "known-user-id", "runner@example.com")

        val tokens = (outcome as SupabaseAuthClient.Outcome.Success).tokens
        assertEquals("known-user-id", tokens.userId)
        assertEquals("runner@example.com", tokens.email)
    }

    @Test
    fun `a rejected refresh token is invalid credentials`() = runBlocking {
        // The one signal that ends a session.
        server.enqueue(
            MockResponse().setResponseCode(400)
                .setBody("""{"error":"invalid_grant","error_description":"Invalid Refresh Token"}""")
        )

        assertEquals(
            SupabaseAuthClient.Outcome.InvalidCredentials,
            client().refresh("stale-refresh", "user-1", null),
        )
    }

    @Test
    fun `an expired access token is reported as expired before it actually lapses`() {
        val tokens = AuthTokens(
            accessToken = "a", refreshToken = "r",
            expiresAtEpochSeconds = 10_000, userId = "u", email = null,
        )

        assertTrue(tokens.isExpired(nowEpochSeconds = 10_000 - AuthTokens.EXPIRY_SKEW_SECONDS))
        assertTrue(tokens.isExpired(nowEpochSeconds = 10_000))
        assertTrue(!tokens.isExpired(nowEpochSeconds = 10_000 - AuthTokens.EXPIRY_SKEW_SECONDS - 1))
    }
}
