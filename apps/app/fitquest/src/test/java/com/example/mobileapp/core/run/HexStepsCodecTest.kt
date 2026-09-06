package com.example.mobileapp.core.run

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * JVM unit tests for the compact hexId->steps checkpoint codec. It must round
 * trip losslessly and degrade gracefully on blank/malformed legacy values so a
 * corrupt checkpoint never crashes process-death recovery.
 */
class HexStepsCodecTest {

    @Test
    fun roundTripsSingleEntry() {
        val map = mapOf("8a60961611a7fff" to 42)
        assertEquals(map, HexStepsCodec.decode(HexStepsCodec.encode(map)))
    }

    @Test
    fun roundTripsManyEntries() {
        val map = linkedMapOf(
            "8a60961611a7fff" to 12,
            "8a60961611a7ffe" to 340,
            "8a60961611a7ffd" to 7
        )
        assertEquals(map, HexStepsCodec.decode(HexStepsCodec.encode(map)))
    }

    @Test
    fun emptyMapEncodesToBlank() {
        assertEquals("", HexStepsCodec.encode(emptyMap()))
        assertEquals(emptyMap<String, Int>(), HexStepsCodec.decode(""))
        assertEquals(emptyMap<String, Int>(), HexStepsCodec.decode(null))
        assertEquals(emptyMap<String, Int>(), HexStepsCodec.decode("   "))
    }

    @Test
    fun malformedTokensAreSkipped() {
        val encoded = "abc:10,broken,x:y,onlycolon:,z,keep:5"
        assertEquals(mapOf("abc" to 10, "keep" to 5), HexStepsCodec.decode(encoded))
    }

    @Test
    fun legacyObjectPlaceholderDecodesToEmpty() {
        // Older/invalid writers may have stored "{}"; it must not crash.
        assertEquals(emptyMap<String, Int>(), HexStepsCodec.decode("{}"))
    }

    @Test
    fun hexIdAlphabetNeverCollidesWithDelimiter() {
        // H3 index digits include a-v; none of them are ':' or ',', so a map
        // whose keys span the full alphabet still round-trips unambiguously.
        val map = mapOf("a" to 1, "v" to 2, "0" to 3, "9" to 4, "f0a1b2" to 5)
        assertEquals(map, HexStepsCodec.decode(HexStepsCodec.encode(map)))
    }
}
