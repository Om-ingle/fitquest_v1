package com.example.mobileapp.di

import com.example.mobileapp.core.auth.AuthInterceptor
import com.example.mobileapp.core.auth.TokenRefreshAuthenticator
import com.example.mobileapp.core.network.CoachingWsClient
import com.example.mobileapp.core.network.FitQuestApi
import okhttp3.Authenticator
import okhttp3.Interceptor
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.koin.dsl.koinApplication

/**
 * The DI graph, built for real.
 *
 * ### Why this file exists
 *
 * M11 wired an authenticated OkHttp client into Koin and shipped. The app then
 * died on launch with
 *
 *   NoBeanDefFoundException: No definition found for type 'okhttp3.Interceptor'
 *
 * because `AppModule` registered `AuthInterceptor` and
 * `TokenRefreshAuthenticator` under their CONCRETE types while every consumer
 * declared the INTERFACE ones — `FitQuestApiClient.create(authInterceptor:
 * Interceptor, authenticator: Authenticator)` and the WebSocket client below
 * it. Koin's `get()` resolves against the declared parameter type, so the
 * graph had no definition for either interface. The 244 JVM tests in this
 * suite all passed, because every one of them constructs the collaborators
 * directly and none of them ever built the container: the defect was only
 * reachable from `MainActivity.onStart`, on a device.
 *
 * So these tests do the one thing the rest of the suite does not — start the
 * real [appModule] and resolve from it. They are deliberately a *graph* test
 * and not a behaviour test: the behaviour is already covered next to each
 * class, and what was missing was proof that the classes can be reached at all.
 *
 * ### What it would catch
 *
 * Any of these changes makes a test here fail, each with a message naming the
 * unresolvable type rather than a launch crash:
 *
 *   * reverting either registration to its concrete type
 *   * removing a binding, or renaming one without updating the consumers
 *   * a consumer that starts asking for a type nothing provides
 *   * dropping `single` in favour of `factory` for the two collaborators,
 *     which would silently break 401 refresh (see the last test)
 *
 * ### Scope
 *
 * Only the two authenticated clients are resolved, not the whole module.
 * Everything else in `appModule` descends from an Android `Context` (Room,
 * `StepSensorManager`, the TTS engine) or from `BuildConfig` values that a
 * unit test is not the right place to assert on, and constructing those here
 * would mean a Robolectric context to test wiring that this bug was not in.
 * `koinApplication` is used rather than `startKoin` so the container is local
 * to this class and cannot leak into, or be polluted by, another test.
 */
class AppModuleGraphTest {

    private val koin = koinApplication { modules(appModule) }.koin

    /**
     * The precise defect, asserted directly: the graph must answer for the
     * OkHttp INTERFACE types, because that is what its consumers ask for.
     *
     * Asserting the instance types too, so that a future binding which happens
     * to satisfy the key with the wrong collaborator still fails here.
     */
    @Test
    fun the_okhttp_interfaces_are_registered_under_the_types_consumers_ask_for() {
        val interceptor = koin.getOrNull<Interceptor>()
        assertNotNull(
            "no definition for okhttp3.Interceptor — AuthInterceptor must be " +
                "registered as single<Interceptor>, or FitQuestApi cannot be built",
            interceptor,
        )
        assertTrue(
            "okhttp3.Interceptor resolved to ${interceptor!!::class.java.name}, " +
                "expected AuthInterceptor",
            interceptor is AuthInterceptor,
        )

        val authenticator = koin.getOrNull<Authenticator>()
        assertNotNull(
            "no definition for okhttp3.Authenticator — TokenRefreshAuthenticator must " +
                "be registered as single<Authenticator>, or FitQuestApi cannot be built",
            authenticator,
        )
        assertTrue(
            "okhttp3.Authenticator resolved to ${authenticator!!::class.java.name}, " +
                "expected TokenRefreshAuthenticator",
            authenticator is TokenRefreshAuthenticator,
        )
    }

    /**
     * The REST client is the binding that actually crashed, and resolving it
     * runs `FitQuestApiClient.create` — the same call, with the same argument
     * types, that `MainActivity.onStart` reaches through
     * `CoachForegroundCoordinator` → `RunReconciler` → `RunSyncer`.
     */
    @Test
    fun the_container_can_build_the_authenticated_rest_client() {
        assertNotNull(
            "FitQuestApi is not resolvable from appModule: the app cannot start",
            koin.getOrNull<FitQuestApi>(),
        )
    }

    /**
     * The WebSocket client carries the same two collaborators, but resolves
     * them at a SECOND site: it builds its own `OkHttpClient` and asks for both
     * by hand, rather than having them injected through a declared parameter
     * type the way `FitQuestApiClient.create` does. Those two sites can
     * therefore disagree — this one was originally written against the
     * concrete types and so kept working while the REST client crashed. Both
     * now ask for the interfaces, and this test pins the second site so a
     * future change to one cannot silently break the other.
     */
    @Test
    fun the_container_can_build_the_authenticated_websocket_client() {
        assertNotNull(
            "CoachingWsClient is not resolvable from appModule",
            koin.getOrNull<CoachingWsClient>(),
        )
    }

    /**
     * The reason both clients share one authenticator.
     *
     * Supabase rotates refresh tokens: a second redemption of the same token
     * loses the session. Two clients holding two authenticators would each
     * redeem the one they were given, so the 401 refresh is only single-flight
     * if the container hands out the same instance to both. That is what
     * `single` buys, and it is invisible from any single class's own tests —
     * `TokenRefreshAuthenticatorTest` proves one authenticator refuses to loop,
     * not that there is only one of them.
     */
    @Test
    fun both_clients_share_one_authenticator_so_token_refresh_stays_single_flight() {
        // `assertSame` alone would pass here on two nulls, which is exactly the
        // broken state this class exists to catch — so the presence of the
        // binding is asserted first, and the identity check only means
        // something once there is an instance to compare.
        val first = koin.getOrNull<Authenticator>()
        val second = koin.getOrNull<Authenticator>()
        assertNotNull("the process must hold a TokenRefreshAuthenticator", first)
        assertSame(
            "the process must hold exactly one TokenRefreshAuthenticator",
            first,
            second,
        )
    }
}
