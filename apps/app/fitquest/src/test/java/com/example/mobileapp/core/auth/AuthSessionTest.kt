package com.example.mobileapp.core.auth

import java.io.IOException
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response as RetrofitResponse

/**
 * M11 (F-04) — the session's lifecycle rules, which are the part of auth most
 * likely to be got subtly wrong.
 *
 * The single rule this file exists to pin down: **only an explicit rejection by
 * the issuer ends a session.** A network blip, a 5xx, a rate limit or an
 * unparseable body must all leave the credentials exactly where they were —
 * logging a user out because one request failed is a bug users experience as
 * "the app keeps forgetting me".
 *
 * The issuer is a scripted [SupabaseAuthApi] rather than a real HTTP server
 * because what is being tested is the session's reaction to each outcome, not
 * the wire format (that is SupabaseAuthClientTest's job). The client under test
 * is the real one, so the outcome mapping is exercised end to end.
 */
class AuthSessionTest {

    private val now = 1_000_000L
    private val user = "11111111-1111-4111-8111-111111111111"
    private val email = "runner@example.com"

    private val farFuture = now + 3600
    private val justExpired = now - 1
    private val aboutToExpire = now + AuthTokens.EXPIRY_SKEW_SECONDS / 2

    // ── Fixtures ────────────────────────────────────────────────────────────

    private fun stored(access: String = "access-1", expiresAt: Long = farFuture) = AuthTokens(
        accessToken = access,
        refreshToken = "refresh-1",
        expiresAtEpochSeconds = expiresAt,
        userId = user,
        email = email,
    )

    private fun dto(access: String = "access-2", refresh: String = "refresh-2") = SupabaseTokenDto(
        access_token = access,
        refresh_token = refresh,
        token_type = "bearer",
        expires_in = 3600,
        user = SupabaseUserDto(id = user, email = email),
    )

    /** The shape Retrofit throws for any non-2xx response. */
    private fun httpError(code: Int): Nothing = throw HttpException(
        RetrofitResponse.error<Any>(code, "{}".toResponseBody("application/json".toMediaType()))
    )

    private class ScriptedAuthApi(
        private val onPassword: () -> SupabaseTokenDto = {
            throw AssertionError("unexpected password grant")
        },
        private val onRefresh: () -> SupabaseTokenDto = {
            throw AssertionError("unexpected refresh grant")
        },
    ) : SupabaseAuthApi {

        var passwordCalls = 0
            private set
        var refreshCalls = 0
            private set

        override suspend fun passwordGrant(
            grantType: String,
            body: PasswordGrantBody,
        ): SupabaseTokenDto {
            passwordCalls++
            return onPassword()
        }

        override suspend fun refreshGrant(
            grantType: String,
            body: RefreshGrantBody,
        ): SupabaseTokenDto {
            refreshCalls++
            return onRefresh()
        }
    }

    private fun session(api: ScriptedAuthApi, store: TokenStore): AuthSession =
        AuthSession(
            client = SupabaseAuthClient(api = api, configured = true, nowEpochSeconds = { now }),
            store = store,
            nowEpochSeconds = { now },
        )

    // ── Construction ────────────────────────────────────────────────────────

    @Test
    fun `a stored session is adopted at construction`() {
        val session = session(ScriptedAuthApi(), InMemoryTokenStore(stored()))

        assertEquals("access-1", session.accessToken())
        assertEquals(AuthState.SignedIn(user, email), session.state.value)
        assertEquals("refresh-1", session.currentTokens()?.refreshToken)
    }

    @Test
    fun `an empty store starts signed out`() {
        val session = session(ScriptedAuthApi(), InMemoryTokenStore())

        assertNull(session.accessToken())
        assertEquals(AuthState.SignedOut, session.state.value)
    }

