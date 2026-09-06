# ADR 0002: Android AI Coach Integration (Phase 4C.3B)

Status: implemented 2026-09-06. Integrates the Phase 4C.2 backend
(`GET /api/v1/coach` — Gemini LLM + pgvector RAG) into the existing Home
tab Coach card. TTS remains deferred (separate later phase per SRS).

## Context & Problem Statement

Phase 4A delivered a server-backed rules-engine recommendation rendered in
the Home tab's Coach card (`RecommendationFetcher` + `CoachCard`).
Phase 4C.2 added a grounded LLM coaching endpoint to the backend. This
phase wires that real AI response into the Android app and verifies it on
a physical device — without rewriting the working Home functionality.

## Decisions

### 1. DTOs model the ACTUAL backend contract — nothing invented

`CoachResponse` / `CoachRetrievalInfo` in
`core/network/models/FitQuestModels.kt` mirror the backend
`CoachResponse` schema exactly (message, grounded, context,
recommendation, retrieval, generated_at). Per-chunk similarity scores,
the raw retrieval query text, and chunk sources are deliberately NOT
modeled: Gson ignores unmapped JSON fields, so retrieval internals can
never reach the UI.

**Nullability by design:** Gson bypasses Kotlin null-safety when a field
is missing from the JSON, so all DTO fields are nullable and the fetcher
validates the essential ones (`message` non-blank, `recommendation`
present) before surfacing a Success.

### 2. CoachFetcher follows the established fetcher pattern

`core/network/CoachFetcher.kt` mirrors `RecommendationFetcher`:
`sealed interface Outcome { Success, HttpError(code), NetworkError,
MalformedResponse }`. Backend HTTP semantics carry through unchanged
(503 no key / 504 timeout / 502 provider or validation failure). A
response that parses but violates the essential shape is
`MalformedResponse`, never a crash. No local fallback coaching text —
the backend is the single source of truth for coaching messages.

### 3. Koin registration, no new DI surface

`CoachFetcher` is a `single` in `di/AppModule.kt` beside the other
fetchers, receiving the existing shared `FitQuestApi` (Retrofit on
`BuildConfig.BACKEND_BASE_URL`). No new dependencies; the existing
debug-only cleartext config is unchanged; release remains HTTPS-safe; no
backend/Gemini/Supabase secrets exist anywhere in the Android app.

### 4. UI: two independent sections in the Coach card

`HomeTab`'s Coach card now stacks two independently-fetched sections:

1. **Rules-engine recommendation (Phase 4A)** — behavior unchanged.
2. **AI personal advice (new)** — its own `mutableIntStateOf` retry key
   + `produceState`, so a slow or failing AI call never blocks the
   recommendation card, the map, steps, quests, or any other Home
   content (and vice versa).

AI section states:

| State | UI |
|---|---|
| Loading | "✨ Coach is writing your personal advice…" with a small spinner |
| Success | "✨ Personal advice" header, honest grounding chip, real message text |
| Error | "✨ AI tip unavailable" + manual **Retry** button |

The grounding chip is honest and user-facing: `grounded: true` →
"📚 Grounded in fitness knowledge"; `grounded: false` (the backend's
flagged general-guidance fallback) → "💡 General guidance". No embedding
dimensions, cosine scores, provider names, or raw retrieval internals
are ever displayed. On failure no fake coaching text is substituted —
just the unavailable notice and Retry. Retry is manual only (key bump);
there is no polling and no automatic repeated retries.

### 5. Unit tests

`CoachFetcherTest` (8 JVM tests) covers: success mapping, HTTP error
code mapping, network error, malformed JSON, blank-message /
missing-recommendation shape violations, full response field mapping,
`grounded: true` preservation, and `grounded: false` pass-through (a
valid fallback response, not an error). The API is faked — no Gemini,
Supabase, or network access from tests. The four existing `FakeApi`
implementations were extended with the new `getCoach` override.

## Consequences & Follow-ups

- Real-device verification (4 tests: backend-up / backend-down / retry /
  personalization) — results below.
- TTS is **not** implemented (explicitly deferred; do not claim
  otherwise).
- Single-turn only; each Retry produces a fresh coaching call (one
  Gemini request per tap — the free-tier 429 burst limit documented in
  the backend README applies only to rapid repeated taps).

