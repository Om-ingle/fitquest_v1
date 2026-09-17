package com.example.mobileapp.ui.auth

import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.koin.koinScreenModel
import cafe.adriel.voyager.navigator.LocalNavigator
import cafe.adriel.voyager.navigator.currentOrThrow
import com.example.mobileapp.core.data.local.AchievementRepository
import com.example.mobileapp.core.data.local.QuestRepository
import com.example.mobileapp.core.data.local.UserProfileEntity
import com.example.mobileapp.core.data.local.UserProfileRepository
import com.example.mobileapp.core.permissions.PermissionManager
import com.example.mobileapp.ui.main.MainHubScreen
import kotlinx.coroutines.launch
import org.koin.compose.koinInject

class OnboardingScreen : Screen {

    @Composable
    override fun Content() {
        val navigator = LocalNavigator.currentOrThrow
        val context = LocalContext.current
        val coroutineScope = rememberCoroutineScope()

        val userProfileRepo = koinInject<UserProfileRepository>()
        val questRepo = koinInject<QuestRepository>()
        val achievementRepo = koinInject<AchievementRepository>()

        var currentStep by remember { mutableIntStateOf(0) }

        // Profile Form State
        var codename by remember { mutableStateOf("PathFinder") }
        val avatarOptions = listOf(
            "⚡" to "Blaze",
            "🛡️" to "Guardian",
            "🦅" to "Scout",
            "👑" to "Sovereign",
            "🚀" to "Voyager"
        )
        var selectedAvatarIndex by remember { mutableIntStateOf(0) }
        var selectedGoal by remember { mutableIntStateOf(6000) }

        // Permission Launcher
        var permissionsGranted by remember {
            mutableStateOf(PermissionManager.hasAllPermissions(context))
        }

        val permissionLauncher = rememberLauncherForActivityResult(
            contract = ActivityResultContracts.RequestMultiplePermissions()
        ) { results ->
            permissionsGranted = results.values.all { it }
        }

        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp)
            ) {
                // Top Step Progress Indicator
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 16.dp, bottom = 24.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    repeat(4) { index ->
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .height(4.dp)
                                .clip(RoundedCornerShape(2.dp))
                                .background(
                                    if (index <= currentStep) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.outlineVariant
                                )
                        )
                    }
                }

                // Step Content
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                ) {
                    AnimatedContent(
                        targetState = currentStep,
                        transitionSpec = { fadeIn() togetherWith fadeOut() },
                        label = "onboarding_step"
                    ) { step ->
                        when (step) {
                            0 -> StepConcept(
                                onNext = { currentStep = 1 }
                            )
                            1 -> StepConquest(
                                onNext = { currentStep = 2 }
                            )
                            2 -> StepPermissions(
                                hasPermissions = permissionsGranted,
                                onRequest = {
                                    permissionLauncher.launch(PermissionManager.REQUIRED_PERMISSIONS)
                                },
                                onNext = { currentStep = 3 }
                            )
                            3 -> StepProfileSetup(
                                codename = codename,
                                onCodenameChange = { codename = it },
                                avatarOptions = avatarOptions,
                                selectedAvatar = selectedAvatarIndex,
                                onSelectAvatar = { selectedAvatarIndex = it },
                                selectedGoal = selectedGoal,
                                onSelectGoal = { selectedGoal = it },
                                onFinish = {
                                    coroutineScope.launch {
                                        // No id: the profile's key is the account,
                                        // and `saveProfile` stamps the signed-in
                                        // subject. Onboarding therefore writes into
                                        // the row belonging to the account that is
                                        // completing it, which is also why this
                                        // screen can never be skipped on the
                                        // strength of another account's answer.
                                        val profile = UserProfileEntity(
                                            username = codename.trim().ifEmpty { "PathFinder" },
                                            avatarName = avatarOptions[selectedAvatarIndex].first,
                                            dailyStepGoal = selectedGoal,
                                            level = 1,
                                            xp = 50, // Welcome XP
                                            currentStreak = 1,
                                            longestStreak = 1,
                                            isOnboardingCompleted = true
                                        )
                                        userProfileRepo.saveProfile(profile)
                                        questRepo.ensureTodayQuests()
                                        achievementRepo.ensureDefaultAchievements()

                                        navigator.replaceAll(MainHubScreen())
                                    }
                                }
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StepConcept(onNext: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text("⬡", fontSize = 80.sp, color = MaterialTheme.colorScheme.primary)
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = "Welcome to FitQuest",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = "The physical world is divided into discrete hexagonal zones. Every step you walk accumulates real territorial power.",
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(modifier = Modifier.height(48.dp))
        Button(
            onClick = onNext,
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) {
            Text("Next")
            Spacer(modifier = Modifier.width(8.dp))
            Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null)
        }
    }
}

@Composable
private fun StepConquest(onNext: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text("👑", fontSize = 80.sp)
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = "King of the Hill",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = "Walk inside a hexagon to claim it. The more steps you invest, the higher your defense score. Defend your home turf and conquer the city!",
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(modifier = Modifier.height(48.dp))
        Button(
            onClick = onNext,
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) {
            Text("Got It")
            Spacer(modifier = Modifier.width(8.dp))
            Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null)
        }
    }
}

