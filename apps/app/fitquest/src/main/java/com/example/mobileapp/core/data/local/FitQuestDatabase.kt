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
        AchievementEntity::class,
        ActiveRunEntity::class
    ],
    version = 5,
    exportSchema = false
)
abstract class FitQuestDatabase : RoomDatabase() {
    abstract fun hexDao(): HexDao
    abstract fun userDao(): UserDao
    abstract fun runSessionDao(): RunSessionDao
    abstract fun dailyQuestDao(): DailyQuestDao
    abstract fun achievementDao(): AchievementDao
    abstract fun activeRunDao(): ActiveRunDao

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

        // v4 adds the single-row active_run checkpoint table used for
        // process-death recovery. Nullable pausedSinceMillis is the only
        // nullable column; all other columns have Room defaults or NOT NULL.
        val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS active_run (" +
                        "runId TEXT NOT NULL PRIMARY KEY, " +
                        "startedAtMillis INTEGER NOT NULL, " +
                        "isPaused INTEGER NOT NULL, " +
                        "pausedSinceMillis INTEGER, " +
                        "pausedAccumulatedMillis INTEGER NOT NULL, " +
                        "sessionSteps INTEGER NOT NULL, " +
                        "distanceMeters REAL NOT NULL, " +
                        "hexesToStepsJson TEXT NOT NULL, " +
                        "lastCheckpointAtMillis INTEGER NOT NULL)"
                )
            }
        }

        // v5 adds run_sessions.pendingSyncPayloadJson — the exact outbound
        // RunSyncPayload (incl. run_id) persisted before the first sync so a
        // failed-sync retry can replay byte-identical data (Fix A). Nullable
        // so existing rows migrate cleanly; legacy rows read NULL and are
        // best-effort reconstructed by RunReconciler instead.
        val MIGRATION_4_5 = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "ALTER TABLE run_sessions ADD COLUMN pendingSyncPayloadJson TEXT"
                )
            }
        }
    }
}
