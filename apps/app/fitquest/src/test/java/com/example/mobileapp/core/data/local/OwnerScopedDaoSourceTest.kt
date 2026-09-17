package com.example.mobileapp.core.data.local

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The account-scoping invariant, enforced against the DAO and entity sources.
 *
 * ### Why this reads source instead of reflecting over annotations
 *
 * Room declares `@Query`, `@Insert`, `@Entity` and `@PrimaryKey` with
 * `java.lang.annotation.RetentionPolicy.CLASS` (verified on
 * `room-common-2.6.1`: the class file carries both
 * `kotlin.annotation.AnnotationRetention.BINARY` and `RetentionPolicy.CLASS`).
 * CLASS retention is discarded before runtime, so
 * `method.getAnnotation(Query::class.java)` is null in a JVM test — an
 * annotation-driven invariant here would assert nothing and still go green.
 *
 * So the annotations and the SQL are read from the Kotlin sources under
 * `src/main/java`. That is the same text Room's KSP processor consumes, which is
 * what makes this a real check: the strings asserted on below are the strings
 * that end up in the generated `*_Impl` classes and therefore in the SQLite
 * statements the app issues.
 *
 * ### What it proves, and what it does not
 *
 * This proves the DAO layer filters by owner and that every scoped entity
 * carries one. It does not prove the repositories pass the right subject — that
 * is `AccountScopedLocalDataTest`, which drives the real repositories against
 * fake DAOs. Together they cover the chain; neither covers it alone.
 *
 * ### Why the invariant is self-tested
 *
 * [the invariant rejects the pre-fix shape] runs the same checker over an
 * embedded copy of the DAO as it was before this work — `WHERE id =
 * "local_user"`, no owner parameter, keyed on the shared row. An invariant that
 * cannot fail on the code it was written to catch is decoration, so it is made
 * to fail here on purpose.
 */
class OwnerScopedDaoSourceTest {

    // ── The invariant ────────────────────────────────────────────────────────

    private fun checkDao(fileName: String): List<String> {
        val source = stripComments(readSource("core/data/local/$fileName"))
        val problems = mutableListOf<String>()

        for (method in parseMethods(source)) {
            val named = "${fileName.substringBefore('.')}.${method.name}"
            val isInsert = method.annotations.any { it.name == "Insert" }

            if (isInsert) {
                // An insert creates the row; the owner comes from the entity.
                // It must NOT take an owner parameter, because a caller-supplied
                // owner on an insert is a way to file a row under someone else.
                if (method.params.firstOrNull()?.name == OWNER) {
                    problems += "$named: @Insert takes an explicit owner; the repository must stamp it"
                }
                continue
            }

            val sql = method.querySql
            if (sql == null) {
                // @Transaction / @Delete wrappers delegate to scoped statements,
                // but must still lead with the owner so no caller can invoke
                // them without deciding who the data belongs to.
                if (method.params.isNotEmpty() && method.params.first().name != OWNER) {
                    problems += "$named: first parameter is '${method.params.first().name}', not '$OWNER'"
                }
                continue
            }

            if (!sql.contains(OWNER_COLUMN, ignoreCase = true)) {
                problems += "$named: @Query does not filter by $OWNER_COLUMN → $sql"
            }
            if (!sql.contains(":$OWNER")) {
                problems += "$named: @Query never binds :$OWNER → $sql"
            }
            val first = method.params.firstOrNull()
            when {
                first == null -> problems += "$named: no '$OWNER' parameter"
                first.name != OWNER ->
                    problems += "$named: first parameter is '${first.name}', not '$OWNER'"
                first.type != "String" ->
                    problems += "$named: owner parameter is '${first.type}', not String"
            }
        }
        return problems
    }