@Composable
private fun StepPermissions(
    hasPermissions: Boolean,
    onRequest: () -> Unit,
    onNext: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text("🛡️", fontSize = 64.sp)
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = "Hardware Permissions",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = "FitQuest relies on your physical sensors to translate real movement into hex conquest.",
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(modifier = Modifier.height(24.dp))

        PermissionCard(
            title = "Precise Location",
            description = "Determines exactly which hexagon you are currently walking in.",
            icon = Icons.Default.LocationOn
        )

        Spacer(modifier = Modifier.height(12.dp))

        PermissionCard(
            title = "Physical Activity",
            description = "Tracks step counts in real time via the on-device step counter.",
            icon = Icons.Default.PlayArrow
        )

        Spacer(modifier = Modifier.height(36.dp))

        if (!hasPermissions) {
            Button(
                onClick = onRequest,
                modifier = Modifier.fillMaxWidth().height(52.dp)
            ) {
                Text("Grant Permissions")
            }
            Spacer(modifier = Modifier.height(8.dp))
            TextButton(onClick = onNext) {
                Text("Skip for Now (Dev Mode)")
            }
        } else {
            Button(
                onClick = onNext,
                modifier = Modifier.fillMaxWidth().height(52.dp)
            ) {
                Text("Permissions Granted • Continue")
            }
        }
    }
}

@Composable
private fun PermissionCard(
    title: String,
    description: String,
    icon: ImageVector
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
        )
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            }
            Spacer(modifier = Modifier.width(16.dp))
            Column {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun StepProfileSetup(
    codename: String,
    onCodenameChange: (String) -> Unit,
    avatarOptions: List<Pair<String, String>>,
    selectedAvatar: Int,
    onSelectAvatar: (Int) -> Unit,
    selectedGoal: Int,
    onSelectGoal: (Int) -> Unit,
    onFinish: () -> Unit
) {
    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "Create Your Explorer Identity",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = "Customize your profile and territory codename",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(modifier = Modifier.height(24.dp))

        // Avatar selector
        Text("Choose Avatar", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        Spacer(modifier = Modifier.height(12.dp))
        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            avatarOptions.forEachIndexed { index, (emoji, name) ->
                val isSelected = selectedAvatar == index
                Box(
                    modifier = Modifier
                        .size(56.dp)
                        .clip(CircleShape)
                        .background(
                            if (isSelected) MaterialTheme.colorScheme.primary.copy(alpha = 0.2f)
                            else MaterialTheme.colorScheme.surfaceVariant
                        )
                        .border(
                            width = if (isSelected) 2.dp else 0.dp,
                            color = if (isSelected) MaterialTheme.colorScheme.primary else Color.Transparent,
                            shape = CircleShape
                        )
                        .clickable { onSelectAvatar(index) },
                    contentAlignment = Alignment.Center
                ) {
                    Text(emoji, fontSize = 26.sp)
                }
            }
        }

        Spacer(modifier = Modifier.height(24.dp))

        // Codename field
        OutlinedTextField(
            value = codename,
            onValueChange = onCodenameChange,
            label = { Text("Explorer Codename") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp)
        )

        Spacer(modifier = Modifier.height(24.dp))

        // Daily step goal picker
        Text("Daily Step Goal", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        Spacer(modifier = Modifier.height(8.dp))
        val goalOptions = listOf(4000, 6000, 8000, 10000, 12000)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            goalOptions.forEach { goal ->
                val selected = selectedGoal == goal
                FilterChip(
                    selected = selected,
                    onClick = { onSelectGoal(goal) },
                    label = { Text("${goal / 1000}k") }
                )
            }
        }

        Spacer(modifier = Modifier.height(40.dp))

        Button(
            onClick = onFinish,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            shape = RoundedCornerShape(14.dp)
        ) {
            Text("Enter FitQuest", fontSize = 16.sp, fontWeight = FontWeight.Bold)
        }
        Spacer(modifier = Modifier.height(24.dp))
    }
}