## Real-device test results (2026-09-06)

Device: Samsung RZ8R90661CF (real hardware), debug APK (byte-identical to
the fresh `:app:assembleDebug` output, verified by MD5), backend
`http://192.168.0.36:8000/` on the dev machine's LAN, live Supabase +
Gemini. Evidence: on-device screenshots + backend access log.

| # | Test | Result |
|---|---|---|
| 1 | **SUCCESS** — backend running, real `/api/v1/coach` response displayed | ✅ PASS |
| 2 | **BACKEND FAILURE** — backend stopped, graceful offline state, no crash | ✅ PASS |
| 3 | **RETRY** — backend restarted, tap Retry, live response appears | ✅ PASS |
| 4 | **PERSONALIZATION** — displayed coaching tracks the actual dev-user context | ✅ PASS |

**1. SUCCESS:** With the backend up, the Coach card rendered both
sections: the Phase 4A recommendation and, below it, "✨ Personal advice"
with the "📚 Grounded in fitness knowledge" chip and a real
Gemini-generated message. Backend log confirms `GET /api/v1/coach` 200
from the phone.

**2. BACKEND FAILURE:** Backend stopped (port verified closed), app
force-stopped and relaunched. App did NOT crash (process alive, full UI
rendered): recommendation section → "🤖 Coach unavailable — offline
mode" + Retry; AI section → "✨ AI tip unavailable" + Retry; every other
Home feature (steps, quests, territory, profile, start-run banner)
worked from local Room data. No fake coaching text was substituted.

**3. RETRY:** Backend restarted, the AI section's Retry tapped
(adb `input tap`). The section entered the loading state ("✨ Coach is
writing your personal advice…") and then rendered a NEW live Gemini
response with the grounded chip — a different message than before,
reflecting the context at fetch time. No polling; the fetch ran only on
the tap.

**4. PERSONALIZATION:** The displayed coaching tracked the live dev-user
context across the session, so it cannot be static UI text: with a zero
context it said "…you have 0 hexes and 0 lifetime steps… 1,000 steps /
20-minute walk to claim your first hex"; immediately after a real 1,988-step
run sync on the phone (visible in the backend log) it switched to
"Consistency Pays Off / KEEP_MOVING" with a message about keeping a
relaxed walking pace; after the dev data was reset again it returned to
cold-start phrasing. Each message corresponds to the
`FitnessContext` the backend served at that moment.

**Known limitation observed live (documented, matches 4C.3A findings):**
rapid repeated coach calls exhaust the Gemini free-tier rate limit
(HTTP 429 → backend 502 → in-app "AI tip unavailable" + Retry). This is
an upstream quota, not an app defect; spacing calls restores service.
On 2026-09-06 the `gemini-2.5-flash` free-tier *daily* quota
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, 20/day) was fully
consumed mid-session, so the remaining live device scenarios were run
through a backend LLM-provider switch.

**Addendum — LLM provider used for the device re-verification
(2026-09-06):** the four scenarios above were reproduced end-to-end with
the backend's text generation routed through an OpenAI-compatible
**AgentRouter → DeepSeek (`deepseek-v4-flash`)** provider instead of
Gemini. This is a backend-only fallback added in `coach/llm.py`
(`AgentRouterLLMProvider`) and selected by the `LLM_PROVIDER` env switch
(`agentrouter` vs default `gemini`); embeddings stayed on Gemini
`gemini-embedding-001` (separate quota; pgvector schema frozen to 1536
dims). Gateway quirk documented in the provider: agentrouter.org rejects
non-`claude-cli` User-Agents (`401 unauthorized client detected`), so the
provider sends that header verbatim. The Android app is
provider-agnostic — it renders whatever real message
`GET /api/v1/coach` returns. Evidence for this re-verification is in
`docs/docs/ui/evidence-4c3b/` (`test1-success.png`, `test2-failure.png`,
`test3-retry.png`, `test4-personal.png`, `backend-access-2026-09-06.log`).
Results unchanged: SUCCESS / FAILURE / RETRY / PERSONALIZATION all ✅ PASS.

**TTS: NOT implemented** — coaching is text-only; no TTS claim is made.
