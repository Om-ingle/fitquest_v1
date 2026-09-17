package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse
import com.example.mobileapp.core.session.AccountScopeGuard
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * M8.3B — the latest LIVE (pushed) coaching message for the dev user.
 *
 * This is deliberately SEPARATE from [CoachCache]. The pull cache keys its
 * "do I need to fetch again?" decision on the set of synced run ids and owns
 * the pull request lifecycle; a pushed response represents a DIFFERENT
 * trigger/context than whatever the last pull produced, so writing it into
 * [CoachCache] would corrupt that bookkeeping. Instead we keep one small
 * "latest live" slot and let the Home UI prefer it over the pull cache when
 * it is present.
 *
 * The value reuses the existing [CoachResponse] DTO (decoded by
 * [CoachingWsMessageParser]) so the rendering path is identical to pull.
 * Process-lifetime: the last live message survives navigation and brief
 * backgrounding (like the pull cache keeps its last Success); it is replaced
 * only by a newer push or cleared on process death.
 *
 * Thread-safety: [MutableStateFlow] makes publish() safe from the WebSocket's
 * own threads.
 *
 * Account scoping: a pushed message is addressed to the account whose session
 * held the socket open, so it must not survive into the next account's session.
 * [clear] is called when the signed-in account changes — the same path that
 * clears [CoachCache]. The socket itself is separately closed on sign-out by
 * `MainActivity` and on backgrounding.
 *
 * Fail closed: a pushed message arrives unsolicited, so it is the easiest of the
 * three surfaces to leave behind. [publish] is therefore refused outright while
 * [AccountScopeGuard] is closed — nothing is watching for an account change, so
 * a message accepted now would have nothing to clear it later. [clear] is never
 * gated: emptying is always the safe direction.
 */
class LiveCoachStore(private val accountScope: AccountScopeGuard) {

    private val _message = MutableStateFlow<CoachResponse?>(null)
    val message: StateFlow<CoachResponse?> = _message.asStateFlow()

    fun publish(response: CoachResponse) {
        if (!accountScope.isActive()) return
        _message.value = response
    }

    /** Drop the last pushed message, so it cannot outlive the account it was for. */
    fun clear() {
        _message.value = null
    }
}
