package com.example.mobileapp.core.network

import com.example.mobileapp.core.network.models.CoachResponse
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
 */
class LiveCoachStore {

    private val _message = MutableStateFlow<CoachResponse?>(null)
    val message: StateFlow<CoachResponse?> = _message.asStateFlow()

    fun publish(response: CoachResponse) {
        _message.value = response
    }

    /** Test/ops hook. The UI and client never clear it themselves. */
    fun clear() {
        _message.value = null
    }
}
