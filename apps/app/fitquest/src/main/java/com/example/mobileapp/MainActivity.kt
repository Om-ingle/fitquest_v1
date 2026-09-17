package com.example.mobileapp

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.lifecycleScope
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.navigator.Navigator
import cafe.adriel.voyager.transitions.SlideTransition
import com.example.mobileapp.core.auth.AuthSession
import com.example.mobileapp.core.auth.AuthState
import com.example.mobileapp.core.capture.HexCaptureEngine
import com.example.mobileapp.core.data.local.ActiveRunRepository
import com.example.mobileapp.core.data.local.UserProfileRepository
import com.example.mobileapp.core.network.CoachForegroundCoordinator
import com.example.mobileapp.core.network.CoachingWsClient
import com.example.mobileapp.core.run.RunNotifications
import com.example.mobileapp.ui.auth.LoginScreen
import com.example.mobileapp.ui.auth.OnboardingScreen
import com.example.mobileapp.ui.capture.CurrentRunScreen
import com.example.mobileapp.ui.main.MainHubScreen
import com.example.mobileapp.ui.theme.MobileAppTheme
import kotlinx.coroutines.launch
import org.koin.android.ext.android.inject

class MainActivity : ComponentActivity() {

    private val userProfileRepository: UserProfileRepository by inject()
    private val activeRunRepository: ActiveRunRepository by inject()
    private val hexCaptureEngine: HexCaptureEngine by inject()
    // M8.5: per-foreground coaching-freshness ordering (open the live channel,
    // replay unsynced runs, refresh the pull coach once if a new run credited).
    private val coachForegroundCoordinator: CoachForegroundCoordinator by inject()
    // M8.3B: single process-scoped real-time coaching WebSocket, tied to the
    // activity's foreground so it is up while the user is in the app and
    // released on backgrounding (idempotent connect/disconnect — tab
    // navigation never duplicates it). Connect is initiated by the coordinator
    // above (before reconciliation); disconnect lives here on backgrounding.
    private val coachingWsClient: CoachingWsClient by inject()
    // M11 (F-04): the process's single session. MainActivity asks it who the
    // user is before deciding which screen to open, and watches it so a session
    // that ends mid-use returns the user to the login screen.
    private val authSession: AuthSession by inject()

    /** Live reference to the current Voyager [Navigator], for notification-tap deep links. */
    private var navigator: Navigator? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Action carried by a launcher/notification start before the first composition.
        val initialAction = intent?.action
        enableEdgeToEdge()
        observeAuthState()
        setContent {
            MobileAppTheme {
                var startScreen by remember { mutableStateOf<Screen>(MainHubScreen()) }
                var startScreenReady by remember { mutableStateOf(false) }

                LaunchedEffect(Unit) {
                    startScreen = resolveStartScreen(initialAction)
                    startScreenReady = true
                }

                if (startScreenReady) {
                    Navigator(startScreen) { nav ->
                        navigator = nav
                        SlideTransition(nav)
                    }
                } else {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator()
                    }
                }
            }
        }
    }

    /**
     * M11 (F-04) — keep the transport and the navigation in step with the
     * session.
     *
     * A session can end while the app is open (the refresh token is revoked, or
     * a refresh is explicitly rejected), and both of the things that depend on
     * it must follow:
     *
     *  1. the coaching WebSocket is authenticated as that user, so it must not
     *     outlive the session — leaving it open would keep a channel the user
     *     can no longer legitimately hold; and
     *  2. the UI must return to the login screen rather than sit on tabs whose
     *     every request now answers 401.
     *
     * Collected for the activity's lifetime: StateFlow replays its current value
     * on subscription, which also covers a session that was already gone before
     * the first composition.
     */
    private fun observeAuthState() {
        lifecycleScope.launch {
            authSession.state.collect { state ->
                if (state !is AuthState.SignedOut) return@collect
                coachingWsClient.disconnect()
                val nav = navigator ?: return@collect
                if (nav.lastItem !is LoginScreen) nav.replaceAll(LoginScreen())
            }
        }
    }

    /**
     * Fix A + M8.5: on every foreground, (1) open the real-time coaching
     * channel FIRST so a run credited by the replay below can still arrive as a
     * live push, then (2) replay any unsynced runs through the normal server
     * sync path (single-flight inside RunReconciler, off the main thread — a
     * run is marked synced only after the server confirms success and the
     * server dedupes on run_id, so it can never double-credit), and (3) if the
     * replay actually credited a new run, refresh the pull coach once so a
     * fresh response surfaces even when no live push arrives (WS down /
     * suppressed). Opening the channel is best-effort and never blocks or
     * aborts the replay — all ordering lives in CoachForegroundCoordinator.
     */
    override fun onStart() {
        super.onStart()
        lifecycleScope.launch { coachForegroundCoordinator.onForeground() }
    }

    override fun onStop() {
        super.onStop()
        // Backgrounded = nobody is looking at the Home coach card; drop the
        // socket (no reconnect scheduled until the next foreground).
        coachingWsClient.disconnect()
    }

    /**
     * Cold-start routing. Identity is resolved FIRST (M11): every route below
     * requires a verified token, so there is no app to open without a session.
     * [AuthSession.restore] reuses the stored session and refreshes it only if
     * the access token has actually expired, so a returning user goes straight
     * to the hub without a round trip in the common case.
     *
     * Then: an unfinished run (either a live in-process engine or a persisted
     * checkpoint from a process death) is surfaced directly on the run screen so
     * it is recovered instead of silently lost. Completed runs keep their normal
     * Room -> RunSyncer path through MainHubScreen.
     *
     * ### Onboarding is per account, and this is the line that decides it
     *
     * Every read below is scoped to the signed-in subject — `getProfile()` reads
     * the profile KEYED BY that account and creates a fresh default when the
     * account has never signed in here, and `getActiveRun()` looks for a
     * checkpoint owned by that account. So a device that has already been
     * through onboarding cannot hand that answer to the next account: no row
     * exists for it, `isOnboardingCompleted` is false, and it goes to
     * OnboardingScreen. The same applies to the run: the previous account's
     * checkpoint is still in the database and is simply not this account's.
     */
    private suspend fun resolveStartScreen(initialAction: String?): Screen {
        if (!authSession.restore()) return LoginScreen()

        val profile = userProfileRepository.getProfile()
        if (!profile.isOnboardingCompleted) return OnboardingScreen()

        val openRunRequested = initialAction == RunNotifications.ACTION_OPEN_RUN
        val engineAlreadyTracking = hexCaptureEngine.state.value.isTracking
        val checkpointExists = activeRunRepository.getActiveRun() != null
        val shouldOpenRunScreen =
            openRunRequested || engineAlreadyTracking || checkpointExists
        return if (shouldOpenRunScreen) CurrentRunScreen() else MainHubScreen()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action != RunNotifications.ACTION_OPEN_RUN) return
        // Warm tap on the run notification while the activity is already up.
        // The run screen is normally the top screen already; push it only if
        // the user has navigated away (still tracking in the background).
        val nav = navigator ?: return
        if (nav.lastItem !is CurrentRunScreen) {
            nav.push(CurrentRunScreen())
        }
    }
}
