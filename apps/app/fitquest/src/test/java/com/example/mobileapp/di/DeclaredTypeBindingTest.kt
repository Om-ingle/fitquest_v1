package com.example.mobileapp.di

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Every interface a Koin consumer declares must have a binding registered under
 * that interface — not merely under the concrete class that implements it.
 *
 * ### The mistake this exists to stop, and why it keeps happening
 *
 * Koin resolves `get()` against the *declared parameter type* of the consumer.
 * So a seam extracted for testability — `AuthInterceptor` behind `Interceptor`,
 * `HexCaptureEngine` behind `RunSessionEngine`, `ForegroundRunServiceLauncher`
 * behind `RunServiceLauncher` — is invisible to the container unless the module
 * binds it *as the interface*. Binding only the concrete class leaves the graph
 * with no definition for the type the consumer asks for.
 *
 * That has now happened three times in this module:
 *
 *  1. `okhttp3.Interceptor` / `okhttp3.Authenticator` — killed the app at launch
 *     with `NoBeanDefFoundException` on the first `MainActivity.onStart` (M11).
 *  2. `RunSessionEngine` — caught while writing the module, by luck.
 *  3. `RunServiceLauncher` — shipped. `ActiveRunController` could not be built,
 *     so `AccountScopeCoordinator` could not be built either, so the
 *     account-switch reset silently never ran. `FitQuestApp` catches the
 *     failure and logs it, so the app looked healthy: no crash, no visible
 *     symptom, and a privacy control that simply wasn't there.
 *
 * ### Why this is a source-parsing test
 *
 * `AppModuleGraphTest` resolves the clients it can, but it deliberately stops
 * where a `Context` is needed — and every run-lifecycle binding descends from
 * one through `ForegroundRunServiceLauncher(context)`. A JVM test has no
 * `Context` to give it, so the coordinator's dependency slice cannot be
 * instantiated here at all, which is exactly the slice that broke.
 *
 * So this test asserts the *rule* the container depends on, statically: for
 * every class the module registers, each constructor parameter whose type is an
 * interface declared in this project must have a binding registered under that
 * interface's name. It needs no Context, no container and no device.
 *
 * ### What it deliberately does not check
 *
 * Only project-declared interfaces. Android and third-party interface types
 * (`Context`, `CoroutineScope`, `okhttp3.Interceptor`) are provided by other
 * means or by their own dedicated tests, and folding them in would mean an
 * allowlist that grows every time a dependency is added — a test that has to be
 * edited to keep passing is one that stops being read.
 */
class DeclaredTypeBindingTest {

    /**
     * The invariant. Fails with the class, the unbound type and the fix.
     */
    @Test
    fun every_interface_a_consumer_declares_is_registered_under_that_interface() {
        val violations = unboundInterfaceParameters(
            moduleSource = moduleSource(),
            classSources = classSources(),
            interfaces = interfaceNames(),
        )
        assertTrue(
            "A Koin consumer declares an interface that the module never " +
                "registers under that interface. Koin resolves `get()` against " +
                "the DECLARED type, so this binding cannot be constructed and " +
                "resolving it throws NoBeanDefFoundException at runtime — " +
                "silently, wherever the failure is caught and logged.\n\n" +
                violations.joinToString("\n") { "  • $it" } +
                "\n\nFix: register it as `single<TheInterface> { TheImplementation(get()) }` " +
                "alongside the concrete binding.",
            violations.isEmpty(),
        )
    }

    /**
     * The test's teeth, proven rather than assumed.
     *
     * Runs the same checker over the module as it was BEFORE the fix — the
     * concrete-only `ForegroundRunServiceLauncher` registration, which is the
     * exact shape that shipped and produced no crash and no symptom — and
     * asserts it is caught, and caught *by name*.
     *
     * Without this, a checker that silently matched nothing (a renamed file, a
     * regex that stopped matching after a refactor) would report success
     * forever, and the invariant would be decorative.
     */
    @Test
    fun the_invariant_rejects_the_concrete_only_registration_that_shipped() {
        // Derived from the real module rather than retyped: an embedded copy
        // would drift out of date and the self-check would quietly stop
        // describing the code it claims to describe.
        val real = moduleSource()
        val preFix = real.replace(
            "single<com.example.mobileapp.core.run.RunServiceLauncher> {",
            "single {",
        )
        assertNotEquals(
            "the pre-fix rewrite did not apply — the registration it targets has " +
                "been renamed or reshaped, so this self-check is no longer " +
                "testing the shape that shipped and must be updated",
            real,
            preFix,
        )

        val violations = unboundInterfaceParameters(
            moduleSource = preFix,
            classSources = classSources(),
            interfaces = interfaceNames(),
        )

        assertEquals(
            "the checker must catch the concrete-only registration that shipped, " +
                "and name exactly the unbound type — found: $violations",
            listOf("ActiveRunController needs RunServiceLauncher"),
            violations,
        )
    }

    // ── the checker ─────────────────────────────────────────────────────────

    /**
     * Returns one entry per (consumer, unbound interface) pair, sorted and
     * de-duplicated so the failure message is stable.
     */
    private fun unboundInterfaceParameters(
        moduleSource: String,
        classSources: Map<String, String>,
        interfaces: Set<String>,
    ): List<String> {
        val registered = registeredTypeNames(moduleSource)
        return classSources
            .filterKeys { it in registered }
            .flatMap { (className, source) ->
                constructorParameterTypes(source, className)
                    .filter { it in interfaces && it !in registered }
                    .map { "$className needs $it" }
            }
            .distinct()
            .sorted()
    }

