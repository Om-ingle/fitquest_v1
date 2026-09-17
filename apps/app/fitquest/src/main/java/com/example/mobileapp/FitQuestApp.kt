package com.example.mobileapp

import android.app.Application
import android.util.Log
import com.example.mobileapp.core.session.AccountScopeCoordinator
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
            // M11 follow-up: start the account-scope observer. Resolving it also
            // installs its subscription on the session's subject, which is what
            // drops the previous account's coach state and live run the moment
            // the signed-in account changes — and opens the AccountScopeGuard
            // that those surfaces read before they will hold anything at all.
            // Started here, at process start rather than on first sign-out, so
            // it is already listening when the transition happens.
            //
            // A failure here still must not take the app down, and it no longer
            // needs to: the surfaces are fail-closed, so a coordinator that
            // never starts leaves them EMPTY rather than stale. The app runs
            // with a blank coach card and run tracking declined — visible, and
            // not a leak.
            //
            // This block used to log the same failure and run on with the
            // isolation control simply absent, which is how that defect shipped
            // unnoticed. Do not add a fallback here that tries to clear the
            // caches: they are already empty, because nothing may fill them
            // while the guard is shut.
            try {
                koinApplication.koin.get<AccountScopeCoordinator>().start()
            } catch (e: Exception) {
                Log.e(
                    "FitQuestApp",
                    "Account scope observer failed to start — account-scoped " +
                        "surfaces stay closed (empty coach card, no run tracking) " +
                        "rather than risk serving the previous account's data",
                    e
                )
            }
        } catch (e: Exception) {
            Log.e("FitQuestApp", "Koin failed to start", e)
        }
    }
}