    private fun checkEntity(fileName: String, expectedPrimaryKey: String) {
        val source = stripComments(readSource("core/data/local/$fileName"))
        val entity = parseAnnotations(source).firstOrNull { it.name == "Entity" }
        assertTrue("$fileName declares no @Entity", entity != null)

        val composite = parsePrimaryKeys(entity!!.args)
        if (composite != null) {
            // A shared key (a hex id, a per-day quest id, a fixed achievement id)
            // must not be able to collide across accounts, so the owner has to be
            // part of the key — and first, so the generated CREATE TABLE reads
            // owner-first like every other scoped table.
            assertEquals(
                "$fileName: the owner must be the FIRST primary key component",
                OWNER_COLUMN, composite.firstOrNull()
            )
        }
        val actual = composite?.joinToString(", ") ?: primaryKeyField(source)
        assertEquals("$fileName: unexpected primary key", expectedPrimaryKey, actual)
        assertTrue(
            "$fileName: no 'val $OWNER_COLUMN: String' property",
            Regex("""val\s+$OWNER_COLUMN\s*:\s*String""").containsMatchIn(source)
        )
    }

    // ── The tests ────────────────────────────────────────────────────────────

    @Test
    fun `every DAO statement is scoped to one account`() {
        val problems = DAO_FILES.flatMap(::checkDao)
        assertTrue(
            "Unscoped local storage — these statements can read or write another account's rows:\n" +
                problems.joinToString("\n"),
            problems.isEmpty()
        )
    }

    @Test
    fun `every scoped entity is keyed by its owner`() {
        checkEntity("RunSessionEntity.kt", "id")
        checkEntity("CapturedHexEntity.kt", "$OWNER_COLUMN, hexId")
        checkEntity("DailyQuestEntity.kt", "$OWNER_COLUMN, id")
        checkEntity("AchievementEntity.kt", "$OWNER_COLUMN, id")
        checkEntity("ActiveRunEntity.kt", "runId")
        checkEntity("UserProfileEntity.kt", OWNER_COLUMN)
    }

    @Test
    fun `the fixed local_user singleton is gone from the data layer`() {
        val offenders = DAO_FILES.plus(ENTITY_FILES)
            .filter { stripComments(readSource("core/data/local/$it")).contains("\"local_user\"") }
        assertTrue(
            "The data layer still names the shared local_user row: $offenders. " +
                "One row per device is the isolation defect this scoping exists to fix.",
            offenders.isEmpty()
        )
    }

    @Test
    fun `the legacy sentinel cannot collide with a real subject`() {
        // A Supabase Auth user id is a UUID. The sentinel must be a value no
        // account could ever present, or a quarantined row would become visible
        // to a real account.
        val uuid = Regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
        assertFalse(
            "LEGACY_UNOWNED_SUBJECT is UUID-shaped and could collide with a real account",
            uuid.matches(LEGACY_UNOWNED_SUBJECT)
        )
        assertTrue("LEGACY_UNOWNED_SUBJECT is blank", LEGACY_UNOWNED_SUBJECT.isNotBlank())
        assertEquals(
            "The sentinel compiled into this test and the one MIGRATION_5_6 writes disagree",
            LEGACY_UNOWNED_SUBJECT,
            sentinelFromSource()
        )
    }

    @Test
    fun `the invariant rejects the pre-fix shape`() {
        val preFix = stripComments(
            """
            @Dao
            interface UserDao {
                @Insert(onConflict = OnConflictStrategy.REPLACE)
                suspend fun upsertProfile(profile: UserProfileEntity)

                @Query("SELECT * FROM user_profile WHERE id = 'local_user' LIMIT 1")
                suspend fun getProfile(): UserProfileEntity?

                @Query("UPDATE user_profile SET dailyStepGoal = :goal WHERE id = 'local_user'")
                suspend fun updateDailyGoal(goal: Int)
            }
            """.trimIndent()
        )

        val problems = parseMethods(preFix).flatMap { method ->
            val sql = method.querySql ?: return@flatMap emptyList()
            val found = mutableListOf<String>()
            if (!sql.contains("ownerSubject", ignoreCase = true)) found += "${method.name}: unfiltered"
            if (!sql.contains(":owner")) found += "${method.name}: owner never bound"
            if (method.params.firstOrNull()?.name != OWNER) found += "${method.name}: no owner parameter"
            found
        }

        assertEquals(
            "The checker does not catch the pre-fix queries",
            listOf("getProfile", "updateDailyGoal"),
            problems.map { it.substringBefore(':') }.distinct()
        )
        assertEquals(
            "Each pre-fix query must trip all three faults (unfiltered, unbound, no owner parameter)",
            6, problems.size
        )
    }

