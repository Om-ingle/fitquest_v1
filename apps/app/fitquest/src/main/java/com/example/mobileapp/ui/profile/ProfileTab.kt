package com.example.mobileapp.ui.profile

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
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
import androidx.compose.ui.graphics.vector.rememberVectorPainter
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cafe.adriel.voyager.navigator.tab.Tab
import cafe.adriel.voyager.navigator.tab.TabOptions
import com.example.mobileapp.core.auth.AuthSession
import com.example.mobileapp.core.data.local.CapturedHexEntity
import com.example.mobileapp.core.data.local.HexRepository
import com.example.mobileapp.core.data.local.RunSessionRepository
import com.example.mobileapp.core.data.local.UserProfileEntity
import com.example.mobileapp.core.data.local.UserProfileRepository
import kotlinx.coroutines.launch
import org.koin.compose.koinInject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object ProfileTab : Tab {
    override val options: TabOptions
        @Composable
        get() {
            val icon = rememberVectorPainter(Icons.Default.Person)
            return remember {
                TabOptions(
                    index = 3u,
                    title = "Profile",
                    icon = icon
                )
            }
        }

    @Composable
    override fun Content() {
        val userProfileRepo = koinInject<UserProfileRepository>()
        val hexRepo = koinInject<HexRepository>()
        val runSessionRepo = koinInject<RunSessionRepository>()
        val authSession = koinInject<AuthSession>()
        val coroutineScope = rememberCoroutineScope()

        val profileState by userProfileRepo.observeProfile().collectAsState(initial = null)
        val profile = profileState ?: UserProfileEntity()
        val capturedHexes by hexRepo.observeCapturedHexes().collectAsState(initial = emptyList())
        val sessionCount by runSessionRepo.observeSessionCount().collectAsState(initial = 0)

        var showEditProfileDialog by remember { mutableStateOf(false) }
        var showSignOutDialog by remember { mutableStateOf(false) }

        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            item {
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "Explorer Profile",
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold
                )
            }

            item {
                ProfileHeroCard(
                    profile = profile,
                    onEditClick = { showEditProfileDialog = true }
                )
            }

            item {
                LifetimeStatsMatrix(
                    profile = profile,
                    totalHexes = capturedHexes.size,
                    totalRuns = sessionCount
                )
            }

            item {
                DailyGoalCard(
                    currentGoal = profile.dailyStepGoal,
                    onUpdateGoal = { newGoal ->
                        coroutineScope.launch {
                            userProfileRepo.updateDailyGoal(newGoal)
                        }
                    }
                )
            }

            item {
                TerritoryVaultSection(hexes = capturedHexes)
            }

            // M11 (F-04): the session lives here, so the way out of it does too.
            item {
                SignOutSection(onSignOutClick = { showSignOutDialog = true })
            }

            item {
                Spacer(modifier = Modifier.height(32.dp))
            }
        }

        if (showSignOutDialog) {
            AlertDialog(
                onDismissRequest = { showSignOutDialog = false },
                title = { Text("Sign out?") },
                text = {
                    Text(
                        "You'll need to sign in again to sync runs and defend " +
                            "your territory. Your captured hexes stay on the server."
                    )
                },
                confirmButton = {
                    TextButton(
                        onClick = {
                            showSignOutDialog = false
                            // The screen change is not done here: MainActivity
                            // observes the session and routes to login, which
                            // also drops the authenticated WebSocket. One
                            // transition, driven from one place.
                            authSession.signOut()
                        }
                    ) {
                        Text("Sign out")
                    }
                },
                dismissButton = {
                    TextButton(onClick = { showSignOutDialog = false }) { Text("Cancel") }
                }
            )
        }

        if (showEditProfileDialog) {
            EditProfileDialog(
                currentProfile = profile,
                onDismiss = { showEditProfileDialog = false },
                onSave = { updated ->
                    coroutineScope.launch {
                        userProfileRepo.saveProfile(updated)
                        showEditProfileDialog = false
                    }
                }
            )
        }
    }
}

