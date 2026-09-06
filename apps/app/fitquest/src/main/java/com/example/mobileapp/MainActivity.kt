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
import com.example.mobileapp.core.capture.HexCaptureEngine
import com.example.mobileapp.core.data.local.ActiveRunRepository
import com.example.mobileapp.core.data.local.UserProfileRepository
import com.example.mobileapp.core.network.RunReconciler
import com.example.mobileapp.core.run.RunNotifications
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
    private val runReconciler: RunReconciler by inject()

    /** Live reference to the current Voyager [Navigator], for notification-tap deep links. */
    private var navigator: Navigator? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Action carried by a launcher/notification start before the first composition.
        val initialAction = intent?.action
        enableEdgeToEdge()
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
     * Fix A: on every foreground, replay any unsynced runs through the normal
     * server sync path (single-flight inside RunReconciler, off the main
     * thread). A run is marked synced only after the server confirms success,
     * and the server dedupes on run_id — so foreground reconciliation can
     * never double-credit. It runs off the main thread and returns immediately
     * when there is nothing to replay.
     */
    override fun onStart() {
        super.onStart()
        lifecycleScope.launch { runReconciler.reconcileUnsyncedRuns() }
    }

    /**
     * Cold-start routing. An unfinished run (either a live in-process engine or
     * a persisted checkpoint from a process death) is surfaced directly on the
     * run screen so it is recovered instead of silently lost. Completed runs
     * keep their normal Room -> RunSyncer path through MainHubScreen.
     */
    private suspend fun resolveStartScreen(initialAction: String?): Screen {
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