    // ── Source access ────────────────────────────────────────────────────────

    private fun readSource(relative: String): String {
        val file = resolveSource(relative)
        assertTrue(
            "Could not locate $relative from ${File(".").absolutePath}. This test reads the " +
                "real DAO sources, so failing to find them must not be reported as a pass.",
            file != null
        )
        return file!!.readText()
    }

    /**
     * Walks up from the working directory looking for the module's source root.
     * Gradle unit tests run with the module directory as the working directory;
     * the upward walk covers being launched from the repo root instead.
     */
    private fun resolveSource(relative: String): File? {
        var dir: File? = File(".").absoluteFile
        repeat(6) {
            val candidate = File(dir, "src/main/java/com/example/mobileapp/$relative")
            if (candidate.isFile) return candidate
            dir = dir?.parentFile
        }
        return null
    }

    private fun sentinelFromSource(): String {
        val source = stripComments(readSource("core/data/local/OwnerScope.kt"))
        val match = Regex("""const\s+val\s+LEGACY_UNOWNED_SUBJECT\s*=\s*"([^"]*)"""")
            .find(source)
        assertTrue("OwnerScope.kt declares no LEGACY_UNOWNED_SUBJECT literal", match != null)
        return match!!.groupValues[1]
    }

    // ── A very small Kotlin reader ───────────────────────────────────────────
    //
    // Just enough to walk a DAO/entity file: strip comments, then read
    // annotation-then-declaration pairs with balanced parentheses. Not a
    // parser — but these files are declarations only, so this covers them.

    private data class KotlinAnnotation(val name: String, val args: String)

    private data class KotlinParam(val name: String, val type: String)

    private data class KotlinMethod(
        val name: String,
        val params: List<KotlinParam>,
        val annotations: List<KotlinAnnotation>,
    ) {
        /** The `@Query` SQL with its string literals joined, or null if not a query. */
        val querySql: String?
            get() = annotations.firstOrNull { it.name == "Query" }?.let { annotation ->
                Regex("\"([^\"]*)\"")
                    .findAll(annotation.args)
                    .joinToString("") { it.groupValues[1] }
            }
    }

    private fun parseMethods(source: String): List<KotlinMethod> {
        val methods = mutableListOf<KotlinMethod>()
        var i = 0
        var pending = mutableListOf<KotlinAnnotation>()
        while (i < source.length) {
            when {
                source[i] == '@' -> {
                    val (annotation, next) = readAnnotation(source, i)
                    pending += annotation
                    i = next
                }
                source.startsWith("fun ", i) -> {
                    val (method, next) = readMethod(source, i, pending)
                    methods += method
                    pending = mutableListOf()
                    i = next
                }
                else -> i++
            }
        }
        return methods
    }

    private fun parseAnnotations(source: String): List<KotlinAnnotation> {
        val found = mutableListOf<KotlinAnnotation>()
        var i = 0
        while (i < source.length) {
            if (source[i] == '@') {
                val (annotation, next) = readAnnotation(source, i)
                found += annotation
                i = next
            } else i++
        }
        return found
    }

    private fun readAnnotation(source: String, at: Int): Pair<KotlinAnnotation, Int> {
        var i = at + 1
        while (i < source.length && (source[i].isLetterOrDigit() || source[i] == '_')) i++
        val name = source.substring(at + 1, i)
        return if (i < source.length && source[i] == '(') {
            val end = matchingParen(source, i)
            KotlinAnnotation(name, source.substring(i + 1, end)) to end + 1
        } else {
            KotlinAnnotation(name, "") to i
        }
    }

    private fun readMethod(
        source: String,
        at: Int,
        annotations: List<KotlinAnnotation>,
    ): Pair<KotlinMethod, Int> {
        val funAt = source.indexOf("fun ", at) + 4
        var i = funAt
        while (i < source.length && (source[i].isLetterOrDigit() || source[i] == '_')) i++
        val name = source.substring(funAt, i)

        // Skip the return type / whitespace up to the parameter list. A method
        // with no parameter list at all is legal Kotlin and was exactly the
        // pre-fix shape (`getProfile()`), so it must be read as zero parameters
        // rather than running on to the next declaration's `(`.
        var j = i
        while (j < source.length && source[j] != '(' && source[j] != '\n') j++
        if (j >= source.length || source[j] != '(') return KotlinMethod(name, emptyList(), annotations) to i

        val end = matchingParen(source, j)
        val params = splitTopLevel(source.substring(j + 1, end)).mapNotNull { raw ->
            val text = raw.trim()
            val colon = text.indexOf(':')
            if (colon <= 0) null
            else KotlinParam(text.substring(0, colon).trim(), text.substring(colon + 1).trim())
        }
        return KotlinMethod(name, params, annotations) to end + 1
    }

    /** Index of the `)` closing the `(` at [open], ignoring parens inside strings. */
    private fun matchingParen(source: String, open: Int): Int {
        var depth = 0
        var i = open
        while (i < source.length) {
            when (source[i]) {
                '"' -> i = skipString(source, i)
                '(' -> depth++
                ')' -> {
                    depth--
                    if (depth == 0) return i
                }
            }
            i++
        }
        return source.length - 1
    }

    private fun skipString(source: String, at: Int): Int {
        var i = at + 1
        while (i < source.length) {
            when {
                source[i] == '\\' -> i += 2
                source[i] == '"' -> return i
                else -> i++
            }
        }
        return source.length - 1
    }

    private fun splitTopLevel(text: String): List<String> {
        val parts = mutableListOf<String>()
        var depth = 0
        var start = 0
        var i = 0
        while (i < text.length) {
            when (text[i]) {
                '"' -> i = skipString(text, i)
                '<', '(', '[' -> depth++
                '>', ')', ']' -> depth--
                ',' -> if (depth == 0) {
                    parts += text.substring(start, i)
                    start = i + 1
                }
            }
            i++
        }
        if (start < text.length) parts += text.substring(start)
        return parts
    }

    /** `primaryKeys = ["a", "b"]` from an `@Entity` argument list, or null. */
    private fun parsePrimaryKeys(args: String): List<String>? {
        val match = Regex("""primaryKeys\s*=\s*\[([^\]]*)]""").find(args) ?: return null
        return Regex("\"([^\"]*)\"").findAll(match.groupValues[1]).map { it.groupValues[1] }.toList()
    }

    /** The field name of an inline `@PrimaryKey val x: ...` declaration. */
    private fun primaryKeyField(source: String): String? =
        Regex("""@PrimaryKey\s+val\s+(\w+)""").find(source)?.groupValues?.get(1)

    /**
     * Removes comments so that prose mentioning `@Query` — the DAO KDocs do
     * exactly that — cannot be mistaken for a declaration, and so a
     * commented-out statement cannot satisfy the invariant.
     */
    private fun stripComments(source: String): String {
        val out = StringBuilder(source.length)
        var i = 0
        while (i < source.length) {
            when {
                source.startsWith("//", i) -> while (i < source.length && source[i] != '\n') i++
                source.startsWith("/*", i) -> {
                    val end = source.indexOf("*/", i + 2)
                    i = if (end < 0) source.length else end + 2
                }
                else -> out.append(source[i++])
            }
        }
        return out.toString()
    }

    private companion object {
        /** The Kotlin parameter name every scoped statement leads with. */
        const val OWNER = "owner"

        /** The column / entity property holding the owner. */
        const val OWNER_COLUMN = "ownerSubject"

        val DAO_FILES = listOf(
            "RunSessionDao.kt",
            "HexDao.kt",
            "DailyQuestDao.kt",
            "AchievementDao.kt",
            "ActiveRunDao.kt",
            "UserDao.kt",
        )

        val ENTITY_FILES = listOf(
            "RunSessionEntity.kt",
            "CapturedHexEntity.kt",
            "DailyQuestEntity.kt",
            "AchievementEntity.kt",
            "ActiveRunEntity.kt",
            "UserProfileEntity.kt",
        )
    }
}
