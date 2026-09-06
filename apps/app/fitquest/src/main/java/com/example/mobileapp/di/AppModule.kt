package com.example.mobileapp.di

import android.util.Log
import androidx.room.Room
import com.example.mobileapp.BuildConfig
import com.example.mobileapp.core.capture.HexCaptureEngine
import com.example.mobileapp.core.data.local.FitQuestDatabase
import com.example.mobileapp.core.data.local.HexRepository
import com.example.mobileapp.core.data.local.RoomHexRepository
import com.example.mobileapp.core.geo.HexIndexer
import com.example.mobileapp.core.geo.UberH3HexIndexer
import com.example.mobileapp.core.network.CoachingWsClient
import com.example.mobileapp.core.network.CoachingWsMessageParser
import com.example.mobileapp.core.network.FitQuestApi
import com.example.mobileapp.core.network.FitQuestApiClient
import com.example.mobileapp.core.network.LiveCoachStore
import com.example.mobileapp.core.network.OkHttpCoachingSocketFactory
import com.example.mobileapp.core.network.RunReconciler
import com.example.mobileapp.core.network.RunSyncer
import com.example.mobileapp.core.network.coachingWsUrl
import com.example.mobileapp.core.run.ActiveRunController
import com.example.mobileapp.core.tts.AndroidTtsSynthesizer
import com.example.mobileapp.core.tts.CoachingSpeechController
import com.example.mobileapp.core.tts.CoachingSpeechGate
import com.example.mobileapp.core.tts.TtsSynthesizer
import com.example.mobileapp.core.sensors.LocationTrackingManager
import com.example.mobileapp.core.sensors.StepSensorManager
import com.example.mobileapp.features.capture.CaptureScreenModel
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import okhttp3.OkHttpClient
import org.koin.dsl.module

/** Process-scope for long-lived background loops (the coaching WebSocket). */
private val AppScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

