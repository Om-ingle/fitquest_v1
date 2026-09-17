package com.example.mobileapp.core.network

import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Builds the [FitQuestApi] Retrofit instance against the configurable
 * backend base URL (BuildConfig.BACKEND_BASE_URL, set via BACKEND_BASE_URL in
 * apps/app/.env — defaults to the emulator host alias http://10.0.2.2:8000/).
 *
 * M11 (F-04): every request this client makes is authenticated. The two
 * collaborators are passed in rather than constructed here so that this class
 * stays a pure transport factory and the session remains owned by
 * `core.auth.AuthSession` — there is exactly one session in the process and
 * this client is one of its consumers:
 *
 *  * [authInterceptor] attaches `Authorization: Bearer <access token>`, and
 *  * [authenticator] re-authenticates and retries once when the server
 *    answers 401, so an expired token is invisible to every fetcher.
 *
 * No backend secrets (DATABASE_URL, the Supabase service-role key) ever reach
 * Android: the only Supabase value in the APK is the publishable anon key,
 * which is used solely to talk to Supabase Auth and confers no authority.
 */
object FitQuestApiClient {

    fun create(
        baseUrl: String,
        authInterceptor: Interceptor,
        authenticator: Authenticator,
    ): FitQuestApi {
        val client = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            // The AI coach endpoint shells out to a reasoning LLM whose latency
            // routinely reaches 10–30s (backend llm_timeout_seconds = 30.0).
            // The earlier 15s read budget let the client abort while the server
            // still returned 200 — observed live on device as an intermittent
            // "AI tip unavailable" (2026-09-06). 45s keeps the client past the
            // backend's own timeout, so the app always receives the terminal
            // 200-or-504 response instead of a spurious NetworkError.
            .readTimeout(45, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .addInterceptor(authInterceptor)
            .authenticator(authenticator)
            .build()

        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(FitQuestApi::class.java)
    }
}
