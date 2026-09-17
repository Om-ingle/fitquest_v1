package com.example.mobileapp.di

import android.util.Log
import androidx.room.Room
import com.example.mobileapp.BuildConfig
import com.example.mobileapp.core.auth.AuthInterceptor
import com.example.mobileapp.core.auth.AuthSession
import com.example.mobileapp.core.auth.EncryptedTokenStore
import com.example.mobileapp.core.auth.SupabaseAuthClient
import com.example.mobileapp.core.auth.TokenRefreshAuthenticator
import com.example.mobileapp.core.auth.TokenStore
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
import okhttp3.Authenticator
import okhttp3.Interceptor
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
                FitQuestDatabase.MIGRATION_4_5,
                FitQuestDatabase.MIGRATION_5_6
            )
            // NO fallbackToDestructiveMigration(). It was removed in v6 on
            // purpose. With it, any migration gap — a version bump without a
            // Migration, or one whose result does not match the entities — makes
            // Room silently DROP AND RECREATE every table, i.e. delete the
            // user's whole local history, and the only evidence is a log line.
            // Now the same mistake throws IllegalStateException naming the table
            // and column, and the app fails loudly instead of quietly losing
            // data. MIGRATION_5_6 deliberately quarantines the rows it cannot
            // attribute rather than deleting them; a destructive fallback
            // underneath that would undo the guarantee it exists to provide.
            .build()
    }
    single { get<FitQuestDatabase>().hexDao() }
    single { get<FitQuestDatabase>().userDao() }
    single { get<FitQuestDatabase>().runSessionDao() }
    single { get<FitQuestDatabase>().dailyQuestDao() }
    single { get<FitQuestDatabase>().achievementDao() }
    single { get<FitQuestDatabase>().activeRunDao() }

    // ── M11 follow-up: account-scoped local storage ──────────────────────────
    // Every repository below resolves the signed-in account from this and scopes
    // its reads and writes to it. Registered under the IdentityProvider
    // interface because that is the type the repositories declare — the same
    // declared-type rule that the OkHttp bindings below had to be corrected for.
    single<com.example.mobileapp.core.auth.IdentityProvider> { get<AuthSession>() }

    // The gate the account-scoped surfaces (CoachCache, LiveCoachStore, the live
    // run) read before they will acquire anything. Closed by default, and opened
    // only by AccountScopeCoordinator once its collector is actually running —
    // so a process in which that coordinator never starts has three EMPTY
    // surfaces rather than three stale ones. That is the fail-closed direction:
    // the previous design left the surfaces holding data and relied on a control
    // to clear them, which is how a coordinator that failed to construct became
    // a silent privacy hole.
    single { com.example.mobileapp.core.session.AccountScopeGuard() }

    single<HexRepository> { RoomHexRepository(get(), get()) }
    single<com.example.mobileapp.core.data.local.UserProfileRepository> {
        com.example.mobileapp.core.data.local.RoomUserProfileRepository(get(), get())
    }
    single<com.example.mobileapp.core.data.local.RunSessionRepository> {
        com.example.mobileapp.core.data.local.RoomRunSessionRepository(get(), get())
    }
    single<com.example.mobileapp.core.data.local.QuestRepository> {
        com.example.mobileapp.core.data.local.RoomQuestRepository(get(), get(), get())
    }
    single<com.example.mobileapp.core.data.local.AchievementRepository> {
        com.example.mobileapp.core.data.local.RoomAchievementRepository(get(), get(), get())
    }
    single<com.example.mobileapp.core.data.local.ActiveRunRepository> {
        com.example.mobileapp.core.data.local.RoomActiveRunRepository(get(), get())
    }

    single<HexIndexer> { UberH3HexIndexer() }

    single { StepSensorManager(get()) }
    single { LocationTrackingManager(get()) }

    single { HexCaptureEngine(get(), get(), get(), get()) }
    // The narrow slice ActiveRunController declares. Registered under the
    // interface because that is the declared parameter type — resolving
    // `HexCaptureEngine` for it would fail, the same way the OkHttp bindings
    // below did before they were corrected.
    single<com.example.mobileapp.core.capture.RunSessionEngine> { get<HexCaptureEngine>() }

    // Process-lifetime owner of the active run's identity + wall-clock timing;
    // starts/stops the foreground tracking service. Takes IdentityProvider so it
    // can record WHICH account started the run — that is what lets it drop the
    // live run when the account changes without touching the checkpoint the
    // departing account left behind. The service launcher is a seam so that
    // decision is testable without a Context.
    // Registered under the RunServiceLauncher INTERFACE, not the concrete
    // ForegroundRunServiceLauncher: ActiveRunController declares the interface
    // as its parameter type, and Koin resolves `get()` against the DECLARED
    // type. Binding only the concrete class left the graph with no definition
    // for RunServiceLauncher, so ActiveRunController — and therefore
    // AccountScopeCoordinator, which depends on it — could not be constructed.
    // This is the third instance of that mistake in this module (the OkHttp
    // Interceptor/Authenticator pair, then RunSessionEngine), which is why
    // DeclaredTypeBindingTest now enforces the rule mechanically instead of
    // relying on it being remembered at each new seam.
    single<com.example.mobileapp.core.run.RunServiceLauncher> {
        com.example.mobileapp.core.run.ForegroundRunServiceLauncher(get())
    }
    single { ActiveRunController(get(), get(), get(), get(), get()) }
    // Registered under the narrow interface the coordinator declares, so the
    // coordinator cannot reach the controller's other operations.
    single<com.example.mobileapp.core.run.ActiveRunAccountScope> { get<ActiveRunController>() }

    // ── M11 (F-04): authentication ───────────────────────────────────────────
    // One session per process, and exactly one place that can mint, replace or
    // destroy it. Everything below consumes it; nothing else owns identity.
    single<TokenStore> { EncryptedTokenStore(get()) }
    single {
        SupabaseAuthClient.create(
            supabaseUrl = BuildConfig.SUPABASE_URL,
            anonKey = BuildConfig.SUPABASE_ANON_KEY,
        )
    }
    single { AuthSession(get(), get()) }

    // M11 follow-up: the one thing that follows the signed-in account for the
    // caches that outlive a screen. Resolved eagerly in FitQuestApp so its
    // collector is installed at process start rather than at the first
    // account change — a subscription installed late is a subscription that
    // misses the transition it exists for.
    single {
        com.example.mobileapp.core.session.AccountScopeCoordinator(
            get(), get(), get(), get(), get(), AppScope
        )
    }

    // The two OkHttp collaborators every authenticated client shares. They are
    // singletons so the 401 refresh is single-flight across the whole process:
    // two clients holding two authenticators would each redeem the same
    // rotating refresh token and one of them would lose the session.
    //
    // Registered under the OkHttp INTERFACE types, not their concrete classes.
    // Koin resolves `get()` against the declared parameter type, and every
    // consumer declares the interface — `FitQuestApiClient.create` takes
    // `Interceptor`/`Authenticator` explicitly. Registering only the concrete
    // classes left the graph with no definition for `okhttp3.Interceptor`, so
    // building `FitQuestApi` threw NoBeanDefFoundException on the first
    // `MainActivity.onStart` and the app died at launch (M11, 2026-09-17).
    // `AppModuleGraphTest` resolves both clients from this module so that
    // cannot recur silently.
    single<Interceptor> { AuthInterceptor { get<AuthSession>().accessToken() } }
    single<Authenticator> {
        TokenRefreshAuthenticator(refresh = { failed -> get<AuthSession>().refreshBlocking(failed) })
    }

    // Networking: Retrofit/OkHttp against the configurable backend URL.
    // Android never holds a backend secret: the only Supabase value in the APK
    // is the publishable anon key, which identifies the project and confers no
    // authority — the user's access token is what the backend verifies.
    single<FitQuestApi> {
        FitQuestApiClient.create(
            baseUrl = BuildConfig.BACKEND_BASE_URL,
            authInterceptor = get(),
            authenticator = get(),
        )
    }
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
    single { com.example.mobileapp.core.network.CoachCache(get(), get(), get()) }

    // M8.3B: real-time coaching WebSocket. The LIVE push slot is a separate
    // singleton from the pull CoachCache above — a pushed response represents
    // a different trigger/context and must not corrupt the pull cache's
    // synced-run signature bookkeeping. Connect/disconnect is driven from
    // MainActivity.onStart/onStop (one logical connection per process).
    single { LiveCoachStore(get()) }
    single {
        // WebSockets are long-lived: the default HTTP read timeout would kill
        // an idle connection, so it is disabled and OkHttp pings to keep the
        // socket (and NAT mapping) alive instead.
        //
        // M11: this client carries the SAME auth interceptor and 401
        // authenticator as the REST client, so the WebSocket handshake presents
        // the session's bearer token in its headers — the backend refuses an
        // unauthenticated upgrade with close code 1008 — and a handshake
        // rejected because the token expired is refreshed and retried by
        // OkHttp rather than surfacing as a connect failure.
        val wsOkHttp = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .writeTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(30, TimeUnit.SECONDS)
            .addInterceptor(get<Interceptor>())
            .authenticator(get<Authenticator>())
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
        val session = get<AuthSession>()
        com.example.mobileapp.core.network.CoachForegroundCoordinator(
            // M11: only open the channel while a session exists. An
            // unauthenticated handshake is refused with 1008 and the client
            // stops there, so asking would be both pointless and noisy.
            // MainActivity restores the session before the first onStart, so a
            // returning user with a live session still connects immediately.
            openLiveChannel = { if (session.currentTokens() != null) ws.connect() },
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



