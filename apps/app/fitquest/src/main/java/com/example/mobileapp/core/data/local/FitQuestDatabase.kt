package com.example.mobileapp.core.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        CapturedHexEntity::class,
        UserProfileEntity::class,
        RunSessionEntity::class,
        DailyQuestEntity::class,
        AchievementEntity::class
    ],
    version = 3,
    exportSchema = false
)
abstract class FitQuestDatabase : RoomDatabase() {
    abstract fun hexDao(): HexDao
    abstract fun userDao(): UserDao
    abstract fun runSessionDao(): RunSessionDao
    abstract fun dailyQuestDao(): DailyQuestDao
    abstract fun achievementDao(): AchievementDao

    companion object {
        // v3 adds run_sessions.isSynced. Real migration (not destructive) so
        // local run history survives the upgrade.
        val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "ALTER TABLE run_sessions ADD COLUMN isSynced INTEGER NOT NULL DEFAULT 0"
                )
            }
        }
    }
}
