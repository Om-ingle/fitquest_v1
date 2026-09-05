package com.example.mobileapp.ui.leaderboard

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
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
import com.example.mobileapp.core.network.LeaderboardFetcher
import com.example.mobileapp.core.network.models.LeaderboardEntryResponse
import com.example.mobileapp.core.network.models.LeaderboardResponse
import org.koin.compose.koinInject

data class Contender(
    val name: String,
    val avatar: String,
    val hexCount: Int,
    val isUser: Boolean = false
)

object LeaderboardTab : Tab {
    override val options: TabOptions
        @Composable
        get() {
            val icon = rememberVectorPainter(Icons.Default.Star)
            return remember {
                TabOptions(
                    index = 1u,
                    title = "Rank",
                    icon = icon
                )
            }
        }

    @Composable
    override fun Content() {
        val fetcher = koinInject<LeaderboardFetcher>()
        var retryKey by remember { mutableIntStateOf(0) }

        // Server-backed leaderboard; no local/fake rivals. produceState is
        // keyed on retryKey so the Retry button re-fetches.
        val state by produceState<LeaderboardFetcher.Outcome?>(
            initialValue = null,
            key1 = retryKey
        ) {
            value = fetcher.fetchLeaderboard()
        }

        when (val outcome = state) {
            null -> LoadingState()
            is LeaderboardFetcher.Outcome.NetworkError,
            is LeaderboardFetcher.Outcome.HttpError -> ErrorState(
                message = when (outcome) {
                    is LeaderboardFetcher.Outcome.HttpError -> "Server error (HTTP ${outcome.code})"
                    is LeaderboardFetcher.Outcome.NetworkError ->
                        outcome.cause ?: "Network unreachable"
                    else -> "Unknown error"
                }
            ) { retryKey++ }
            is LeaderboardFetcher.Outcome.Success -> LeaderboardContent(outcome.leaderboard)
        }
    }

    @Composable
    private fun LoadingState() {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator()
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = "Loading territory rankings…",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }

    @Composable
    private fun ErrorState(message: String, onRetry: () -> Unit) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Column(
                modifier = Modifier.padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("📡", fontSize = 40.sp)
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "Couldn't load leaderboard",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(16.dp))
                Button(onClick = onRetry) { Text("Retry") }
            }
        }
    }
}

@Composable
private fun LeaderboardContent(leaderboard: LeaderboardResponse) {
    // The current user's entry: inside the top-N list, or supplied
    // separately by the backend when they missed the cut.
    val currentUserEntry = leaderboard.entries.firstOrNull { it.is_current_user }
        ?: leaderboard.current_user_entry

    if (leaderboard.entries.isEmpty()) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(
                modifier = Modifier.padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("🗺️", fontSize = 40.sp)
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "No contenders yet",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "Capture your first territory to claim rank #1",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        return
    }

    // Rank travels with each row so the appended standalone current-user
    // entry keeps its server-assigned rank.
    val rows: List<Pair<Int, Contender>> =
        leaderboard.entries.map { it.rank to it.toContender() } +
            listOfNotNull(
                leaderboard.current_user_entry?.takeIf { standalone ->
                    leaderboard.entries.none { it.user_id == standalone.user_id }
                }?.let { it.rank to it.toContender() }
            )

    val userRank = currentUserEntry?.rank ?: 0
    val userHexCount = currentUserEntry?.hexes_owned ?: 0

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "Territory Leaderboard",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = "Ranked by territories conquered",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        item {
            DistrictTierCard(hexCount = userHexCount)
        }

        if (currentUserEntry != null) {
            item {
                UserStandingCard(
                    rank = userRank,
                    hexCount = userHexCount,
                    totalContenders = leaderboard.total_players
                )
            }
        }

        item {
            Text(
                text = "District Standings",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
        }

        itemsIndexed(rows) { _, row ->
            ContenderRow(rank = row.first, contender = row.second)
        }

        item {
            Spacer(modifier = Modifier.height(32.dp))
        }
    }
}

