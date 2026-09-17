package com.example.mobileapp.core.auth

import okhttp3.Interceptor
import okhttp3.Response

/**
 * M11 (F-04) — attaches the session's access token to every outgoing request.
 *
 * This is the ONLY place a request acquires an identity. Nothing else in the
 * app sets an `Authorization` header, and no request body, query parameter or
 * path segment ever names the acting user — the backend derives identity from
 * this header's verified token and from nowhere else, so the client and the
 * server agree on exactly one source of truth.
 *
 * `.header()` rather than `.addHeader()` on purpose: it REPLACES any existing
 * value, so a request can never go out carrying two Authorization headers. A
 * duplicate would be ambiguous to every proxy on the path and is a classic
 * request-smuggling shape.
 *
 * The token is read at call time, not captured at construction, so a refresh
 * mid-session is picked up by the very next request without rewiring anything.
 */
class AuthInterceptor(
    private val accessToken: () -> String?,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val token = accessToken()?.trim()
        if (token.isNullOrEmpty()) {
            // Signed out: the request goes out unauthenticated and the server
            // answers 401. Deliberately not short-circuited here — fabricating
            // a local failure would hide the server's own answer, and the
            // backend's 401 is the contract we are testing against.
            return chain.proceed(request)
        }
        return chain.proceed(
            request.newBuilder()
                .header(AUTHORIZATION, "Bearer $token")
                .build()
        )
    }

    companion object {
        const val AUTHORIZATION = "Authorization"
    }
}

/** The bearer value of an `Authorization` header, or null if it is not one. */
internal fun String?.bearerToken(): String? {
    val parts = this?.trim()?.split(' ', limit = 2) ?: return null
    if (parts.size != 2) return null
    if (!parts[0].equals("Bearer", ignoreCase = true)) return null
    return parts[1].trim().ifEmpty { null }
}