val appModule = module {

    single {
        Room.databaseBuilder(
            get(),
            FitQuestDatabase::class.java,
            "fitquest.db"
        )
            .addMigrations(
                FitQuestDatabase.MIGRATION_2_3,
                FitQuestDatabase.MIGRATION_3_4,
                FitQuestDatabase.MIGRATION_4_5
            )
            .fallbackToDestructiveMigration()
            .build()
    }
    single { get<FitQuestDatabase>().hexDao() }
    single { get<FitQuestDatabase>().userDao() }
    single { get<FitQuestDatabase>().runSessionDao() }
    single { get<FitQuestDatabase>().dailyQuestDao() }
    single { get<FitQuestDatabase>().achievementDao() }
    single { get<FitQuestDatabase>().activeRunDao() }

    single<HexRepository> { RoomHexRepository(get()) }
    single<com.example.mobileapp.core.data.local.UserProfileRepository> {
        com.example.mobileapp.core.data.local.RoomUserProfileRepository(get())
    }
    single<com.example.mobileapp.core.data.local.RunSessionRepository> {
        com.example.mobileapp.core.data.local.RoomRunSessionRepository(get())
    }
    single<com.example.mobileapp.core.data.local.QuestRepository> {
        com.example.mobileapp.core.data.local.RoomQuestRepository(get(), get())
    }
    single<com.example.mobileapp.core.data.local.AchievementRepository> {
        com.example.mobileapp.core.data.local.RoomAchievementRepository(get(), get())
    }
    single<com.example.mobileapp.core.data.local.ActiveRunRepository> {
        com.example.mobileapp.core.data.local.RoomActiveRunRepository(get())
    }

    single<HexIndexer> { UberH3HexIndexer() }

    single { StepSensorManager(get()) }
    single { LocationTrackingManager(get()) }

    single { HexCaptureEngine(get(), get(), get(), get()) }

    // Process-lifetime owner of the active run's identity + wall-clock timing;
    // starts/stops the foreground tracking service. Context resolves to the
    // application context registered by androidContext() in FitQuestApp.
    single { ActiveRunController(get(), get(), get()) }

    // Networking: Retrofit/OkHttp against the configurable backend URL.
    // Android never sees DATABASE_URL or Supabase credentials, and the
    // deferred-auth backend needs no auth headers for the dev user.
    single<FitQuestApi> { FitQuestApiClient.create(BuildConfig.BACKEND_BASE_URL) }
    single { RunSyncer(get()) }
    // Foreground reconciliation of unsynced runs (Fix A): single-flight,
    // replayed through RunSyncer, triggered from MainActivity.onStart.
    single { RunReconciler(get(), get(), get()) }
    single { com.example.mobileapp.core.network.LeaderboardFetcher(get()) }
    single { com.example.mobileapp.core.network.MapTerritoryFetcher(get()) }
    single { com.example.mobileapp.core.network.RecommendationFetcher(get()) }
    single { com.example.mobileapp.core.network.CoachFetcher(get()) }
    // Fix E: process-lifetime coach cache so Home navigation alone never
    // re-triggers the expensive AI-coach GET/LLM generation. Kept as a
    // singleton (like the fetcher) so its Success survives tab switches.
    single { com.example.mobileapp.core.network.CoachCache(get(), get()) }

    // M8.3B: real-time coaching WebSocket. The LIVE push slot is a separate
    // singleton from the pull CoachCache above — a pushed response represents
    // a different trigger/context and must not corrupt the pull cache's
    // synced-run signature bookkeeping. Connect/disconnect is driven from
    // MainActivity.onStart/onStop (one logical connection per process).
    single { LiveCoachStore() }
    single {
        // WebSockets are long-lived: the default HTTP read timeout would kill
        // an idle connection, so it is disabled and OkHttp pings to keep the
        // socket (and NAT mapping) alive instead.
        val wsOkHttp = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .writeTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(30, TimeUnit.SECONDS)
            .build()
        val store = get<LiveCoachStore>()
        CoachingWsClient(
            url = coachingWsUrl(BuildConfig.BACKEND_BASE_URL),
            socketFactory = OkHttpCoachingSocketFactory(wsOkHttp),
            messageParser = CoachingWsMessageParser::parse,
            onLiveCoach = store::publish,
            onStatusChanged = { Log.d("CoachingWs", "status=$it") },
            scope = AppScope,
        )
    }

    // M8.5: per-foreground freshness ordering. MainActivity.onStart drives this
    // instead of the WS/RunReconciler directly: open the live channel before
    // replaying unsynced runs, then refresh the pull coach once when a newly
    // credited run advanced the synced signature (fresh pull when no push came).
    single {
        val ws = get<CoachingWsClient>()
        val reconciler = get<RunReconciler>()
        val cache = get<com.example.mobileapp.core.network.CoachCache>()
        com.example.mobileapp.core.network.CoachForegroundCoordinator(
            openLiveChannel = { ws.connect() },
            reconcileUnsyncedRuns = { reconciler.reconcileUnsyncedRuns() },
            refreshPullAfterNewRun = { cache.ensureLoaded() },
        )
    }

    // M8.4: native Android text-to-speech for live coaching messages. One
    // process-lifetime chain: the gate is pure dedupe logic, the synthesizer
    // wraps android.speech.tts bound to the application context (never an
    // Activity, so it cannot leak across navigation), and the controller
    // observes the EXISTING LiveCoachStore flow and speaks each genuinely new
    // coaching_message. FitQuestApp resolves the controller at startup so TTS
    // is initialised once per process — navigation/recomposition never
    // re-initialises it.
    single { CoachingSpeechGate() }
    single<TtsSynthesizer> { AndroidTtsSynthesizer(get()) }
    single {
        CoachingSpeechController(
            liveCoachStore = get(),
            synthesizer = get(),
            gate = get(),
            scope = AppScope,
        )
    }

    // factory (not single) so Voyager can properly scope and dispose the
    // ScreenModel when the screen leaves the backstack. A singleton would keep
    // the Orbit container alive forever and cause stale state on re-entry.
    factory {
        CaptureScreenModel(
            get(), get(), get(), get(), get(), get(), get(), get(), get(),
            get(), get()
        )
    }
}



