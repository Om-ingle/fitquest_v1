package com.example.mobileapp.ui.capture

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Color as AndroidColor
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import cafe.adriel.voyager.koin.koinScreenModel
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.navigator.LocalNavigator
import cafe.adriel.voyager.navigator.currentOrThrow
import com.example.mobileapp.BuildConfig
import com.example.mobileapp.core.network.ViewportBounds
import com.example.mobileapp.core.permissions.PermissionManager
import com.example.mobileapp.core.run.RunTiming
import com.example.mobileapp.features.capture.CaptureScreenModel
import com.example.mobileapp.features.capture.CaptureState
import org.orbitmvi.orbit.compose.collectAsState
import org.maplibre.geojson.FeatureCollection
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapLibreMapOptions
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.layers.FillLayer
import org.maplibre.android.style.layers.LineLayer
import org.maplibre.android.style.layers.SymbolLayer
import org.maplibre.android.style.layers.PropertyFactory.fillColor
import org.maplibre.android.style.layers.PropertyFactory.fillOpacity
import org.maplibre.android.style.layers.PropertyFactory.lineColor
import org.maplibre.android.style.layers.PropertyFactory.lineOpacity
import org.maplibre.android.style.layers.PropertyFactory.lineWidth
import org.maplibre.android.style.layers.PropertyFactory.textColor
import org.maplibre.android.style.layers.PropertyFactory.textField
import org.maplibre.android.style.layers.PropertyFactory.textSize
import org.maplibre.android.style.sources.GeoJsonSource

// ─────────────────────────────────────────────────────────────────────────────
// Top-level screen: permission gate → map
// ─────────────────────────────────────────────────────────────────────────────

class CurrentRunScreen : Screen {
    @SuppressLint("MissingPermission")
    @Composable
    override fun Content() {
        val modifier: Modifier = Modifier
        val screenModel = koinScreenModel<CaptureScreenModel>()
        val context = LocalContext.current
    var permissionsGranted by remember { mutableStateOf(PermissionManager.hasAllPermissions(context)) }
    var permanentlyDenied by remember { mutableStateOf(false) }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        val allGranted = results.values.all { it }
        permissionsGranted = allGranted
        if (!allGranted) {
            // If the user denied without "Don't ask again", the launcher will just
            // re-prompt next time. We mark permanently denied only when a permission
            // is fully denied (the system won't show the dialog again).
            permanentlyDenied = true
        }
    }

