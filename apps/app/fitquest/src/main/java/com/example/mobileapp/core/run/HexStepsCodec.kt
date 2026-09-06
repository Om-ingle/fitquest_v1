package com.example.mobileapp.core.run

/**
 * Compact, dependency-free encoding of a `hexId -> steps` map so a partial
 * session survives in the [ActiveRunEntity] checkpoint row.
 *
 * Format: `hex:steps,hex:steps`. H3 index strings are drawn from the alphabet
 * `0-9 a-v` (base-cell + per-resolution indexing digits), which never contains
 * `:` or `,`, so both delimiters are unambiguous. [decode] is tolerant of
 * blank input and malformed tokens so a corrupt legacy row degrades to an
 * empty map instead of crashing recovery.
 */
object HexStepsCodec {

    fun encode(hexesToSteps: Map<String, Int>): String =
        hexesToSteps.entries.joinToString(",") { (hex, steps) -> "$hex:$steps" }

    fun decode(encoded: String?): Map<String, Int> {
        if (encoded.isNullOrBlank()) return emptyMap()
        val result = LinkedHashMap<String, Int>()
        for (token in encoded.split(",")) {
            val sep = token.lastIndexOf(':')
            if (sep <= 0 || sep == token.length - 1) continue
            val hex = token.substring(0, sep)
            val steps = token.substring(sep + 1).toIntOrNull()
            if (hex.isEmpty() || steps == null) continue
            result[hex] = steps
        }
        return result
    }
}
