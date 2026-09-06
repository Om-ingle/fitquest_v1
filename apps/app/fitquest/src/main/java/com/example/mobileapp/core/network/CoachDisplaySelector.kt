package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse

/**
 * M8.5 — the freshness-aware choice between the LIVE push slot and the pull
 * cache, shown by the Home coach card.
 *
 * Before M8.5 the UI preferred a live push unconditionally whenever one was
 * present (`livePush?.let { Success(it) } ?: pull`). The push slot is
 * process-lifetime, so after a genuinely new credited run that reached the app
 * through the pull path — or when the WebSocket was unavailable/suppressed and
 * no push arrived — an older live push could shadow a fresh pull response
 * forever.
 *
 * Decision (freshness over source). The response grounded in the NEWER server
 * context wins, regardless of whether it arrived by push or by pull:
 *
 *  - same [CoachResponse.context_fingerprint] -> the live-push presentation is
 *    preserved (the card does not churn between two views of the same context);
 *  - different (or missing) fingerprints -> the response with the newer
 *    [CoachResponse.generated_at] wins, so a fresh pull displaces a stale live
 *    and a fresh live displaces a stale pull;
 *  - equal / indeterminate freshness -> keep the live push (the pre-M8.5
 *    default), because a live push is grounded in a just-fired trigger.
 *
 * `generated_at` is compared exactly as the backend serialises it — naive UTC
 * ISO-8601 (`2026-09-06T12:00:00` or `2026-09-06T12:00:00.123456`). No date
 * library is used (minSdk 24 has no java.time without core library desugaring);
 * the string is canonicalised to a fixed-width sort key and compared
 * lexicographically, which is exact for that single, known serialisation. A
 * timestamp that does not match is treated as indeterminate and the caller
 * falls back to the live push — never a crash.
 *
 * Pure: no state, no I/O, no clock.
 */
object CoachDisplaySelector {

    /**
     * What the card should show: the [outcome] to render and whether that
     * response came from the LIVE channel ([isLive], which picks the
     * "⚡ Live coaching" heading).
     */
    fun select(livePush: CoachResponse?, pull: CoachFetcher.Outcome?): CoachDisplay {
        // No live push -> exactly the pull outcome (or null = still loading).
        val live = livePush ?: return CoachDisplay(pull, isLive = false)

        // A live push exists but the pull is not a usable Success (loading,
        // http/network/malformed error) -> show the live push, as before; an
        // error must never hide a good live message.
        val pullSuccess = pull as? CoachFetcher.Outcome.Success
            ?: return CoachDisplay(CoachFetcher.Outcome.Success(live), isLive = true)

        // Same server context -> keep the live-push presentation. (For the same
        // context the pull cache and the push are two generations of the same
        // advice; churning the card adds nothing.)
        val liveFingerprint = live.context_fingerprint
        if (liveFingerprint != null && liveFingerprint == pullSuccess.response.context_fingerprint) {
            return CoachDisplay(CoachFetcher.Outcome.Success(live), isLive = true)
        }

        // Different context -> the strictly newer generation wins, source-agnostic.
        val pullNewer = isStrictlyNewer(
            pullSuccess.response.generated_at,
            live.generated_at
        )
        return if (pullNewer) {
            CoachDisplay(pullSuccess, isLive = false)
        } else {
            CoachDisplay(CoachFetcher.Outcome.Success(live), isLive = true)
        }
    }

    private fun isStrictlyNewer(candidate: String?, reference: String?): Boolean {
        val candidateKey = generatedAtSortKey(candidate) ?: return false
        val referenceKey = generatedAtSortKey(reference) ?: return false
        return candidateKey > referenceKey
    }
}

/** Rendered coach outcome plus whether it arrived live (drives the heading). */
data class CoachDisplay(
    val outcome: CoachFetcher.Outcome?,
    val isLive: Boolean,
)

/**
 * Fixed-width chronological sort key for the backend's naive-UTC `generated_at`
 * (`yyyy-MM-dd[ T]HH:mm:ss` optionally followed by a fractional second) ->
 * `yyyyMMddHHmmss` + a 9-digit fraction (right-padded with zeros). Keys always
 * have the same length, so lexicographic comparison equals chronological
 * comparison. Returns null when the string does not match the known
 * serialisation.
 */
internal fun generatedAtSortKey(raw: String?): String? {
    if (raw.isNullOrBlank()) return null
    val match = GENERATED_AT_PATTERN.matchEntire(raw.trim()) ?: return null
    val g = match.groupValues
    val base = g[1] + g[2] + g[3] + g[4] + g[5] + g[6]
    val fraction = g[7]
    val frac = if (fraction.isEmpty()) "000000000" else (fraction + "000000000").take(9)
    return base + frac
}

private val GENERATED_AT_PATTERN = Regex(
    "(\\d{4})-(\\d{2})-(\\d{2})[T ](\\d{2}):(\\d{2}):(\\d{2})(?:\\.(\\d{1,9}))?"
)
