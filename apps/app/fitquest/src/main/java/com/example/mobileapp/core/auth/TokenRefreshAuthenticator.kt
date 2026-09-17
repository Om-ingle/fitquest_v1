package com.example.mobileapp.core.auth

import okhttp3.Authenticator
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route

/**
 * M11 (F-04) — re-authenticates a request the server answered 401.
 *
 * OkHttp invokes this automatically when a response carries 401, and retries
 * the request if a replacement is returned. That is exactly the behaviour
 * wanted: an access token that expires mid-session is invisible to every
 * fetcher in the app — the request simply succeeds on the second attempt, and
 * no call site needs to know that tokens expire at all.
 *
 * ### Why it cannot loop
 *
 * Three independent guards, because a refresh loop is a denial-of-service
 * against your own identity provider:
 *
 *  1. A request with no `Authorization` header is never retried. This is the
 *     structural one: the Supabase token endpoint carries no bearer (it uses
 *     `apikey`), so a rejected sign-in or refresh can never re-enter here.
 *  2. [maxAttempts] caps the chain — one retry per request, counted through
 *     OkHttp's own `priorResponse` chain, which is the authoritative record of
 *     how many times this call has already been round the loop.
 *  3. A refresh that yields the SAME token is refused. Retrying with the token
 *     the server just rejected is guaranteed to fail again.
 *
 * ### When it gives up
 *
 * Returning null hands the 401 back to the caller, which maps it to an error
 * outcome for the UI. It does NOT mean the user was signed out: [refresh]
 * clears the session only when Supabase explicitly rejects the refresh token,
 * so a transient failure leaves the session — and the stored credentials —
 * intact for the next attempt.
 */
class TokenRefreshAuthenticator(
    private val refresh: (failedAccessToken: String?) -> String?,
    private val maxAttempts: Int = MAX_ATTEMPTS,
) : Authenticator {

    override fun authenticate(route: Route?, response: Response): Request? {
        val failedToken = response.request.header(AuthInterceptor.AUTHORIZATION).bearerToken()
            ?: return null // guard 1: never re-auth a request that carried no bearer

        if (response.attemptCount() >= maxAttempts) return null // guard 2

        val fresh = refresh(failedToken) ?: return null
        if (fresh == failedToken) return null // guard 3

        return response.request.newBuilder()
            .header(AuthInterceptor.AUTHORIZATION, "Bearer $fresh")
            .build()
    }

    private companion object {
        /**
         * Total requests allowed for one logical call: the original plus one
         * retry. A second retry could only re-present a token the server has
         * already refused.
         */
        const val MAX_ATTEMPTS = 2
    }
}

/**
 * How many requests have been made for this response — the original counts as
 * one. Walks [Response.priorResponse], which OkHttp populates for exactly this
 * purpose, rather than keeping our own counter that would need resetting.
 */
private fun Response.attemptCount(): Int {
    var count = 1
    var prior = priorResponse
    while (prior != null) {
        count++
        prior = prior.priorResponse
    }
    return count
}
