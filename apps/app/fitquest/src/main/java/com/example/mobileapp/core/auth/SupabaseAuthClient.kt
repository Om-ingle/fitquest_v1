package com.example.mobileapp.core.auth

import com.google.gson.Gson
import com.google.gson.JsonParseException
import com.google.gson.stream.MalformedJsonException
import kotlinx.coroutines.CancellationException
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * M11 (F-04) — talks to Supabase Auth and maps every outcome, including every
 * failure, to an explicit value.
 *
 * The mapping is the point. A sign-in attempt has four genuinely different
 * failures and the UI must tell them apart:
 *
 *  * [Outcome.InvalidCredentials] — the password is wrong. Tell the user.
 *  * [Outcome.NetworkError] — we never reached Supabase. Retrying may work;
 *    telling the user their password is wrong would be a lie.
 *  * [Outcome.ServerError] — Supabase answered, badly (5xx, or 429 rate limit).
 *  * [Outcome.NotConfigured] — the build has no SUPABASE_URL/anon key. This is
 *    a build error, not a user error.
 *
 * Nothing here logs, echoes or stores a password, and the access/refresh tokens
 * travel only inside the returned [AuthTokens] — never into a log line, an
 * exception message, or the UI state.
 */
class SupabaseAuthClient internal constructor(
    private val api: SupabaseAuthApi,
    private val configured: Boolean,
    private val nowEpochSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
) {

    sealed interface Outcome {

        /** Supabase issued a session. */
        data class Success(val tokens: AuthTokens) : Outcome

        /**
         * Supabase rejected the credential: a wrong password on sign-in, or a
         * refresh token that is expired, revoked or already rotated. For a
         * refresh this means the session is over — the caller signs out.
         */
        object InvalidCredentials : Outcome

        /** The build is missing SUPABASE_URL / the publishable anon key. */
        object NotConfigured : Outcome

        /** Supabase answered with an error status we do not treat as a rejection. */
        data class ServerError(val status: Int) : Outcome

        /** The request never completed — no connectivity, DNS, TLS or timeout. */
        object NetworkError : Outcome

        /**
         * A 2xx body that does not carry the fields a session needs. Kept
         * separate from [ServerError] because it means the contract changed,
         * not that the server is unwell.
         */
        object MalformedResponse : Outcome
    }

    /** Sign in with the user's own email and password (the `password` grant). */
    suspend fun signInWithPassword(email: String, password: String): Outcome {
        if (!configured) return Outcome.NotConfigured
        return call {
            api.passwordGrant(
                SupabaseAuthApi.GRANT_PASSWORD,
                PasswordGrantBody(email = email.trim(), password = password),
            )
        }
    }

    /**
     * Exchange a refresh token for a new session (the `refresh_token` grant).
     *
     * [fallbackUserId]/[fallbackEmail] carry the identity we already know. A
     * refresh response is not contractually required to repeat the `user`
     * object, and treating a missing one as a malformed response would sign a
     * perfectly valid user out — so the identity is kept from the session we
     * already hold. If the response DOES carry a user id it wins: it is the
     * server's word, and a mismatch would mean we were refreshing someone
     * else's token, which must never be silently adopted.
     */
    suspend fun refresh(
        refreshToken: String,
        fallbackUserId: String?,
        fallbackEmail: String?,
    ): Outcome {
        if (!configured) return Outcome.NotConfigured
        return call(
            fallbackUserId = fallbackUserId,
            fallbackEmail = fallbackEmail,
        ) {
            api.refreshGrant(
                SupabaseAuthApi.GRANT_REFRESH_TOKEN,
                RefreshGrantBody(refresh_token = refreshToken),
            )
        }
    }

    private suspend fun call(
        fallbackUserId: String? = null,
        fallbackEmail: String? = null,
        request: suspend () -> SupabaseTokenDto,
    ): Outcome = try {
        val dto = request()
        dto.toTokens(fallbackUserId, fallbackEmail)?.let { Outcome.Success(it) }
            ?: Outcome.MalformedResponse
    } catch (e: HttpException) {
        mapHttpError(e)
    } catch (e: JsonParseException) {
        // A body we could not make sense of. The server answered — it just
        // answered something this client does not understand — so this is a
        // changed contract, NOT a connectivity problem: telling the user to
        // check their connection would send them to fix the wrong thing.
        Outcome.MalformedResponse
    } catch (e: MalformedJsonException) {
        // Gson's malformed-JSON failure is an IOException, so it has to be
        // caught ahead of the transport case below or it would be reported as
        // a network error. (Retrofit hands the body straight to the type
        // adapter, which does not wrap it the way Gson.fromJson would.)
        Outcome.MalformedResponse
    } catch (e: IOException) {
        // Includes timeouts, TLS failures and a dropped connection: the request
        // did not complete.
        Outcome.NetworkError
    } catch (e: CancellationException) {
        // Structured concurrency must not be swallowed: a cancelled sign-in is
        // not a malformed response, it is the caller going away.
        throw e
    } catch (e: Exception) {
        // Anything else the converter can raise for a body of the wrong shape —
        // a JSON array where an object was expected surfaces as an
        // IllegalStateException, for instance.
        Outcome.MalformedResponse
    }

    /**
     * Supabase signals a rejected credential with 400 (bad password, bad/expired
     * refresh token) and 401 in some gateway configurations. Both mean the same
     * thing to the caller. 429 is a rate limit and must NOT be shown as a wrong
     * password — it is retryable.
     */
    private fun mapHttpError(e: HttpException): Outcome = when (e.code()) {
        400, 401, 403 -> Outcome.InvalidCredentials
        else -> Outcome.ServerError(e.code())
    }

    private fun SupabaseTokenDto.toTokens(
        fallbackUserId: String?,
        fallbackEmail: String?,
    ): AuthTokens? {
        val access = access_token?.trim().orEmpty()
        val refresh = refresh_token?.trim().orEmpty()
        val userId = user?.id?.trim()?.takeIf { it.isNotEmpty() }
            ?: fallbackUserId?.trim()?.takeIf { it.isNotEmpty() }
        if (access.isEmpty() || refresh.isEmpty() || userId == null) return null

        // Supabase sends `expires_at` as an absolute epoch second; `expires_in`
        // is the fallback for responses that only carry the relative form.
        val expiry = expires_at ?: expires_in?.let { nowEpochSeconds() + it } ?: return null

        return AuthTokens(
            accessToken = access,
            refreshToken = refresh,
            expiresAtEpochSeconds = expiry,
            userId = userId,
            email = user?.email?.trim()?.takeIf { it.isNotEmpty() } ?: fallbackEmail,
        )
    }

    companion object {

        /** Fast enough to fail visibly; long enough to survive a slow mobile network. */
        private const val CONNECT_TIMEOUT_SECONDS = 10L
        private const val READ_TIMEOUT_SECONDS = 20L

        /**
         * Placeholder used when the build is unconfigured. Retrofit rejects a
         * blank base URL at construction, and a misconfigured build should
         * surface as [Outcome.NotConfigured] at sign-in — not as a crash in
         * Koin's startup graph, which would take the whole app down.
         */
        private const val PLACEHOLDER_BASE_URL = "https://unconfigured.invalid/auth/v1/"

        /**
         * Builds the Supabase Auth client from the build's SUPABASE_URL and
         * publishable anon key.
         *
         * This client deliberately carries NONE of the backend client's auth
         * machinery: no bearer interceptor (there is no session yet — that is
         * what these calls create) and no 401 refresh authenticator (refreshing
         * in response to a failed refresh is an infinite loop). Its only header
         * is Supabase's `apikey`, which identifies the PROJECT, not the user,
         * and is public by design.
         */
        fun create(
            supabaseUrl: String,
            anonKey: String,
            nowEpochSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
        ): SupabaseAuthClient {
            val baseUrl = supabaseAuthBaseUrl(supabaseUrl)
            val key = anonKey.trim()
            val http = OkHttpClient.Builder()
                .connectTimeout(CONNECT_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .readTimeout(READ_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .apply {
                    if (key.isNotEmpty()) addInterceptor(ApiKeyInterceptor(key))
                }
                .build()

            val api = Retrofit.Builder()
                .baseUrl(baseUrl ?: PLACEHOLDER_BASE_URL)
                .client(http)
                .addConverterFactory(GsonConverterFactory.create(Gson()))
                .build()
                .create(SupabaseAuthApi::class.java)

            return SupabaseAuthClient(
                api = api,
                configured = baseUrl != null && key.isNotEmpty(),
                nowEpochSeconds = nowEpochSeconds,
            )
        }
    }
}

/**
 * Adds Supabase's `apikey` header. This is the PUBLISHABLE anon key — it ships
 * inside every Supabase client app and confers no authority on its own; the
 * user's access token, never this key, is what the FitQuest backend verifies.
 * The service-role key must never appear in this app.
 */
private class ApiKeyInterceptor(private val anonKey: String) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response =
        chain.proceed(
            chain.request().newBuilder()
                .header("apikey", anonKey)
                .build()
        )
}
