package com.example.mobileapp.core.auth

import retrofit2.http.Body
import retrofit2.http.POST
import retrofit2.http.Query

/**
 * M11 (F-04) — the Supabase Auth endpoints the app uses, and nothing else.
 *
 * Only two grants are modelled, both of which are passwordless-secret-free from
 * the client's point of view: the user's own `password` grant (sign-in) and
 * `refresh_token` (re-authentication). No admin/user-management endpoints are
 * reachable from the app, and the service-role key is never present here —
 * the Android build only ever carries the PUBLISHABLE anon key, which is
 * designed to be public and which grants nothing on its own.
 */
internal interface SupabaseAuthApi {

    @POST("token")
    suspend fun passwordGrant(
        @Query("grant_type") grantType: String,
        @Body body: PasswordGrantBody,
    ): SupabaseTokenDto

    @POST("token")
    suspend fun refreshGrant(
        @Query("grant_type") grantType: String,
        @Body body: RefreshGrantBody,
    ): SupabaseTokenDto

    companion object {
        const val GRANT_PASSWORD = "password"
        const val GRANT_REFRESH_TOKEN = "refresh_token"
    }
}

internal data class PasswordGrantBody(
    val email: String,
    val password: String,
)

internal data class RefreshGrantBody(
    val refresh_token: String,
)

/**
 * Wire shape of a successful `POST /auth/v1/token`.
 *
 * Every field is nullable because this is untrusted network input that Gson
 * populates by reflection: a missing JSON key would otherwise leave a non-null
 * Kotlin field silently null and crash later, far from the cause.
 * [SupabaseAuthClient] validates the fields it needs and refuses the response
 * if they are absent, so a malformed body is a clean failure rather than a
 * `NullPointerException` at the call site.
 */
internal data class SupabaseTokenDto(
    val access_token: String? = null,
    val refresh_token: String? = null,
    val token_type: String? = null,
    val expires_in: Long? = null,
    val expires_at: Long? = null,
    val user: SupabaseUserDto? = null,
)

internal data class SupabaseUserDto(
    val id: String? = null,
    val email: String? = null,
)

/**
 * Builds the Retrofit base URL for Supabase Auth from the project URL.
 *
 * Supabase's project URL carries no path (`https://<ref>.supabase.co`), but an
 * operator may paste it with a trailing slash, or with the `/auth/v1` suffix
 * already attached from the dashboard's docs. Both are accepted and normalised
 * to exactly one `auth/v1/` segment, because a doubled segment produces a 404
 * that looks like a credentials problem.
 *
 * Returns null for anything that is not a usable http(s) URL — including the
 * empty string a build produces when SUPABASE_URL was never set. The caller
 * turns that null into a clear "not configured" failure instead of an obscure
 * `IllegalArgumentException` from Retrofit at startup.
 */
internal fun supabaseAuthBaseUrl(supabaseUrl: String?): String? {
    val trimmed = supabaseUrl?.trim()?.trimEnd('/').orEmpty()
    if (trimmed.isEmpty()) return null
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) return null
    // Accept a URL that already names the auth path, and strip it so it is
    // added exactly once below. (trailing slashes are already gone above)
    val root = trimmed.removeSuffix("/auth/v1")
    if (root.isEmpty()) return null
    return "$root/auth/v1/"
}