private fun LeaderboardEntryResponse.toContender(): Contender = Contender(
    name = username,
    avatar = avatar_url?.takeIf { it.isNotBlank() } ?: defaultAvatar(rank),
    hexCount = hexes_owned,
    isUser = is_current_user
)

private fun defaultAvatar(rank: Int): String = when (rank) {
    1 -> "👑"
    2 -> "🥈"
    3 -> "🥉"
    else -> "🏃"
}

@Composable
private fun DistrictTierCard(hexCount: Int) {
    val (tierName, tierEmoji, nextThreshold, color) = when {
        hexCount >= 50 -> Quad("Hex Master", "💎", 50, Color(0xFF00B0FF))
        hexCount >= 30 -> Quad("Regional Sovereign", "👑", 50, Color(0xFFFFD700))
        hexCount >= 15 -> Quad("Urban Conqueror", "🛡️", 30, Color(0xFFE040FB))
        hexCount >= 5 -> Quad("District Pioneer", "⚡", 15, Color(0xFF00E676))
        else -> Quad("Novice Scout", "🦅", 5, Color(0xFFFF9100))
    }

    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(20.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(tierEmoji, fontSize = 32.sp)
                    Spacer(modifier = Modifier.width(12.dp))
                    Column {
                        Text(tierName, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text("Current Division", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = color.copy(alpha = 0.15f)
                ) {
                    Text(
                        "$hexCount Hexes",
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.Bold,
                        color = color,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                    )
                }
            }

            if (hexCount < 50) {
                Spacer(modifier = Modifier.height(16.dp))
                val progress = (hexCount.toFloat() / nextThreshold.toFloat()).coerceIn(0f, 1f)
                LinearProgressIndicator(
                    progress = { progress },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(8.dp)
                        .clip(RoundedCornerShape(4.dp)),
                    color = color,
                    trackColor = MaterialTheme.colorScheme.surfaceVariant
                )
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "${nextThreshold - hexCount} more hexes to reach next rank",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun UserStandingCard(rank: Int, hexCount: Int, totalContenders: Int) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f))
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text("Your Ranking", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("Rank #$rank of $totalContenders", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            }
            Text(
                text = if (rank == 1) "👑 District King" else "⚔️ Contender",
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.primary
            )
        }
    }
}

@Composable
private fun ContenderRow(rank: Int, contender: Contender) {
    val isUser = contender.isUser
    val rankBadgeColor = when (rank) {
        1 -> Color(0xFFFFD700)
        2 -> Color(0xFFC0C0C0)
        3 -> Color(0xFFCD7F32)
        else -> MaterialTheme.colorScheme.surfaceVariant
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isUser) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
            else MaterialTheme.colorScheme.surface
        ),
        border = if (isUser) BorderStroke(1.5.dp, MaterialTheme.colorScheme.primary) else null
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Rank Number
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .background(rankBadgeColor.copy(alpha = 0.25f)),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "#$rank",
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                    color = if (rank <= 3) Color(0xFFD48800) else MaterialTheme.colorScheme.onSurface
                )
            }

            Spacer(modifier = Modifier.width(12.dp))

            // Avatar
            Text(contender.avatar, fontSize = 24.sp)

            Spacer(modifier = Modifier.width(12.dp))

            // Name
            Text(
                text = contender.name,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = if (isUser) FontWeight.Bold else FontWeight.Medium,
                modifier = Modifier.weight(1f)
            )

            if (isUser) {
                Spacer(modifier = Modifier.width(6.dp))
                Surface(
                    shape = RoundedCornerShape(4.dp),
                    color = MaterialTheme.colorScheme.primary
                ) {
                    Text(
                        "YOU",
                        color = Color.White,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(horizontal = 4.dp, vertical = 1.dp)
                    )
                }
            }

            // Hex Count
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = "${contender.hexCount} ⬡",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    text = "territories",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

private data class Quad<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)