    @Test
    fun `a store that cannot be read starts signed out instead of crashing`() {
        // An invalidated keystore (factory reset, restored backup, changed lock
        // screen) must present as "signed out", never as a crash in the DI graph
        // — which would take the whole app down before the login screen exists.
        val broken = object : TokenStore {
            override fun load(): AuthTokens? = throw IllegalStateException("keystore invalidated")
            override fun save(tokens: AuthTokens) = throw IllegalStateException("keystore invalidated")
            override fun clear() = throw IllegalStateException("keystore invalidated")
        }

        val session = session(ScriptedAuthApi(), broken)

        assertEquals(AuthState.SignedOut, session.state.value)
        assertNull(session.accessToken())
    }

    // ── Sign-in ─────────────────────────────────────────────────────────────

    @Test
    fun `a successful sign-in is persisted and observable`() = runBlocking {
        val store = InMemoryTokenStore()
        val session = session(ScriptedAuthApi(onPassword = { dto() }), store)

        val outcome = session.signIn(email, "hunter2")

        assertTrue(outcome is SupabaseAuthClient.Outcome.Success)
        assertEquals("access-2", session.accessToken())
        assertEquals(AuthState.SignedIn(user, email), session.state.value)
        // Persisted, so the session survives the process dying.
        assertEquals("access-2", store.load()?.accessToken)
        assertEquals("refresh-2", store.load()?.refreshToken)
    }

    @Test
    fun `a wrong password does not evict a live session`() = runBlocking {
        val store = InMemoryTokenStore(stored())
        val session = session(ScriptedAuthApi(onPassword = { httpError(400) }), store)

        val outcome = session.signIn(email, "wrong")

        assertEquals(SupabaseAuthClient.Outcome.InvalidCredentials, outcome)
        // The signed-in user typed a password into a form that was not theirs to
        // type; the session they already had is untouched.
        assertEquals("access-1", session.accessToken())
        assertEquals(AuthState.SignedIn(user, email), session.state.value)
        assertEquals("access-1", store.load()?.accessToken)
    }

    @Test
    fun `a network failure during sign-in does not evict a live session`() = runBlocking {
        val store = InMemoryTokenStore(stored())
        val session = session(
            ScriptedAuthApi(onPassword = { throw IOException("no route to host") }),
            store,
        )

        assertEquals(
            SupabaseAuthClient.Outcome.NetworkError,
            session.signIn(email, "hunter2"),
        )
        assertEquals(AuthState.SignedIn(user, email), session.state.value)
        assertEquals("access-1", store.load()?.accessToken)
    }

    @Test
    fun `a cancelled sign-in propagates rather than becoming a response`() = runBlocking {
        // Structured concurrency must not be swallowed: a cancelled sign-in is
        // the caller going away, not a malformed response to be shown to a user.
        val session = session(
            ScriptedAuthApi(onPassword = { throw CancellationException("caller left") }),
            InMemoryTokenStore(),
        )

        val thrown = try {
            session.signIn(email, "hunter2")
            null
        } catch (e: Throwable) {
            e
        }

        assertTrue("cancellation must propagate, got $thrown", thrown is CancellationException)
        assertEquals(AuthState.SignedOut, session.state.value)
    }

    @Test
    fun `a session survives a storage failure`() = runBlocking {
        // Persistence is best-effort: a device whose keystore has gone bad still
        // gets a working session for this process, and puts nothing on disk.
        val store = object : TokenStore {
            override fun load(): AuthTokens? = null
            override fun save(tokens: AuthTokens) = throw IllegalStateException("keystore invalidated")
            override fun clear() = Unit
        }
        val session = session(ScriptedAuthApi(onPassword = { dto() }), store)

        assertTrue(session.signIn(email, "hunter2") is SupabaseAuthClient.Outcome.Success)

        assertEquals("access-2", session.accessToken())
        assertEquals(AuthState.SignedIn(user, email), session.state.value)
    }