    /**
     * Every type name the module provides a definition for.
     *
     * Three registration shapes exist in `appModule` and all three have to be
     * read, because a consumer does not care which one supplied its dependency:
     *
     *  * an explicit generic — `single<HexRepository> { … }`
     *  * a bare registration, where Koin infers the type from the constructor —
     *    `single { ActiveRunController(…) }`, `single { SupabaseAuthClient.create(…) }`
     *  * a Room accessor — `single { get<FitQuestDatabase>().hexDao() }`, whose
     *    type is the return of `hexDao()`, i.e. `HexDao`
     */
    private fun registeredTypeNames(moduleSource: String): Set<String> {
        val names = mutableSetOf<String>()

        EXPLICIT_BINDING.findAll(moduleSource).forEach {
            names += it.groupValues[1].substringAfterLast('.')
        }

        LAMBDA_BINDING.findAll(moduleSource).forEach { match ->
            val body = match.groupValues[1]
            // `Foo(`, `pkg.Foo(`, `Foo.Bar(` — the callee's last segment is the
            // type Koin records. `Log.d(` is not a match: the segment after the
            // dot must itself be capitalised.
            CALLEE.findAll(body).forEach { names += it.groupValues[1].substringAfterLast('.') }
            // Room accessors: `hexDao()` → `HexDao`.
            DAO_ACCESSOR.findAll(body).forEach {
                names += it.groupValues[1].replaceFirstChar(Char::uppercase)
            }
        }

        return names
    }

    /** The primary constructor's parameter types, simple names only. */
    private fun constructorParameterTypes(source: String, className: String): List<String> {
        val declaration = Regex(
            """(?m)^\s*(?:[\w.]+\s+)*class\s+${Regex.escape(className)}\s*\("""
        ).find(source) ?: return emptyList()

        val open = source.indexOf('(', declaration.range.first)
        val close = matchingParen(source, open) ?: return emptyList()

        return splitTopLevel(source.substring(open + 1, close)).mapNotNull { parameter ->
            // `private val serviceLauncher: RunServiceLauncher = X` → RunServiceLauncher
            PARAMETER_TYPE.find(parameter)?.groupValues?.get(1)?.substringAfterLast('.')
        }
    }

    /** Index of the `)` matching the `(` at [open], or null if unbalanced. */
    private fun matchingParen(source: String, open: Int): Int? {
        var depth = 0
        for (i in open until source.length) {
            when (source[i]) {
                '(' -> depth++
                ')' -> {
                    depth--
                    if (depth == 0) return i
                }
            }
        }
        return null
    }

    /**
     * Splits a parameter list on commas that are at nesting depth zero, so a
     * generic's own comma (`Map<String, Int>`) does not split a parameter in two.
     */
    private fun splitTopLevel(text: String): List<String> {
        val parts = mutableListOf<String>()
        var depth = 0
        var start = 0
        text.forEachIndexed { i, c ->
            when (c) {
                '(', '<', '[' -> depth++
                ')', '>', ']' -> depth--
                ',' -> if (depth == 0) {
                    parts += text.substring(start, i)
                    start = i + 1
                }
            }
        }
        parts += text.substring(start)
        return parts.map(String::trim).filter(String::isNotEmpty)
    }

    // ── project source ──────────────────────────────────────────────────────

    /**
     * The package root under `main`. Found by walking up rather than assuming a
     * working directory, and it fails loudly: a checker that cannot find the
     * sources it is meant to check must not report a pass.
     */
    private fun mainRoot(): File {
        var dir: File? = File(".").absoluteFile
        repeat(8) {
            val candidate = File(dir, "src/main/java/com/example/mobileapp")
            if (candidate.isDirectory) return candidate
            dir = dir?.parentFile
        }
        throw AssertionError(
            "could not locate src/main/java/com/example/mobileapp from " +
                "${File(".").absolutePath} — this test cannot verify anything " +
                "without the sources it parses, so it must not pass"
        )
    }

    private fun moduleSource(): String = File(mainRoot(), "di/AppModule.kt").readText()

    private fun classSources(): Map<String, String> {
        val byName = mutableMapOf<String, String>()
        mainRoot().walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .forEach { file ->
                val text = file.readText()
                CLASS_DECL.findAll(text).forEach { byName.putIfAbsent(it.groupValues[1], text) }
            }
        return byName
    }

    /** Simple names of every interface this project declares. */
    private fun interfaceNames(): Set<String> =
        mainRoot().walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .flatMap { file -> INTERFACE_DECL.findAll(file.readText()).map { it.groupValues[1] } }
            .toSet()

    private companion object {
        val EXPLICIT_BINDING = Regex("""(?:single|factory)\s*<\s*([\w.]+)\s*>""")
        val LAMBDA_BINDING = Regex("""(?:single|factory)\s*\{([^{}]*)\}""")
        val CALLEE = Regex("""([A-Z]\w*(?:\.[A-Z]\w*)*)\s*\(""")
        val DAO_ACCESSOR = Regex("""get<[\w.]+>\(\)\.(\w+)\(\)""")
        val CLASS_DECL = Regex("""(?m)^\s*(?:[\w.]+\s+)*class\s+([A-Z]\w*)\s*[\(<]""")
        val INTERFACE_DECL = Regex("""(?m)^\s*(?:[\w.]+\s+)*interface\s+([A-Z]\w*)""")
        val PARAMETER_TYPE = Regex("""(?:val|var)?\s*\w+\s*:\s*([\w.]+)""")
    }
}
