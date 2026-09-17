package com.example.mobileapp.core.auth

/**
 * M11 (F-04) — a signed-in session's credentials, exactly as Supabase Auth
 * issues them.
 *
 * The access token is what every backend call carries; the refresh token is
 * what buys a new access token when it expires. Both are secrets: this type is
 * persisted only through [TokenStore] (encrypted at rest on device) and is
 * never logged.
 *
 * [userId] is Supabase's `auth.users.id` — the backend's token SUBJECT. It is
 * deliberately not the backend's internal user id: the two id spaces are kept
 * distinct server-side (see apps/api/app/modules/users/models.py), and the
 * client never needs to know the internal one.
 */
data class AuthTokens(
    val accessToken: String,
    val refreshToken: String,
    val expiresAtEpochSeconds: Long,
    val userId: String,
    val email: String?,
) {

    /**
     * True when the access token is expired — or about to be, within
     * [EXPIRY_SKEW_SECONDS].
     *
     * The skew is not decoration: a token that is valid when the request is
     * built can expire while it is in flight, and a device clock that drifts
     * slightly behind the issuer's would otherwise treat a dead token as live.
     * Refreshing a minute early costs one request; refreshing too late costs a
     * 401 the user sees.
     */
    fun isExpired(
        nowEpochSeconds: Long,
        skewSeconds: Long = EXPIRY_SKEW_SECONDS,
    ): Boolean = nowEpochSeconds >= expiresAtEpochSeconds - skewSeconds

    companion object {
        /** Refresh this many seconds before the token actually expires. */
        const val EXPIRY_SKEW_SECONDS = 60L
    }
}

/**
 * Who the app currently is, as far as the UI is concerned.
 *
 * Deliberately two states, not three: "has a token that we have not verified
 * yet" is not a state the UI can act on differently, and a third state that
 * renders the same as one of the others is a state that will drift. Whether the
 * refresh token still works is discovered by using it ([AuthSession.restore],
 * or the 401 authenticator), and the answer moves the app to one of these two.
 */
sealed interface AuthState {

    /** No usable session: the app shows the login screen and calls nothing. */
    object SignedOut : AuthState

    /** A session exists. [email] is for display only — it is never an identity. */
    data class SignedIn(val userId: String, val email: String?) : AuthState
}
