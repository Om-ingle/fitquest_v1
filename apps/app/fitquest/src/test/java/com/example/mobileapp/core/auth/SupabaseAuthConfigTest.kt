package com.example.mobileapp.core.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * M11 (F-04) — SUPABASE_URL is operator-supplied text, so it arrives in whatever
 * shape the operator pasted. Every case below is one that produces a silent
 * 404 (which looks exactly like a wrong password) if it is not normalised.
 */
class SupabaseAuthConfigTest {

    @Test
    fun `a bare project url gains exactly one auth path`() {
        assertEquals(
            "https://abcdefg.supabase.co/auth/v1/",
            supabaseAuthBaseUrl("https://abcdefg.supabase.co"),
        )
    }

    @Test
    fun `trailing slashes do not double the path`() {
        assertEquals(
            "https://abcdefg.supabase.co/auth/v1/",
            supabaseAuthBaseUrl("https://abcdefg.supabase.co/"),
        )
        assertEquals(
            "https://abcdefg.supabase.co/auth/v1/",
            supabaseAuthBaseUrl("https://abcdefg.supabase.co///"),
        )
    }

    @Test
    fun `a url that already names the auth path is not doubled`() {
        // Straight from Supabase's own docs, which show the full endpoint.
        assertEquals(
            "https://abcdefg.supabase.co/auth/v1/",
            supabaseAuthBaseUrl("https://abcdefg.supabase.co/auth/v1"),
        )
        assertEquals(
            "https://abcdefg.supabase.co/auth/v1/",
            supabaseAuthBaseUrl("https://abcdefg.supabase.co/auth/v1/"),
        )
    }

    @Test
    fun `surrounding whitespace is tolerated`() {
        assertEquals(
            "https://abcdefg.supabase.co/auth/v1/",
            supabaseAuthBaseUrl("  https://abcdefg.supabase.co  "),
        )
    }

    @Test
    fun `an unset value is not a url`() {
        // The state of every build that has not been given the Supabase values.
        // It must be distinguishable from a typo, and must never reach Retrofit
        // (which rejects a blank base URL by throwing at construction).
        assertNull(supabaseAuthBaseUrl(null))
        assertNull(supabaseAuthBaseUrl(""))
        assertNull(supabaseAuthBaseUrl("   "))
    }

    @Test
    fun `a value with no scheme is rejected rather than guessed at`() {
        assertNull(supabaseAuthBaseUrl("abcdefg.supabase.co"))
        assertNull(supabaseAuthBaseUrl("ftp://abcdefg.supabase.co"))
    }

    @Test
    fun `a url that is only the auth path is rejected`() {
        assertNull(supabaseAuthBaseUrl("/auth/v1"))
    }
}