    if (!permissionsGranted) {
        PermissionGateScreen(
            permanentlyDenied = permanentlyDenied,
            onRequestPermissions = {
                permissionLauncher.launch(PermissionManager.REQUIRED_PERMISSIONS)
            },
            onOpenSettings = {
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.fromParts("package", context.packageName, null)
                }
                context.startActivity(intent)
            }
        )
        return
    }

    val state by screenModel.collectAsState()
    val navigator = LocalNavigator.currentOrThrow

    Box(modifier = modifier.fillMaxSize()) {
        CaptureMap(
            state = state,
            screenModel = screenModel,
            modifier = Modifier.fillMaxSize()
        )

        // Top Navigation Bar (Back button)
        Row(
            modifier = Modifier
                .align(Alignment.TopStart)
                .statusBarsPadding()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(
                onClick = {
                    if (state.isTracking) {
                        screenModel.onToggleTracking()
                    }
                    navigator.pop()
                },
                modifier = Modifier
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.85f))
            ) {
                Text("✕", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            }
        }

        // Live HUD card
        ElevatedCard(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .statusBarsPadding()
                .padding(top = 16.dp, start = 64.dp, end = 16.dp),
            shape = RoundedCornerShape(16.dp)
        ) {
            Column(
                modifier = Modifier.padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = if (state.isTracking) "ACTIVE RUN" else "STANDBY",
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.Bold,
                        color = if (state.isTracking) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline
                    )
                    Text(
                        text = formatDuration(state.durationSeconds),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    Column {
                        Text("Steps", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("${state.sessionSteps}", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    }
                    Column {
                        Text("Distance", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(String.format("%.2f km", state.distanceMeters / 1000.0), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    }
                    Column {
                        Text("Calories", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("${state.caloriesBurned} kcal", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    }
                    Column {
                        Text("Hexes", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("+${state.sessionCapturedHexes.size}", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                    }
                }

                Text(
                    text = "Current Hex: ${state.currentHexId?.take(8) ?: "Scanning..."}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )

                // Shared-map status: a server failure never blocks the local
                // run — it only degrades to local-only rendering.
                if (state.sharedMapFetchFailed) {
                    Text(
                        text = "Shared map unavailable — showing local territory",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.error
                    )
                } else if (state.isFetchingSharedMap) {
                    Text(
                        text = "Syncing territory map…",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }

        // Bottom Controls. Hidden while a process-death recovery prompt is up —
        // starting a fresh run over a pending recovery would silently discard it.
        if (state.pendingRecovery == null) {
            Row(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 32.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                if (state.isTracking) {
                    FilledTonalButton(
                        onClick = screenModel::onTogglePause,
                        shape = RoundedCornerShape(24.dp)
                    ) {
                        Text(if (state.isPaused) "Resume" else "Pause")
                    }
                }

                ExtendedFloatingActionButton(
                    onClick = screenModel::onToggleTracking,
                    containerColor = if (state.isTracking) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                    contentColor = Color.White,
                    shape = RoundedCornerShape(28.dp)
                ) {
                    Text(
                        text = if (state.isTracking) "Stop & Finish" else "Start Capture",
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }

        // ── Process-death recovery prompt ────────────────────────────────
        // A Room checkpoint was found but the capture engine is not live. Show
        // what was recovered (never a silent 00:00) and let the user resume or
        // discard. Drawn over the whole screen so no live-run control is active.
        state.pendingRecovery?.let { recovery ->
            val recoveredElapsed = RunTiming.fromCheckpoint(recovery).elapsedSeconds()
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.5f)),
                contentAlignment = Alignment.Center
            ) {
                Card(
                    modifier = Modifier
                        .padding(24.dp)
                        .fillMaxWidth(),
                    shape = RoundedCornerShape(20.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(
                        modifier = Modifier.padding(20.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text("🏃 Previous Run Found", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                        Text(
                            text = "Your run was still in progress when the app was closed.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            textAlign = TextAlign.Center
                        )
                        Card(
                            modifier = Modifier.fillMaxWidth(),
                            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f))
                        ) {
                            Column(
                                modifier = Modifier.padding(12.dp),
                                verticalArrangement = Arrangement.spacedBy(4.dp)
                            ) {
                                Text("Steps: ${recovery.sessionSteps}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                                Text(
                                    "Distance: ${String.format("%.2f km", recovery.distanceMeters / 1000.0)}",
                                    style = MaterialTheme.typography.bodyMedium
                                )
                                Text("Elapsed: ${formatDuration(recoveredElapsed)}", style = MaterialTheme.typography.bodyMedium)
                                if (recovery.isPaused) {
                                    Text("Status: Paused", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.error)
                                }
                            }
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Button(
                            onClick = screenModel::onResumeRecovery,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("Resume Run", fontWeight = FontWeight.Bold)
                        }
                        FilledTonalButton(
                            onClick = screenModel::onDiscardRecovery,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("Discard Run")
                        }
                    }
                }
            }
        }

        // Post-Run Victory Summary Dialog
        if (state.showSummaryDialog && state.latestCompletedSession != null) {
            val session = state.latestCompletedSession!!
            AlertDialog(
                onDismissRequest = {
                    screenModel.dismissSummaryDialog()
                    navigator.pop()
                },
                title = {
                    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                        Text("🎉 Run Completed!", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.headlineSmall)
                        Text("Session territory saved", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                text = {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Card(
                            modifier = Modifier.fillMaxWidth(),
                            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f))
                        ) {
                            Column(modifier = Modifier.padding(12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                Text("+${session.xpEarned} XP Earned", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                                Text("${session.capturedHexCount} Hexagons Conquered", style = MaterialTheme.typography.bodySmall)
                                // Backend is authoritative: show whether the
                                // server confirmed this XP or it is a local
                                // provisional estimate (offline run).
                                Text(
                                    text = if (session.isSynced) "✓ Synced with server" else "Saved offline — provisional XP (no auto-retry)",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }

                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Total Steps", style = MaterialTheme.typography.bodyMedium)
                            Text("${session.totalSteps}", fontWeight = FontWeight.Bold)
                        }
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Distance Covered", style = MaterialTheme.typography.bodyMedium)
                            Text(String.format("%.2f km", session.distanceMeters / 1000.0), fontWeight = FontWeight.Bold)
                        }
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Duration", style = MaterialTheme.typography.bodyMedium)
                            Text(formatDuration(session.durationSeconds), fontWeight = FontWeight.Bold)
                        }
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Active Calories", style = MaterialTheme.typography.bodyMedium)
                            Text("${session.caloriesBurned} kcal", fontWeight = FontWeight.Bold)
                        }

                        if (state.unlockedAchievements.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(4.dp))
                            Text("🏆 Achievements Unlocked:", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelLarge)
                            state.unlockedAchievements.forEach { ach ->
                                Text("• ${ach.title}: ${ach.description}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                            }
                        }
                    }
                },
                confirmButton = {
                    Button(
                        onClick = {
                            screenModel.dismissSummaryDialog()
                            navigator.pop()
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("View Hub & Stats")
                    }
                }
            )
        }
    }
}
}

private fun formatDuration(seconds: Long): String {
    val mins = seconds / 60
    val secs = seconds % 60
    val hours = mins / 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, mins % 60, secs)
    } else {
        String.format("%02d:%02d", mins, secs)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Permission gate UI
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun PermissionGateScreen(
    permanentlyDenied: Boolean,
    onRequestPermissions: () -> Unit,
    onOpenSettings: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(32.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "FitQuest needs your location, step and notification data to track which hexagons you capture and to keep your run alive in the background.",
                style = MaterialTheme.typography.bodyLarge,
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.height(24.dp))
            if (permanentlyDenied) {
                Text(
                    text = "Permissions were denied. Please enable them in Settings.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(12.dp))
                Button(onClick = onOpenSettings) {
                    Text("Open Settings")
                }
            } else {
                Button(onClick = onRequestPermissions) {
                    Text("Grant Permissions")
                }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────────────
// Standard Map Style (CARTO Voyager / OSM raster tiles - zero API key/env dependency)
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// Vector Map Styles (MapTiler Streets-v2 vector style with OpenFreeMap Liberty fallback)
// ─────────────────────────────────────────────────────────────────────────────

private const val OPEN_VECTOR_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty"

// ─────────────────────────────────────────────────────────────────────────────
// Map composable
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun CaptureMap(
    state: CaptureState,
    screenModel: CaptureScreenModel,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var mapInstance by remember { mutableStateOf<MapLibreMap?>(null) }
    var isMapReady by remember { mutableStateOf(false) }

    val primaryVectorStyle = remember {
        if (BuildConfig.MAPTILER_STYLE_URL.isNotBlank()) {
            BuildConfig.MAPTILER_STYLE_URL
        } else if (BuildConfig.MAPTILER_API_KEY.isNotBlank()) {
            "https://api.maptiler.com/maps/streets-v2/style.json?key=${BuildConfig.MAPTILER_API_KEY}"
        } else {
            OPEN_VECTOR_STYLE_URL
        }
    }

    val mapView = remember {
        val options = MapLibreMapOptions.createFromAttributes(context)
            .textureMode(true)
        MapView(context, options).apply {
            onCreate(null)
        }
    }

    DisposableEffect(lifecycleOwner, mapView) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> mapView.onStart()
                Lifecycle.Event.ON_RESUME -> mapView.onResume()
                Lifecycle.Event.ON_PAUSE -> mapView.onPause()
                Lifecycle.Event.ON_STOP -> mapView.onStop()
                Lifecycle.Event.ON_DESTROY -> mapView.onDestroy()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        if (lifecycleOwner.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
            mapView.onStart()
        }
        if (lifecycleOwner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) {
            mapView.onResume()
        }
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            mapView.onDestroy()
        }
    }

    Box(modifier = modifier) {
        AndroidView(
            factory = {
                mapView.apply {
                    getMapAsync { mapLibreMap ->
                        mapInstance = mapLibreMap

                        mapLibreMap.setStyle(Style.Builder().fromUri(primaryVectorStyle)) { style ->
                            ensureHexLayers(style)
                            isMapReady = true

                            if (state.nearbyHexGeoJson.isNotEmpty()) {
                                style.getSourceAs<GeoJsonSource>(NEARBY_HEX_SOURCE_ID)?.setGeoJson(state.nearbyHexGeoJson)
                            }
                            if (state.capturedHexGeoJson.isNotEmpty()) {
                                style.getSourceAs<GeoJsonSource>(HEX_SOURCE_ID)?.setGeoJson(state.capturedHexGeoJson)
                            }
                            if (state.currentHexGeoJson.isNotEmpty()) {
                                style.getSourceAs<GeoJsonSource>(CURRENT_HEX_SOURCE_ID)?.setGeoJson(state.currentHexGeoJson)
                            }

                            // Shared map: request the server viewport once the
                            // style is ready, then re-request whenever the
                            // camera settles. The ScreenModel dedupes
                            // (meaningful-change check + zoom < 14 guard), so
                            // tiny movements and zoomed-out views issue no
                            // request.
                            requestSharedTerritoryViewport(mapLibreMap, screenModel)
                            mapLibreMap.addOnCameraIdleListener {
                                requestSharedTerritoryViewport(mapLibreMap, screenModel)
                            }
                        }

                        // Add fallback if primary style fails
                        addOnDidFailLoadingMapListener {
                            if (primaryVectorStyle != OPEN_VECTOR_STYLE_URL) {
                                mapLibreMap.setStyle(Style.Builder().fromUri(OPEN_VECTOR_STYLE_URL)) { fallbackStyle ->
                                    ensureHexLayers(fallbackStyle)
                                    isMapReady = true

                                    // The primary style callback never ran, so
                                    // wire the shared-viewport requests here.
                                    requestSharedTerritoryViewport(mapLibreMap, screenModel)
                                    mapLibreMap.addOnCameraIdleListener {
                                        requestSharedTerritoryViewport(mapLibreMap, screenModel)
                                    }
                                }
                            }
                        }

                        state.currentLocation?.let { loc ->
                            mapLibreMap.cameraPosition = CameraPosition.Builder()
                                .target(LatLng(loc.latitude, loc.longitude))
                                .zoom(16.0)
                                .build()
                        }
                    }
                }
            },
            modifier = Modifier.fillMaxSize()
        )

        // Center / track camera when real location arrives
        var initialCameraSet by remember { mutableStateOf(false) }
        LaunchedEffect(state.currentLocation, mapInstance) {
            val map = mapInstance ?: return@LaunchedEffect
            val loc = state.currentLocation ?: return@LaunchedEffect
            val target = LatLng(loc.latitude, loc.longitude)
            if (!initialCameraSet) {
                map.cameraPosition = CameraPosition.Builder()
                    .target(target)
                    .zoom(16.0)
                    .build()
                initialCameraSet = true
            } else if (state.isTracking) {
                map.animateCamera(CameraUpdateFactory.newLatLng(target), 400)
            }
        }

        // Push pre-computed GeoJSON strings to map sources when ready
        LaunchedEffect(state.nearbyHexGeoJson, isMapReady) {
            if (!isMapReady) return@LaunchedEffect
            mapInstance?.getStyle { style ->
                ensureHexLayers(style)
                if (state.nearbyHexGeoJson.isNotEmpty()) {
                    style.getSourceAs<GeoJsonSource>(NEARBY_HEX_SOURCE_ID)
                        ?.setGeoJson(state.nearbyHexGeoJson)
                }
            }
        }

        LaunchedEffect(state.capturedHexGeoJson, isMapReady) {
            if (!isMapReady) return@LaunchedEffect
            mapInstance?.getStyle { style ->
                ensureHexLayers(style)
                if (state.capturedHexGeoJson.isNotEmpty()) {
                    style.getSourceAs<GeoJsonSource>(HEX_SOURCE_ID)
                        ?.setGeoJson(state.capturedHexGeoJson)
                }
            }
        }

        LaunchedEffect(state.currentHexGeoJson, isMapReady) {
            if (!isMapReady) return@LaunchedEffect
            mapInstance?.getStyle { style ->
                ensureHexLayers(style)
                if (state.currentHexGeoJson.isNotEmpty()) {
                    style.getSourceAs<GeoJsonSource>(CURRENT_HEX_SOURCE_ID)
                        ?.setGeoJson(state.currentHexGeoJson)
                }
            }
        }

        // Rival territory from the server. Unlike the local layers above,
        // an empty string means "no rivals in viewport" and must actively
        // clear the source (setGeoJson("") throws, so push an empty
        // FeatureCollection) — otherwise stale hexes would linger.
        LaunchedEffect(state.multiplayerGeoJson, isMapReady) {
            if (!isMapReady) return@LaunchedEffect
            mapInstance?.getStyle { style ->
                ensureHexLayers(style)
                val source = style.getSourceAs<GeoJsonSource>(RIVAL_HEX_SOURCE_ID)
                if (state.multiplayerGeoJson.isNotEmpty()) {
                    source?.setGeoJson(state.multiplayerGeoJson)
                } else {
                    source?.setGeoJson(FeatureCollection.fromFeatures(emptyList()))
                }
            }
        }

        // Server-confirmed own territory. Same explicit-clear reasoning.
        LaunchedEffect(state.myServerHexesGeoJson, isMapReady) {
            if (!isMapReady) return@LaunchedEffect
            mapInstance?.getStyle { style ->
                ensureHexLayers(style)
                val source = style.getSourceAs<GeoJsonSource>(MY_SERVER_HEX_SOURCE_ID)
                if (state.myServerHexesGeoJson.isNotEmpty()) {
                    source?.setGeoJson(state.myServerHexesGeoJson)
                } else {
                    source?.setGeoJson(FeatureCollection.fromFeatures(emptyList()))
                }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Map layer setup
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Idempotently adds all hex-related sources and layers.
 *
 * Layer order (bottom → top):
 *  1. Nearby hex grid outlines (subtle grey)
 *  2. Captured hex fills (green — local Room data)
 *  3. Rival territory fills + owner labels (red — server viewport)
 *  4. My server-confirmed territory fills + labels (blue — server viewport)
 *  5. Current hex fill (orange)
 */
private fun ensureHexLayers(style: Style) {
    // --- Nearby hex grid (outline only) ---
    if (style.getSource(NEARBY_HEX_SOURCE_ID) == null) {
        style.addSource(GeoJsonSource(NEARBY_HEX_SOURCE_ID))
    }
    if (style.getLayer(NEARBY_HEX_OUTLINE_LAYER_ID) == null) {
        val nearbyOutline = LineLayer(NEARBY_HEX_OUTLINE_LAYER_ID, NEARBY_HEX_SOURCE_ID)
            .withProperties(
                lineColor(AndroidColor.parseColor("#455A64")),
                lineWidth(1.2f),
                lineOpacity(0.35f)
            )
        style.addLayer(nearbyOutline)
    }

    // --- Captured hexes (green fill) ---
    if (style.getSource(HEX_SOURCE_ID) == null) {
        style.addSource(GeoJsonSource(HEX_SOURCE_ID))
    }
    if (style.getLayer(HEX_FILL_LAYER_ID) == null) {
        val capturedHexLayer = FillLayer(HEX_FILL_LAYER_ID, HEX_SOURCE_ID).withProperties(
            fillColor(AndroidColor.parseColor("#00C853")),
            fillOpacity(0.35f)
        )
        style.addLayer(capturedHexLayer)
    }

    // --- Rival territory (server viewport; red fill + username label) ---
    // Color is fixed by role (rival vs me), never derived from usernames.
    if (style.getSource(RIVAL_HEX_SOURCE_ID) == null) {
        style.addSource(GeoJsonSource(RIVAL_HEX_SOURCE_ID))
    }
    if (style.getLayer(RIVAL_HEX_FILL_LAYER_ID) == null) {
        val rivalFill = FillLayer(RIVAL_HEX_FILL_LAYER_ID, RIVAL_HEX_SOURCE_ID).withProperties(
            fillColor(AndroidColor.parseColor("#FF5252")),
            fillOpacity(0.30f)
        )
        style.addLayer(rivalFill)
    }
    if (style.getLayer(RIVAL_HEX_LABEL_LAYER_ID) == null) {
        val rivalLabel = SymbolLayer(RIVAL_HEX_LABEL_LAYER_ID, RIVAL_HEX_SOURCE_ID).withProperties(
            textField("{owner}"),
            textSize(11f),
            textColor(AndroidColor.parseColor("#FF5252"))
        )
        style.addLayer(rivalLabel)
    }

    // --- My server-confirmed territory (blue fill + "YOU" label) ---
    if (style.getSource(MY_SERVER_HEX_SOURCE_ID) == null) {
        style.addSource(GeoJsonSource(MY_SERVER_HEX_SOURCE_ID))
    }
    if (style.getLayer(MY_SERVER_HEX_FILL_LAYER_ID) == null) {
        val myServerFill = FillLayer(MY_SERVER_HEX_FILL_LAYER_ID, MY_SERVER_HEX_SOURCE_ID).withProperties(
            fillColor(AndroidColor.parseColor("#00B0FF")),
            fillOpacity(0.30f)
        )
        style.addLayer(myServerFill)
    }
    if (style.getLayer(MY_SERVER_HEX_LABEL_LAYER_ID) == null) {
        val myServerLabel = SymbolLayer(MY_SERVER_HEX_LABEL_LAYER_ID, MY_SERVER_HEX_SOURCE_ID).withProperties(
            textField("{owner}"),
            textSize(11f),
            textColor(AndroidColor.parseColor("#00B0FF"))
        )
        style.addLayer(myServerLabel)
    }

    // --- Current hex (orange fill) ---
    if (style.getSource(CURRENT_HEX_SOURCE_ID) == null) {
        style.addSource(GeoJsonSource(CURRENT_HEX_SOURCE_ID))
    }
    if (style.getLayer(CURRENT_HEX_FILL_LAYER_ID) == null) {
        val currentHexLayer = FillLayer(CURRENT_HEX_FILL_LAYER_ID, CURRENT_HEX_SOURCE_ID)
            .withProperties(
                fillColor(AndroidColor.parseColor("#FFA500")),
                fillOpacity(0.5f)
            )
        style.addLayer(currentHexLayer)
    }
}

/**
 * Reports the current visible bounds + zoom to the ScreenModel, which
 * decides whether the change justifies a server viewport request.
 */
private fun requestSharedTerritoryViewport(mapLibreMap: MapLibreMap, screenModel: CaptureScreenModel) {
    val camera = mapLibreMap.cameraPosition
    val bounds = mapLibreMap.projection.visibleRegion.latLngBounds
    screenModel.onViewportChanged(
        ViewportBounds(
            minLat = bounds.latitudeSouth,
            minLng = bounds.longitudeWest,
            maxLat = bounds.latitudeNorth,
            maxLng = bounds.longitudeEast,
            zoomLevel = camera.zoom
        )
    )
}

private const val HEX_SOURCE_ID = "captured-hex-source"
private const val HEX_FILL_LAYER_ID = "captured-hex-fill-layer"
private const val CURRENT_HEX_SOURCE_ID = "current-hex-source"
private const val CURRENT_HEX_FILL_LAYER_ID = "current-hex-fill-layer"
private const val NEARBY_HEX_SOURCE_ID = "nearby-hex-source"
private const val NEARBY_HEX_OUTLINE_LAYER_ID = "nearby-hex-outline-layer"
private const val RIVAL_HEX_SOURCE_ID = "rival-hex-source"
private const val RIVAL_HEX_FILL_LAYER_ID = "rival-hex-fill-layer"
private const val RIVAL_HEX_LABEL_LAYER_ID = "rival-hex-label-layer"
private const val MY_SERVER_HEX_SOURCE_ID = "my-server-hex-source"
private const val MY_SERVER_HEX_FILL_LAYER_ID = "my-server-hex-fill-layer"
private const val MY_SERVER_HEX_LABEL_LAYER_ID = "my-server-hex-label-layer"
