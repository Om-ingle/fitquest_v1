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
            .readTimeout(15, TimeUnit.SECONDS)
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
