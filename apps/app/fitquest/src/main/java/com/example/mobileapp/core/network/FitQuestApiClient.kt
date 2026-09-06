package com.example.mobileapp.core.network

import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Builds the [FitQuestApi] Retrofit instance against the configurable
 * backend base URL (BuildConfig.BACKEND_BASE_URL, set via BACKEND_BASE_URL in
 * apps/app/.env — defaults to the emulator host alias http://10.0.2.2:8000/).
 *
 * No backend secrets (DATABASE_URL, Supabase keys) ever reach Android; the
 * dev-user backend currently requires no auth headers.
 */
object FitQuestApiClient {

    fun create(baseUrl: String): FitQuestApi {
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
            .build()

        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(FitQuestApi::class.java)
    }
}
