package com.example.mobileapp.core.auth

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/**
 * M11 (F-04) — the stored-session envelope, tested on the JVM.
 *
 * This is the part of secure storage that can actually be wrong: the Android
 * layer around it only fetches a key and writes a string. Everything that
 * matters — that a round trip is lossless, that a fresh IV is used every time,
 * and that tampering is DETECTED rather than silently decrypted — is asserted
 * here, with no device and no keystore.
 */
class AesGcmCodecTest {

    private fun key(): SecretKey =
        KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    private fun codecKey() = key()

    @Test
    fun `round trip returns exactly what was encrypted`() {
        val key = codecKey()
        val plaintext = "access token with spaces, ünïcode and \"quotes\"".toByteArray()

        val recovered = AesGcmCodec.decrypt(key, AesGcmCodec.encrypt(key, plaintext))

        assertArrayEquals(plaintext, recovered)
    }

    @Test
    fun `the same plaintext encrypts differently every time`() {
        // A fresh IV per encryption. If this ever failed, the same session
        // stored twice would produce identical ciphertext — and, worse, GCM
        // would be reusing an IV under one key, which breaks its security
        // rather than merely leaking equality.
        val key = codecKey()
        val plaintext = "same input".toByteArray()

        val first = AesGcmCodec.encrypt(key, plaintext)
        val second = AesGcmCodec.encrypt(key, plaintext)

        assertNotEquals(
            first.copyOfRange(0, AesGcmCodec.IV_BYTES).toList(),
            second.copyOfRange(0, AesGcmCodec.IV_BYTES).toList(),
        )
        assertFalse(first.contentEquals(second))
    }

    @Test
    fun `the payload carries an iv then ciphertext and tag`() {
        val key = codecKey()
        val plaintext = "1234567890".toByteArray() // 10 bytes -> 10 + 16-byte tag

        val payload = AesGcmCodec.encrypt(key, plaintext)

        assertEquals(AesGcmCodec.IV_BYTES + plaintext.size + AesGcmCodec.TAG_BITS / 8, payload.size)
    }

    @Test
    fun `a flipped ciphertext bit fails authentication instead of decrypting`() {
        val key = codecKey()
        val payload = AesGcmCodec.encrypt(key, "session".toByteArray())
        payload[payload.size - 1] = (payload[payload.size - 1].toInt() xor 0x01).toByte()

        assertRejected { AesGcmCodec.decrypt(key, payload) }
    }

    @Test
    fun `a flipped iv bit fails authentication`() {
        val key = codecKey()
        val payload = AesGcmCodec.encrypt(key, "session".toByteArray())
        payload[0] = (payload[0].toInt() xor 0x01).toByte()

        assertRejected { AesGcmCodec.decrypt(key, payload) }
    }

    @Test
    fun `a different key cannot decrypt the payload`() {
        // The realistic failure this models: the keystore key is gone (lock
        // screen removed, data restored to a new device) and the blob survives.
        // It must fail closed.
        val payload = AesGcmCodec.encrypt(codecKey(), "session".toByteArray())

        assertRejected { AesGcmCodec.decrypt(codecKey(), payload) }
    }

    @Test
    fun `a truncated payload is rejected`() {
        val key = codecKey()

        // Exactly an IV, no ciphertext or tag: GCM's tag check cannot even run.
        assertRejected { AesGcmCodec.decrypt(key, ByteArray(AesGcmCodec.IV_BYTES)) }
    }

    @Test
    fun `an empty plaintext still round trips and is still authenticated`() {
        val key = codecKey()

        val payload = AesGcmCodec.encrypt(key, ByteArray(0))

        assertArrayEquals(ByteArray(0), AesGcmCodec.decrypt(key, payload))
        assertTrue(payload.size > AesGcmCodec.IV_BYTES) // the tag is still there
    }

    private fun assertRejected(block: () -> Unit) {
        try {
            block()
            fail("decryption should have failed authentication")
        } catch (expected: Exception) {
            // Any failure is acceptable; silently returning corrupted bytes is not.
        }
    }
}