    @Test
    fun `an unconfigured build reports it instead of calling the network`() = runBlocking {
        val api = ScriptedAuthApi()
        val session = AuthSession(
            client = SupabaseAuthClient(api = api, configured = false, nowEpochSeconds = { now }),
            store = InMemoryTokenStore(),
            nowEpochSeconds = { now },
        )

        assertEquals(
            SupabaseAuthClient.Outcome.NotConfigured,
            session.signIn(email, "hunter2"),
        )
        assertEquals(0, api.passwordCalls)
    }

    // ── Sign-out ────────────────────────────────────────────────────────────

    @Test
    fun `sign-out clears memory, storage and the observed state`() {
        val store = InMemoryTokenStore(stored())
        val session = session(ScriptedAuthApi(), store)

        session.signOut()

        assertNull(session.accessToken())
        assertNull(session.currentTokens())
        assertNull(store.load())
        assertEquals(AuthState.SignedOut, session.state.value)
    }

    // ── restore() at startup ────────────────────────────────────────────────

    @Test
    fun `restore keeps a fresh token without a round trip`() = runBlocking {
        val api = ScriptedAuthApi()
        val session = session(api, InMemoryTokenStore(stored(expiresAt = farFuture)))

        assertTrue(session.restore())

        assertEquals(0, api.refreshCalls)
        assertEquals("access-1", session.accessToken())
    }

    @Test
    fun `restore refreshes a token that has already expired`() = runBlocking {
        val api = ScriptedAuthApi(onRefresh = { dto() })
        val store = InMemoryTokenStore(stored(access = "expired", expiresAt = justExpired))
        val session = session(api, store)

        assertTrue(session.restore())

        assertEquals(1, api.refreshCalls)
        assertEquals("access-2", session.accessToken())
        assertEquals("access-2", store.load()?.accessToken)
    }

    @Test
    fun `restore refreshes a token that is about to expire`() = runBlocking {
        // The skew is not decoration: a token valid when the request is built
        // can expire in flight, and a slightly slow device clock would treat a
        // dead token as live. Refreshing a minute early costs one request.
        val api = ScriptedAuthApi(onRefresh = { dto() })
        val session = session(api, InMemoryTokenStore(stored(expiresAt = aboutToExpire)))

        assertTrue(session.restore())

        assertEquals(1, api.refreshCalls)
        assertEquals("access-2", session.accessToken())
    }

    @Test
    fun `restore signs out only when the issuer rejects the refresh token`() = runBlocking {
        val store = InMemoryTokenStore(stored(expiresAt = justExpired))
        val session = session(ScriptedAuthApi(onRefresh = { httpError(400) }), store)

        assertEquals(false, session.restore())

        assertEquals(AuthState.SignedOut, session.state.value)
        assertNull(store.load())
    }

    @Test
    fun `restore keeps the session when the refresh cannot reach the issuer`() = runBlocking {
        // Offline at startup with a stored session: the app must open and serve
        // cached data rather than demand a password because the network is down.
        val store = InMemoryTokenStore(stored(expiresAt = justExpired))
        val session = session(
            ScriptedAuthApi(onRefresh = { throw IOException("no route to host") }),
            store,
        )

        assertTrue(session.restore())

        assertEquals(AuthState.SignedIn(user, email), session.state.value)
        assertEquals("access-1", session.accessToken())
        assertEquals("refresh-1", store.load()?.refreshToken)
    }

    @Test
    fun `restore keeps the session when the issuer is unhealthy`() = runBlocking {
        val store = InMemoryTokenStore(stored(expiresAt = justExpired))
        val session = session(ScriptedAuthApi(onRefresh = { httpError(503) }), store)

        assertTrue(session.restore())

        assertEquals(AuthState.SignedIn(user, email), session.state.value)
        assertEquals("refresh-1", store.load()?.refreshToken)
    }

    @Test
    fun `restore keeps the session when the response is unparseable`() = runBlocking {
        // A changed contract, not a dead session. Signing the user out here
        // would turn a server-side release into a mass logout.
        val store = InMemoryTokenStore(stored(expiresAt = justExpired))
        val session = session(ScriptedAuthApi(onRefresh = { SupabaseTokenDto() }), store)

        assertTrue(session.restore())

        assertEquals(AuthState.SignedIn(user, email), session.state.value)
        assertEquals("refresh-1", store.load()?.refreshToken)
    }

