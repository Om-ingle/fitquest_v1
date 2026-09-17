package com.example.mobileapp.core.auth

/**
 * M11 (F-04) — where a session lives between app launches.
 *
 * Synchronous by design. The reader that matters most is the OkHttp bearer
 * interceptor, which runs on a network thread and must attach a token before
 * every request; making this interface `suspend` would force the interceptor to
 * block a coroutine dispatcher to answer a question that is already answered by
 * a value in memory.
 *
 * Implementations must never throw. A device whose keystore has been
 * invalidated (factory reset, restored backup, changed lock screen) will fail
 * to decrypt, and that must present as "signed out", never as a crash on
 * startup.
 */
interface TokenStore {

    /** The stored session, or null when there is none (or it cannot be read). */
    fun load(): AuthTokens?

    /** Persist the session, replacing any existing one. */
    fun save(tokens: AuthTokens)

    /** Remove the session. Must be safe to call when none is stored. */
    fun clear()
}

/**
 * A [TokenStore] that keeps the session in memory only.
 *
 * This is the test double — it makes the auth core exercisable on the JVM with
 * no Android keystore and no Robolectric — and it is also the honest fallback
 * for a device where the encrypted store is unavailable: a session that works
 * for this process is strictly better than no session at all, and it leaves
 * nothing on disk.
 */
class InMemoryTokenStore(initial: AuthTokens? = null) : TokenStore {

    @Volatile
    private var tokens: AuthTokens? = initial

    override fun load(): AuthTokens? = tokens

    override fun save(tokens: AuthTokens) {
        this.tokens = tokens
    }

    override fun clear() {
        tokens = null
    }
}
