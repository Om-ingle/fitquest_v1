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
    version = 6,
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

        /**
         * v6 scopes every local table to the account that owns it.
         *
         * ### Why this is a rebuild and not six `ADD COLUMN`s
         *
         * `ownerSubject` is not just a new column — it is part of the identity
         * of three of these rows. `captured_hexes.hexId` is a map coordinate,
         * `daily_quests.id` is `"${date}_${slug}"` and `achievements.id` is a
         * fixed constant, so all three are shared between accounts by
         * construction and each needs `(ownerSubject, id)` as its key. And
         * `user_profile`'s key was the literal `"local_user"`, which has to go
         * entirely. SQLite cannot alter a primary key, so those four tables are
         * rebuilt: create the new shape, copy the rows in, drop the old table,
         * rename. `run_sessions` and `active_run` are keyed by a UUID and would
         * only need `ADD COLUMN`, but they are rebuilt the same way so all six
         * tables end in one uniform shape with no DB-level `DEFAULT` anywhere —
         * a default would have to be re-declared in the entity via
         * `@ColumnInfo(defaultValue = …)` for Room's schema validation to pass,
         * and one uniform mechanism is far easier to verify than two.
         *
         * The column list and order below is exactly what Room generates from
         * the entities, so the migrated table presents the same shape Room's
         * `TableInfo` reads back from a freshly created one — same column names,
         * same order, same affinities, same NOT NULLs, same primary key, and no
         * DB-level `DEFAULT` anywhere. (The raw `sqlite_master.sql` text is not
         * identical: Room's own CREATE says `IF NOT EXISTS` and this one cannot,
         * because the table already exists under a staging name. Room validates
         * the parsed table, not the statement text, so that difference is
         * invisible to it.) `tools/verify_migration_5_6.py` checks this against
         * a real pre-migration database by parsing the entity sources
         * independently of this column list.
         *
         * ### Where existing rows go — the migration policy
         *
         * Rows written before this migration have no account recorded, and the
         * device cannot know which account created them: the old schema had no
         * per-user column anywhere, and the only account identifier ever stored
         * was the token in encrypted storage, which is overwritten on each
         * sign-in. Inferring an owner would mean silently handing one account
         * another account's history — the exact defect being fixed.
         *
         * So the rows are QUARANTINED, not deleted: they are carried across
         * intact and stamped `LEGACY_UNOWNED_SUBJECT`, which no account can
         * match, so no query returns them. Nothing is lost — the rows are still
         * in `fitquest.db` and can be inspected or re-assigned later with a
         * single `UPDATE … SET ownerSubject = '<the verified subject>'` once the
         * correct account has been established by other means. They are simply
         * invisible until someone decides, deliberately, who they belong to.
         *
         * What this means in practice for the device this was written for: its
         * 40 existing runs, 16 hexes, 18 quests, 8 achievements and 1 profile
         * stop being visible, and the account that signs in next sees a fresh
         * profile and is taken through onboarding. That is the cost of not
         * guessing, and it is why this migration was written but NOT applied
         * until the owner approves the policy.
         */
        val MIGRATION_5_6 = object : Migration(5, 6) {
            override fun migrate(db: SupportSQLiteDatabase) {
                rebuildScopedTable(
                    db,
                    table = "run_sessions",
                    newColumns = "`ownerSubject` TEXT NOT NULL, `id` TEXT NOT NULL, " +
                        "`startedAt` INTEGER NOT NULL, `endedAt` INTEGER NOT NULL, " +
                        "`durationSeconds` INTEGER NOT NULL, `totalSteps` INTEGER NOT NULL, " +
                        "`distanceMeters` REAL NOT NULL, `caloriesBurned` INTEGER NOT NULL, " +
                        "`capturedHexCount` INTEGER NOT NULL, `capturedHexIdsJson` TEXT NOT NULL, " +
                        "`xpEarned` INTEGER NOT NULL, `isSynced` INTEGER NOT NULL, " +
                        "`pendingSyncPayloadJson` TEXT",
                    primaryKey = "PRIMARY KEY(`id`)",
                    carriedColumns = "`id`, `startedAt`, `endedAt`, `durationSeconds`, " +
                        "`totalSteps`, `distanceMeters`, `caloriesBurned`, `capturedHexCount`, " +
                        "`capturedHexIdsJson`, `xpEarned`, `isSynced`, `pendingSyncPayloadJson`",
                )

                rebuildScopedTable(
                    db,
                    table = "captured_hexes",
                    newColumns = "`ownerSubject` TEXT NOT NULL, `hexId` TEXT NOT NULL, " +
                        "`totalSteps` INTEGER NOT NULL, `lastUpdated` INTEGER NOT NULL",
                    primaryKey = "PRIMARY KEY(`ownerSubject`, `hexId`)",
                    carriedColumns = "`hexId`, `totalSteps`, `lastUpdated`",
                )

                rebuildScopedTable(
                    db,
                    table = "daily_quests",
                    newColumns = "`ownerSubject` TEXT NOT NULL, `id` TEXT NOT NULL, " +
                        "`title` TEXT NOT NULL, `description` TEXT NOT NULL, " +
                        "`targetMetric` TEXT NOT NULL, `targetValue` INTEGER NOT NULL, " +
                        "`currentProgress` INTEGER NOT NULL, `isCompleted` INTEGER NOT NULL, " +
                        "`rewardXp` INTEGER NOT NULL, `dateString` TEXT NOT NULL",
                    primaryKey = "PRIMARY KEY(`ownerSubject`, `id`)",
                    carriedColumns = "`id`, `title`, `description`, `targetMetric`, " +
                        "`targetValue`, `currentProgress`, `isCompleted`, `rewardXp`, `dateString`",
                )

                rebuildScopedTable(
                    db,
                    table = "achievements",
                    newColumns = "`ownerSubject` TEXT NOT NULL, `id` TEXT NOT NULL, " +
                        "`title` TEXT NOT NULL, `description` TEXT NOT NULL, " +
                        "`category` TEXT NOT NULL, `iconName` TEXT NOT NULL, " +
                        "`currentProgress` INTEGER NOT NULL, `maxProgress` INTEGER NOT NULL, " +
                        "`isUnlocked` INTEGER NOT NULL, `unlockedAt` INTEGER",
                    primaryKey = "PRIMARY KEY(`ownerSubject`, `id`)",
                    carriedColumns = "`id`, `title`, `description`, `category`, `iconName`, " +
                        "`currentProgress`, `maxProgress`, `isUnlocked`, `unlockedAt`",
                )

                rebuildScopedTable(
                    db,
                    table = "active_run",
                    newColumns = "`ownerSubject` TEXT NOT NULL, `runId` TEXT NOT NULL, " +
                        "`startedAtMillis` INTEGER NOT NULL, `isPaused` INTEGER NOT NULL, " +
                        "`pausedSinceMillis` INTEGER, `pausedAccumulatedMillis` INTEGER NOT NULL, " +
                        "`sessionSteps` INTEGER NOT NULL, `distanceMeters` REAL NOT NULL, " +
                        "`hexesToStepsJson` TEXT NOT NULL, `lastCheckpointAtMillis` INTEGER NOT NULL",
                    primaryKey = "PRIMARY KEY(`runId`)",
                    carriedColumns = "`runId`, `startedAtMillis`, `isPaused`, `pausedSinceMillis`, " +
                        "`pausedAccumulatedMillis`, `sessionSteps`, `distanceMeters`, " +
                        "`hexesToStepsJson`, `lastCheckpointAtMillis`",
                )

                // user_profile loses `id` entirely: it WAS the fixed
                // "local_user" constant, and the account is now the key.
                rebuildScopedTable(
                    db,
                    table = "user_profile",
                    newColumns = "`ownerSubject` TEXT NOT NULL, `username` TEXT NOT NULL, " +
                        "`avatarName` TEXT NOT NULL, `dailyStepGoal` INTEGER NOT NULL, " +
                        "`level` INTEGER NOT NULL, `xp` INTEGER NOT NULL, " +
                        "`currentStreak` INTEGER NOT NULL, `longestStreak` INTEGER NOT NULL, " +
                        "`lastActiveDate` TEXT NOT NULL, `totalLifetimeSteps` INTEGER NOT NULL, " +
                        "`totalDistanceMeters` REAL NOT NULL, `totalCalories` INTEGER NOT NULL, " +
                        "`isOnboardingCompleted` INTEGER NOT NULL, `createdAt` INTEGER NOT NULL",
                    primaryKey = "PRIMARY KEY(`ownerSubject`)",
                    carriedColumns = "`username`, `avatarName`, `dailyStepGoal`, `level`, `xp`, " +
                        "`currentStreak`, `longestStreak`, `lastActiveDate`, `totalLifetimeSteps`, " +
                        "`totalDistanceMeters`, `totalCalories`, `isOnboardingCompleted`, `createdAt`",
                )
            }
        }

        /**
         * Create [table] in its v6 shape under a staging name, copy every row
         * across with [LEGACY_UNOWNED_SUBJECT] as its owner, then swap it in.
         *
         * Room runs a migration inside a transaction, so a failure part-way
         * leaves the v5 database untouched rather than half-migrated.
         *
         * [LEGACY_UNOWNED_SUBJECT] is interpolated into the SQL as a literal.
         * That is safe because it is a `const val` compile-time String with no
         * quote character in it, and the alternative — a bound parameter — is
         * not available for the value list of an `INSERT … SELECT` through
         * `SupportSQLiteDatabase.execSQL`.
         */
        private fun rebuildScopedTable(
            db: SupportSQLiteDatabase,
            table: String,
            newColumns: String,
            primaryKey: String,
            carriedColumns: String,
        ) {
            val staging = "${table}__v6"
            db.execSQL("CREATE TABLE `$staging` ($newColumns, $primaryKey)")
            db.execSQL(
                "INSERT INTO `$staging` (`ownerSubject`, $carriedColumns) " +
                    "SELECT '$LEGACY_UNOWNED_SUBJECT', $carriedColumns FROM `$table`"
            )
            db.execSQL("DROP TABLE `$table`")
            db.execSQL("ALTER TABLE `$staging` RENAME TO `$table`")
        }
    }
}
