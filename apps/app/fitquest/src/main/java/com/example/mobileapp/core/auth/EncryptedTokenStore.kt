package com.example.mobileapp.core.auth

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import com.google.gson.Gson
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/**
 * M11 (F-04) — the on-device session store: ciphertext in SharedPreferences,
 * key material in the Android keystore.
 *
 * ### What is actually protected, and from what
 *
 * The key is generated inside the Android keystore and never leaves it: this
 * class can ask the keystore to encrypt and decrypt, but cannot read the key
 * bytes, and neither can anything that gets hold of `fitquest.db` or the app's
 * private directory. A stolen device image, an `adb backup`, or a root-level
 * file copy therefore yields an opaque blob rather than a usable refresh token
 * — which matters because a refresh token is a long-lived credential that
 * outlives the app being closed.
 *
 * This is protection at rest. It is not protection from a compromised device:
 * code running as this app can call the same keystore. Nothing on a client can
 * change that, which is why the server never trusts the client's word about who
 * it is — the token is verified server-side on every request.
 *
 * ### Why the platform keystore and not a library
 *
 * `androidx.security:security-crypto` (EncryptedSharedPreferences) would be the
 * conventional choice, but the library is deprecated and adds a dependency to
 * do what the platform API already does. The code below is the same
 * construction — AES-256-GCM under a keystore-resident key — with the envelope
 * split into [AesGcmCodec] where it can be unit-tested.
 *
 * ### It cannot throw
 *
 * [TokenStore] implementations must never take the app down, and this one has a
 * genuine failure mode: the keystore key is destroyed when the device's lock
 * screen is removed or the app's data is restored onto a different device, and
 * decryption then fails permanently. That presents as "signed out" — the user
 * logs in again — and never as a crash on launch. If the keystore is
 * unavailable outright, the session is kept in memory for this process and
 * nothing is written to disk.
 */
class EncryptedTokenStore(context: Context) : TokenStore {

    private val prefs =
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val gson = Gson()

    /**
     * Used only when the keystore is unusable, so a session still works for
     * this process. Checked before [prefs] on read: it is the newer value.
     */
    @Volatile
    private var memoryFallback: AuthTokens? = null

    override fun load(): AuthTokens? {
        memoryFallback?.let { return it }

        val stored = prefs.getString(KEY_SESSION, null) ?: return null
        return try {
            val plaintext = AesGcmCodec.decrypt(secretKey(), decode(stored))
            gson.fromJson(String(plaintext, Charsets.UTF_8), AuthTokens::class.java)
        } catch (t: Throwable) {
            // Tampered, truncated, or encrypted under a key this device no
            // longer has. Log the fact, never the contents, and drop it.
            Log.w(TAG, "Stored session is unreadable; treating as signed out")
            clear()
            null
        }
    }

    override fun save(tokens: AuthTokens) {
        memoryFallback = tokens
        try {
            val plaintext = gson.toJson(tokens).toByteArray(Charsets.UTF_8)
            val blob = encode(AesGcmCodec.encrypt(secretKey(), plaintext))
            // apply(), not commit(): a lost write costs one re-login, while a
            // synchronous disk write here would be main-thread I/O on the
            // sign-in path.
            prefs.edit().putString(KEY_SESSION, blob).apply()
        } catch (t: Throwable) {
            // Keystore unavailable or key generation refused. Keep the session
            // in memory and write nothing — an unencrypted token on disk would
            // be worse than a session that ends when the app does.
            Log.w(TAG, "Session could not be encrypted; keeping it in memory only")
        }
    }

    override fun clear() {
        memoryFallback = null
        runCatching { prefs.edit().remove(KEY_SESSION).apply() }
    }

    /**
     * The AES key, generated on first use and thereafter owned by the keystore.
     *
     * No user-authentication requirement: a fitness app's session must survive
     * the screen locking, and the threat this defends against is offline
     * extraction of app storage, not someone holding an unlocked phone.
     */
    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(KEY_SIZE_BITS)
                .build()
        )
        return generator.generateKey()
    }

    private fun encode(bytes: ByteArray): String =
        Base64.encodeToString(bytes, Base64.NO_WRAP)

    private fun decode(value: String): ByteArray =
        Base64.decode(value, Base64.NO_WRAP)

    private companion object {
        const val TAG = "EncryptedTokenStore"
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "fitquest.auth.session.v1"
        const val KEY_SIZE_BITS = 256
        const val PREFS_NAME = "fitquest_auth"
        const val KEY_SESSION = "session"
    }
}
