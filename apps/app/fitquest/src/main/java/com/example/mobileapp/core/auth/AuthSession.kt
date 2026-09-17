package com.example.mobileapp.core.auth

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull

/**
 * M11 (F-04) — the app's single source of truth for "who is signed in".
 *
 * Every other component asks this object:
 *
 *  * the bearer interceptor asks [accessToken] before each request,
 *  * the 401 authenticator asks [refreshBlocking] for a new one,
 *  * the UI observes [state] to decide between the login screen and the app,
 *  * the coaching WebSocket is opened only while a session exists.
 *
 * Centralising it is what makes the session coherent: there is exactly one
 * place that can mint, replace or destroy it, so the token on the wire, the
 * token in [store] and the token the UI believes in cannot drift apart.
 *
 * ### When the session actually ends
 *
 * Only the issuer can end a session. A network blip, a 5xx, a rate limit or an
 * unparseable body all leave the session exactly as it was — the access token
 * may still be perfectly good, and destroying credentials because a request
 * failed would log users out every time they walked into a lift. The session is
 * cleared on precisely one event: Supabase explicitly rejecting the refresh
 * token ([SupabaseAuthClient.Outcome.InvalidCredentials]), which is the one
 * signal that says "this session is over".
 */
class AuthSession(
    private val client: SupabaseAuthClient,
    private val store: TokenStore,
    private val nowEpochSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
) {

    /**
     * Guards every mutation of [tokens] and the store, and serialises refreshes.
     *
     * Reentrant, so [adopt]/[signOut] can be called while [refreshBlocking]
     * holds it. Holding it across the refresh network call is deliberate: two
     * threads that both saw a 401 must not each redeem the same refresh token —
     * Supabase ROTATES refresh tokens, so the loser of that race would be
     * holding one that no longer works and would sign the user out.
     */
    private val lock = Any()

    @Volatile
    private var tokens: AuthTokens? = runCatching { store.load() }.getOrNull()

    private val _state = MutableStateFlow(stateOf(tokens))
    val state: StateFlow<AuthState> = _state.asStateFlow()

    fun currentTokens(): AuthTokens? = tokens

    /** The bearer value for the next request, or null when signed out. */
    fun accessToken(): String? = tokens?.accessToken

    /**
     * Sign in with the user's own credentials. A failure leaves the current
     * session untouched — a mistyped password must not evict a live session.
     */
    suspend fun signIn(email: String, password: String): SupabaseAuthClient.Outcome {
        val outcome = client.signInWithPassword(email, password)
        if (outcome is SupabaseAuthClient.Outcome.Success) adopt(outcome.tokens)
        return outcome
    }

    /**
     * Re-establish a session at startup, refreshing only if the stored access
     * token is expired or about to be.
     *
     * Returns whether a session is available — not whether it is provably
     * fresh. Offline with a stored session returns true: the app opens and
     * serves cached data, and the first request that actually reaches the
     * server drives a refresh through the authenticator.
     */
    suspend fun restore(): Boolean {
        val current = tokens ?: return false
        if (!current.isExpired(nowEpochSeconds())) return true

        return when (val outcome = client.refresh(current.refreshToken, current.userId, current.email)) {
            is SupabaseAuthClient.Outcome.Success -> {
                adopt(outcome.tokens)
                true
            }
            SupabaseAuthClient.Outcome.InvalidCredentials -> {
                signOut()
                false
            }
            else -> true
        }
    }

    /** Drop the session everywhere: memory, storage, and the observed state. */
    fun signOut() {
        synchronized(lock) {
            tokens = null
            runCatching { store.clear() }
            _state.value = AuthState.SignedOut
        }
    }

    /**
     * Refresh for the OkHttp authenticator, which cannot suspend.
     *
     * BLOCKING — call it only from a network thread, never from the main
     * thread. [withTimeoutOrNull] bounds it so a hung connection cannot wedge
     * the caller forever.
     *
     * [failedAccessToken] is the token the rejected request actually carried.
     * If the stored token has moved on since, another thread has already
     * refreshed and this returns that newer token without a second round trip —
     * the standard single-flight guard, and the reason a burst of parallel 401s
     * costs exactly one refresh.
     *
     * Returns the token to retry with, or null to give up. Null does not
     * necessarily mean signed out: only an explicit rejection clears the
     * session (see the class comment).
     */
    fun refreshBlocking(failedAccessToken: String?): String? {
        synchronized(lock) {
            val current = tokens ?: return null

            if (failedAccessToken != null && current.accessToken != failedAccessToken) {
                return current.accessToken
            }

            val outcome = runCatching {
                runBlocking {
                    withTimeoutOrNull(REFRESH_TIMEOUT_MS) {
                        client.refresh(current.refreshToken, current.userId, current.email)
                    }
                }
            }.getOrNull() ?: return null // timed out or the coroutine failed: retry later

            return when (outcome) {
                is SupabaseAuthClient.Outcome.Success -> {
                    adopt(outcome.tokens)
                    outcome.tokens.accessToken
                }
                SupabaseAuthClient.Outcome.InvalidCredentials -> {
                    signOut()
                    null
                }
                // ServerError / NetworkError / MalformedResponse / NotConfigured:
                // the session is not provably dead, so it is left alone.
                else -> null
            }
        }
    }

    private fun adopt(fresh: AuthTokens) {
        synchronized(lock) {
            tokens = fresh
            runCatching { store.save(fresh) }
            _state.value = AuthState.SignedIn(fresh.userId, fresh.email)
        }
    }

    private companion object {
        /**
         * Ceiling on a blocking refresh. Longer than the client's own 20s read
         * timeout is pointless (the call would already have failed), so this
         * only exists to cover a stall that never reaches the socket.
         */
        const val REFRESH_TIMEOUT_MS = 20_000L
    }
}

private fun stateOf(tokens: AuthTokens?): AuthState =
    if (tokens == null) AuthState.SignedOut
    else AuthState.SignedIn(tokens.userId, tokens.email)
