package com.example.mobileapp.core.auth

import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * M11 (F-04) — the authenticated-encryption envelope used for stored sessions.
 *
 * Kept free of every Android type on purpose (plain `javax.crypto` plus a
 * [SecretKey] the caller supplies), so the envelope itself is covered by fast
 * JVM unit tests in `src/test`. Only the key's origin — the Android keystore —
 * needs a device, and that is the one part with no logic to get wrong.
 *
 * ### The format
 *
 * ```
 * [ 12-byte IV ][ ciphertext ][ 16-byte GCM tag ]
 * ```
 *
 * AES-256-GCM, with a fresh random IV per encryption and the IV stored
 * alongside the ciphertext.
 *
 * The IV is not secret and does not need to be — but it must never REPEAT under
 * the same key, which is exactly what GCM's security proof depends on: a
 * repeated IV with the same key leaks the XOR of the two plaintexts and, worse,
 * the authentication key. Generating it inside [Cipher.init] (rather than
 * deriving it from a counter, a timestamp, or anything else the app controls)
 * is what makes that guarantee the platform's responsibility instead of ours.
 *
 * GCM is authenticated: [decrypt] fails rather than returning corrupted bytes,
 * so a tampered or truncated blob is detected, not silently trusted.
 */
internal object AesGcmCodec {

    const val TRANSFORMATION = "AES/GCM/NoPadding"

    /** 128-bit authentication tag — the maximum GCM offers. */
    const val TAG_BITS = 128

    /** GCM's standard IV length, and the length `Cipher.init` generates. */
    const val IV_BYTES = 12

    fun encrypt(key: SecretKey, plaintext: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key) // fresh random IV, per call
        val iv = cipher.iv
        require(iv.size == IV_BYTES) { "unexpected GCM IV length: ${iv.size}" }
        return iv + cipher.doFinal(plaintext)
    }

    fun decrypt(key: SecretKey, payload: ByteArray): ByteArray {
        require(payload.size > IV_BYTES) { "payload is too short to contain an IV and a tag" }
        val iv = payload.copyOfRange(0, IV_BYTES)
        val body = payload.copyOfRange(IV_BYTES, payload.size)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, iv))
        return cipher.doFinal(body)
    }
}
