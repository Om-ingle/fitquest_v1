package com.example.mobileapp

import android.app.Application
import android.util.Log
import com.example.mobileapp.core.tts.CoachingSpeechController
import com.example.mobileapp.di.appModule
import org.koin.android.ext.koin.androidContext
import org.koin.core.context.startKoin
import org.maplibre.android.MapLibre

class FitQuestApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // Must catch Throwable (not just Exception) because a missing native .so
        // throws UnsatisfiedLinkError which is a JVM Error — it escapes all
        // Exception handlers and kills the process silently before Logcat fires.
        try {
            MapLibre.getInstance(this)
        } catch (e: Throwable) {
            Log.e("FitQuestApp", "MapLibre native init failed — check jniLibs", e)
        }
        try {
            val koinApplication = startKoin {
                androidContext(this@FitQuestApp)
                modules(appModule)
            }
            // M8.4: start the app-scoped voice-coaching observer. Koin is lazy,
            // so resolving the controller also constructs the native TTS engine
            // (bound to the application context) exactly once per process, and
            // its collector starts watching the live coaching store. If TTS is
            // unavailable on the device this must never take the app down —
            // every failure inside is already contained; this is a final guard.
            try {
                koinApplication.koin.get<CoachingSpeechController>().start()
            } catch (e: Exception) {
                Log.e("FitQuestApp", "Voice coaching start failed", e)
            }
        } catch (e: Exception) {
            Log.e("FitQuestApp", "Koin failed to start", e)
        }
    }
}