@Composable
private fun ProfileHeroCard(
    profile: UserProfileEntity,
    onEditClick: () -> Unit
) {
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(20.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .size(64.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primaryContainer)
                        .border(2.5.dp, MaterialTheme.colorScheme.primary, CircleShape),
                    contentAlignment = Alignment.Center
                ) {
                    Text(profile.avatarName.ifEmpty { "⚡" }, fontSize = 32.sp)
                }

                Spacer(modifier = Modifier.width(16.dp))

                Column(modifier = Modifier.weight(1f)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = profile.username,
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold
                        )
                        OutlinedButton(
                            onClick = onEditClick,
                            shape = RoundedCornerShape(12.dp)
                        ) {
                            Text("Edit", style = MaterialTheme.typography.labelMedium)
                        }
                    }

                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Surface(
                            shape = RoundedCornerShape(6.dp),
                            color = MaterialTheme.colorScheme.primary.copy(alpha = 0.15f)
                        ) {
                            Text(
                                "Level ${profile.level}",
                                color = MaterialTheme.colorScheme.primary,
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                        Surface(
                            shape = RoundedCornerShape(6.dp),
                            color = Color(0xFFFF9800).copy(alpha = 0.15f)
                        ) {
                            Text(
                                "🔥 ${profile.currentStreak}d Streak",
                                color = Color(0xFFE65100),
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Level Progress Bar
            val xpInCurrentLevel = profile.xp % 250
            val progress = (xpInCurrentLevel.toFloat() / 250f).coerceIn(0f, 1f)

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text("Level ${profile.level} Progress", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("$xpInCurrentLevel / 250 XP", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            }

            Spacer(modifier = Modifier.height(6.dp))

            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(8.dp)
                    .clip(RoundedCornerShape(4.dp)),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.surfaceVariant
            )
        }
    }
}

@Composable
private fun LifetimeStatsMatrix(
    profile: UserProfileEntity,
    totalHexes: Int,
    totalRuns: Int
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(20.dp)) {
            Text("Career Record", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(16.dp))

            Row(modifier = Modifier.fillMaxWidth()) {
                MatrixItem(modifier = Modifier.weight(1f), label = "Lifetime Steps", value = "${profile.totalLifetimeSteps}")
                MatrixItem(modifier = Modifier.weight(1f), label = "Distance Covered", value = String.format("%.1f km", profile.totalDistanceMeters / 1000.0))
            }
            Spacer(modifier = Modifier.height(12.dp))
            Row(modifier = Modifier.fillMaxWidth()) {
                MatrixItem(modifier = Modifier.weight(1f), label = "Hexagons Owned", value = "$totalHexes")
                MatrixItem(modifier = Modifier.weight(1f), label = "Expeditions", value = "$totalRuns")
            }
            Spacer(modifier = Modifier.height(12.dp))
            Row(modifier = Modifier.fillMaxWidth()) {
                MatrixItem(modifier = Modifier.weight(1f), label = "Active Calories", value = "${profile.totalCalories} kcal")
                MatrixItem(modifier = Modifier.weight(1f), label = "Longest Streak", value = "${profile.longestStreak} days")
            }
        }
    }
}

@Composable
private fun MatrixItem(modifier: Modifier = Modifier, label: String, value: String) {
    Column(modifier = modifier) {
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun DailyGoalCard(
    currentGoal: Int,
    onUpdateGoal: (Int) -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(20.dp)) {
            Text("Daily Step Target", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("Set your personal pace for territory exploration", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)

            Spacer(modifier = Modifier.height(12.dp))

            val goals = listOf(4000, 6000, 8000, 10000, 12000)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                goals.forEach { goal ->
                    val selected = currentGoal == goal
                    FilterChip(
                        selected = selected,
                        onClick = { onUpdateGoal(goal) },
                        label = { Text("${goal / 1000}k") }
                    )
                }
            }
        }
    }
}

@Composable
private fun TerritoryVaultSection(hexes: List<CapturedHexEntity>) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text("Territory Vault", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Spacer(modifier = Modifier.height(10.dp))

        if (hexes.isEmpty()) {
            Text(
                text = "No territories conquered yet. Complete your first run to claim a hexagon.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                hexes.take(10).forEach { hex ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f))
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("⬡", fontSize = 20.sp, color = MaterialTheme.colorScheme.primary)
                                Spacer(modifier = Modifier.width(10.dp))
                                Column {
                                    Text("Hex #${hex.hexId.take(10)}...", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                                    val dateStr = SimpleDateFormat("MMM d, yyyy", Locale.US).format(Date(hex.lastUpdated))
                                    Text("Captured $dateStr", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                            Text("${hex.totalSteps} steps", fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SignOutSection(onSignOutClick: () -> Unit) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = "Account",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold
        )
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedButton(
            onClick = onSignOutClick,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Sign out")
        }
    }
}

@Composable
private fun EditProfileDialog(
    currentProfile: UserProfileEntity,
    onDismiss: () -> Unit,
    onSave: (UserProfileEntity) -> Unit
) {
    var username by remember { mutableStateOf(currentProfile.username) }
    val avatarOptions = listOf(
        "⚡" to "Blaze",
        "🛡️" to "Guardian",
        "🦅" to "Scout",
        "👑" to "Sovereign",
        "🚀" to "Voyager"
    )
    var selectedAvatar by remember {
        mutableStateOf(currentProfile.avatarName.ifEmpty { "⚡" })
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit Explorer Profile", fontWeight = FontWeight.Bold) },
        text = {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                OutlinedTextField(
                    value = username,
                    onValueChange = { username = it },
                    label = { Text("Codename") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp)
                )

                Text("Select Avatar", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    avatarOptions.forEach { (emoji, _) ->
                        val isSelected = selectedAvatar == emoji
                        Box(
                            modifier = Modifier
                                .size(48.dp)
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
                                .clickable { selectedAvatar = emoji },
                            contentAlignment = Alignment.Center
                        ) {
                            Text(emoji, fontSize = 22.sp)
                        }
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onSave(currentProfile.copy(
                        username = username.trim().ifEmpty { currentProfile.username },
                        avatarName = selectedAvatar
                    ))
                }
            ) {
                Text("Save")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}