    @Test
    fun `restore without a stored session does not call the issuer`() = runBlocking {
        val api = ScriptedAuthApi()
        val session = session(api, InMemoryTokenStore())

        assertEquals(false, session.restore())

        assertEquals(0, api.refreshCalls)
    }

    // ── refreshBlocking() — the 401 path ────────────────────────────────────

    @Test
    fun `a successful refresh hands back a new token and persists it`() {
        val store = InMemoryTokenStore(stored(access = "expired"))
        val api = ScriptedAuthApi(onRefresh = { dto() })
        val session = session(api, store)

        assertEquals("access-2", session.refreshBlocking("expired"))

        assertEquals("access-2", session.accessToken())
        assertEquals("refresh-2", store.load()?.refreshToken)
        assertEquals(AuthState.SignedIn(user, email), session.state.value)
    }

    @Test
    fun `an explicitly rejected refresh token ends the session`() {
        val store = InMemoryTokenStore(stored(access = "expired"))
        val session = session(ScriptedAuthApi(onRefresh = { httpError(400) }), store)

        assertNull(session.refreshBlocking("expired"))

        assertEquals(AuthState.SignedOut, session.state.value)
        assertNull(store.load())
    }

    @Test
    fun `a transient refresh failure keeps the session for the next attempt`() {
        // Null here means "could not fix THIS request", not "signed out".
        val store = InMemoryTokenStore(stored(access = "expired"))
        val session = session(
            ScriptedAuthApi(onRefresh = { throw IOException("connection reset") }),
            store,
        )

        assertNull(session.refreshBlocking("expired"))

        assertEquals("expired", session.accessToken())
        assertEquals("refresh-1", store.load()?.refreshToken)
        assertEquals(AuthState.SignedIn(user, email), session.state.value)
    }

    @Test
    fun `refreshBlocking without a session is a no-op`() {
        val api = ScriptedAuthApi()
        val session = session(api, InMemoryTokenStore())

        assertNull(session.refreshBlocking("whatever"))

        assertEquals(0, api.refreshCalls)
    }

    @Test
    fun `a token that another caller already replaced is returned without a refresh`() {
        // The single-flight guard, sequentially: the caller is holding a 401
        // from a token that no longer exists. Refreshing again would spend a
        // round trip to learn what we already know.
        val api = ScriptedAuthApi(onRefresh = { dto() })
        val session = session(api, InMemoryTokenStore(stored(access = "expired")))

        assertEquals("access-2", session.refreshBlocking("expired"))
        assertEquals("access-2", session.refreshBlocking("expired")) // stale failure token

        assertEquals(1, api.refreshCalls)
    }

    @Test
    fun `concurrent refreshes cost exactly one round trip`() {
        // Supabase ROTATES refresh tokens. If two threads each redeemed the same
        // one, the loser would be holding a token that no longer works and would
        // sign the user out — so refreshBlocking holds the session lock across
        // the network call on purpose.
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val api = ScriptedAuthApi(
            onRefresh = {
                entered.countDown()
                release.await(10, TimeUnit.SECONDS)
                dto()
            },
        )
        val session = session(api, InMemoryTokenStore(stored(access = "expired")))
        val results = Collections.synchronizedList(mutableListOf<String?>())

        val first = Thread { results.add(session.refreshBlocking("expired")) }
        val second = Thread { results.add(session.refreshBlocking("expired")) }
        first.start()
        assertTrue(
            "the first refresh must reach the issuer",
            entered.await(10, TimeUnit.SECONDS),
        )
        second.start() // blocks on the session lock while the first is in flight
        release.countDown()
        first.join(10_000)
        second.join(10_000)

        assertEquals(1, api.refreshCalls)
        assertEquals(listOf("access-2", "access-2"), results.toList())
        assertEquals("access-2", session.accessToken())
    }
}
