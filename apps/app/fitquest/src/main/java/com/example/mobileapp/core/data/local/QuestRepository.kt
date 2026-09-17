package com.example.mobileapp.core.data.local

import android.util.Log
import com.example.mobileapp.core.auth.IdentityProvider
import kotlinx.coroutines.flow.Flow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

interface QuestRepository {
    fun observeTodayQuests(): Flow<List<DailyQuestEntity>>
    suspend fun ensureTodayQuests()
    suspend fun recordActivity(steps: Int, hexCount: Int, durationSeconds: Long)
}

/**
 * Today's quests, filed under the signed-in account.
 *
 * The quest ids are `"${today}_steps_3k"` and friends — derived from the date,
 * not the user — so before this was scoped, the first account to open the app
 * on a given day owned the day's quest rows and every other account read and
 * advanced those same rows. Every statement now names the owner, and the rows
 * are created per account on first use.
 */
class RoomQuestRepository(
    private val questDao: DailyQuestDao,
    private val userProfileRepository: UserProfileRepository,
    private val identity: IdentityProvider,
) : QuestRepository {

    private fun todayString(): String = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())

    override fun observeTodayQuests(): Flow<List<DailyQuestEntity>> {
        val today = todayString()
        return identity.ownedFlow(emptyList()) { owner -> questDao.observeQuestsForDate(owner, today) }
    }

    override suspend fun ensureTodayQuests() {
        val owner = identity.currentSubject() ?: run {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("QuestRepository", "ensureTodayQuests"))
            return
        }
        val today = todayString()
        val existing = questDao.getQuestsForDate(owner, today)
        if (existing.isNotEmpty()) return

        val defaultQuests = listOf(
            DailyQuestEntity(
                ownerSubject = owner,
                id = "${today}_steps_3k",
                title = "Trail Blazer",
                description = "Log at least 3,000 steps today",
                targetMetric = "STEPS",
                targetValue = 3000,
                rewardXp = 100,
                dateString = today
            ),
            DailyQuestEntity(
                ownerSubject = owner,
                id = "${today}_hex_2",
                title = "Territory Expansion",
                description = "Capture or reinforce 2 hexagons",
                targetMetric = "HEXES",
                targetValue = 2,
                rewardXp = 150,
                dateString = today
            ),
            DailyQuestEntity(
                ownerSubject = owner,
                id = "${today}_duration_10m",
                title = "Endurance Walk",
                description = "Complete an active capture walk of at least 10 minutes",
                targetMetric = "DURATION",
                targetValue = 600, // 600 seconds = 10 mins
                rewardXp = 120,
                dateString = today
            )
        )
        questDao.insertQuests(defaultQuests)
    }

    override suspend fun recordActivity(steps: Int, hexCount: Int, durationSeconds: Long) {
        val owner = identity.currentSubject() ?: run {
            Log.w(OWNER_LOG_TAG, ownerlessRefusal("QuestRepository", "recordActivity"))
            return
        }
        val today = todayString()
        val quests = questDao.getQuestsForDate(owner, today)

        for (quest in quests) {
            if (quest.isCompleted) continue

            val delta = when (quest.targetMetric) {
                "STEPS" -> steps
                "HEXES" -> hexCount
                "DURATION" -> durationSeconds.toInt()
                else -> 0
            }

            val newProgress = quest.currentProgress + delta
            val completed = newProgress >= quest.targetValue

            if (completed && !quest.isCompleted) {
                // Award XP to user profile. `userProfileRepository` resolves the
                // same account independently, so the reward can only ever land on
                // the profile of the account whose quest just completed.
                val profile = userProfileRepository.getProfile()
                userProfileRepository.saveProfile(profile.copy(
                    xp = profile.xp + quest.rewardXp,
                    level = 1 + ((profile.xp + quest.rewardXp) / 250)
                ))
            }

            questDao.updateProgress(owner, quest.id, newProgress, completed)
        }
    }
}
