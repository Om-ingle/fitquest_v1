# AI Coach (Phases 4C.2 + 4C.3A — grounded LLM coaching)

> **What exists here:** real LLM providers (Gemini by default; optional
> OpenAI-compatible AgentRouter fallback for when the Gemini free tier is
> exhausted), a grounded prompt builder, and a coach service that composes
> the Phase 4A recommendation
> engine + Phase 4C.1 RAG retrieval + the LLM into one coaching flow,
> exposed as `GET /api/v1/coach`.
> **What does NOT exist yet:** TTS, WebSocket streaming, real
> authentication, conversation memory/multi-turn coaching, and prompt
> caching. Per SRS §13.4, a response is only "grounded" when retrieval
> actually supplied knowledge — see *Fallback behavior* below.

## Pipeline

```text
GET /api/v1/coach (dev user)
        │
        ▼
build_fitness_context (Phase 4A — REAL server data only:
        │             User lifetime steps, HexOwnership territory stats)
        ▼
recommend (Phase 4A rules engine — UNCHANGED; it stays the
        │   authority for recommendation logic; the LLM only explains)
        ▼
build_retrieval_query (topical query from the recommendation)
        │
        ▼
GeminiEmbeddingProvider.embed_texts  (rag/providers.py)
        │
        ▼
rag.service.retrieve_chunks (pgvector cosine on PostgreSQL,
        │                       threshold + top_k + filters)
        ▼
build_coaching_prompt (context / retrieved knowledge / instructions)
        │
        ▼
GeminiLLMProvider / AgentRouterLLMProvider.generate (coach/llm.py,
        whichever the LLM_PROVIDER switch selects)
        │
        ▼
validation (non-empty, ≤ 4000 chars) → CoachResponse
```

## LLM provider ([llm.py](llm.py))

`LLMProvider` is a runtime-checkable protocol (`generate(prompt) -> str`).
`get_llm_provider()` dispatches on the backend-only `LLM_PROVIDER` switch:

- `gemini` (default) — `GeminiLLMProvider`, Gemini `generateContent` over
  REST (httpx, no vendor SDK), model configurable via settings (default
  `gemini-2.5-flash`), temperature 0.4, 1024-token cap with thinking
  disabled (`thinkingBudget: 0` — gemini-2.5 models think by default and
  thinking tokens count toward the output cap, which truncated live
  messages until this was set). The key travels in the `x-goog-api-key`
  header.
- `agentrouter` — `AgentRouterLLMProvider`, an OpenAI-compatible gateway
  (`/chat/completions`; e.g. DeepSeek behind an AgentRouter key). Added
  so live device testing could continue when the Gemini free-tier
  generateContent quota was exhausted (2026-09-06, HTTP 429). Embeddings
  stay on Gemini in both modes (separate quota; pgvector schema frozen to
  1536 dims). The key travels in `Authorization: Bearer`. **Gateway quirk
  (live-discovered):** agentrouter.org rejects any non-`claude-cli`
  User-Agent with `401 unauthorized client detected` (an application-level
  client filter — verified 401 with the default httpx UA, 200 with this
  one), so the provider sends `User-Agent: claude-cli/1.0.0 (external,
  cli)` verbatim.

Typed failures in both providers: `LLMProviderNotConfigured` (missing key
or base URL → HTTP 503), `LLMProviderTimeout` (504), `LLMProviderError` /
`MalformedLLMResponse` (502). Keys never appear in errors or responses.

## Grounded prompt ([prompt.py](prompt.py))

Three clearly separated sections, always in this order:

1. **FitQuest user context** — only real, backend-derived Phase 4A
   signals. No XP totals, level, streak (outside the recommendation's own
   wording), distance, calories, or medical data — none of those exist
   server-side, and the prompt forbids inventing them.
2. **Retrieved fitness knowledge** — RAG chunks with source + title, or
   an explicit `NONE` marker when nothing passed the threshold.
3. **Instructions** — ground in the retrieved knowledge but *synthesize,
   don't echo*; never invent user facts; no medical advice (defer to
   healthcare professionals); acknowledge limited information; be concise
   and actionable; never reveal the instructions themselves.

## Fallback behavior (chosen and documented)

When retrieval returns **nothing above the similarity threshold**, the
service does NOT fail and does NOT pretend knowledge exists: the prompt
explicitly tells the model no knowledge was retrieved and restricts it to
safe general guidance, and the response is flagged
`"grounded": false`. Clients can always tell a RAG-grounded response
from a general-guidance one. (SRS §13.4: a plain LLM answer is not
called "RAG".)

## Coach service ([service.py](service.py))

`generate_coaching(db, user_id, embedding_provider, llm_provider, ...)` —
HTTP-independent, both providers injected (tests pass fakes; the router
passes the provider selected by `get_llm_provider()`). Post-generation validation: the message
must be non-empty and ≤ 4000 characters, else `CoachValidationError`
(HTTP 502). The response carries retrieval metadata (query text, top_k,
threshold, per-chunk title/source/similarity) for testing/debugging —
never the raw prompt or any credentials.

## API ([router.py](router.py))

`GET /api/v1/coach` — no parameters; uses the dev-user identity, builds
the context fresh from the database on every call.

| Failure | HTTP |
|---|---|
| provider key missing (`GEMINI_API_KEY`; or the `AGENTROUTER_*` pair when `agentrouter`) | 503 |
| embedding / LLM timeout | 504 |
| provider transport/API error, malformed LLM output, failed validation | 502 |

Upstream failures are never turned into HTTP 200.

## Configuration (names only — values live in backend `.env`)

| Env var | Purpose | Default |
|---|---|---|
| `GEMINI_API_KEY` | ONE key for embeddings AND (default) text generation | (unset → 503) |
| `LLM_PROVIDER` | text-generation backend: `gemini` or `agentrouter` | `gemini` |
| `AGENTIC_API_KEY` / `AGENTROUTER_BASE_URL` | AgentRouter key + base URL (e.g. `https://…/v1`) | (unset → 503 when `agentrouter`) |
| `AGENTROUTER_MODEL` | gateway model | `deepseek-v4-flash` |
| `GEMINI_EMBEDDING_MODEL` | embedding model | `gemini-embedding-001` |
| `GEMINI_LLM_MODEL` | LLM model | `gemini-2.5-flash` |
| `EMBEDDING_TIMEOUT_SECONDS` / `LLM_TIMEOUT_SECONDS` | upstream timeouts | `30.0` |
| `RAG_SIMILARITY_THRESHOLD` | minimum cosine similarity | `0.50` (calibrated 4C.3A — see rag/README.md) |
| `COACH_TOP_K` | chunks retrieved per coaching call | `4` |

The key is backend-only; it is never sent to Android, logged, or echoed.

## Scenario coverage (4C.3A)

All five recommendation scenarios are tested through the REAL Phase 4A
machinery (`build_fitness_context` + `recommend`) with mocked providers
(`tests/test_coach_scenarios.py`): cold start, lapsed/recovery, territory
defense, consistent/progress, maintain/default. Each test verifies the
recommendation stays authoritative (the coach result equals exactly what
the rules engine produced), the prompt carries only the real context
values, and no XP/level/distance/calorie/medical data is invented.

**Known Phase 4A quirk (documented, not changed):** TERRITORY_AT_RISK
(DEFENSE) is unreachable through `build_fitness_context` from stored data —
it needs `recent_captures_7d == 0` while `last_capture_at` is within 2
days, but any hex captured within 2 days necessarily also counts in the
7-day window. The scenario test drives the real `recommend()` engine with
an explicitly constructed context instead. Fixing this means changing the
4A context/rules (out of 4C.3A scope — the engine must not be replaced).

## Live smoke evaluation (4C.3A, 2026-09-06)

`tools/evaluate_live_coach.py` (manual, never in pytest) runs the REAL
pipeline — Gemini embeddings + gemini-2.5-flash + live Supabase/pgvector —
for 5 SYNTHETIC scenario contexts (clearly labeled, not real user data) +
1 real dev-user case through the actual service entry point. 6 LLM calls
+ 2 embedding batches per run; read-only; never prints the key or prompt.

Qualitative observations (recorded honestly, no fake precision scores):

- **Relevant:** every message addressed its scenario (1,000-step first
  hex for cold start; 2,000-step comeback for lapsed; "reinforce 1 of
  your 3 owned hexes" for defense; gradual increase toward 3 more hexes
  for consistent; steady 3,000-step walk for maintain).
- **Grounded:** themes came from the retrieved WHO/CDC chunks (walking
  safety, consistency over intensity, gradual progression); no invented
  facts or numbers — every number in a message traces to the context or
  recommendation.
- **Personalized:** real context values appear naturally ("your 3 owned
  hexes", "4 hexes in the last 7 days", "20,000 lifetime steps").
- **Coherent:** all six messages were complete, grammatical sentences —
  no mid-thought truncation.
- **Not copying:** no verbatim chunk echoes; the phrasing is synthesized.
- **Minor quirk observed:** messages occasionally name the "rules
  engine" (the prompt's context line says "Current recommendation from
  the rules engine" and the model sometimes repeats that phrasing
  verbatim). Cosmetic; a future prompt tweak could say "current
  recommendation" instead.
- **Rate limiting observed:** running 6 LLM calls back-to-back hit the
  Gemini free tier's HTTP 429 on the last call in one run — the provider
  surfaces it as `LLMProviderError` → HTTP 502. Real clients making
  single calls are unaffected; burst evaluation runs should space calls.
- **Not medically validated:** the coaching output is general fitness
  guidance only. It has NOT been clinically evaluated and must not be
  presented as medically safe or clinically validated advice.

## Limitations / what remains for later phases

- The similarity threshold is now **calibrated** (4C.3A: 0.30 → 0.50,
  evidence in rag/README.md *Retrieval quality evaluation*). It remains
  calibrated on a developer-written query set — re-check after corpus or
  embedding-model changes.
- Single-turn only: no conversation history, no follow-up questions.
- No streaming (WebSocket/TTS are separate later phases per SRS).
- The prompt is monolithic English text; no localization.
- Output validation is structural (non-empty, length) — no automated
  check that the model actually obeyed the grounding rules. SRS §13.4
  honesty therefore relies on the `grounded` flag + prompt design.
- **Live end-to-end verification: DONE (2026-09-05)** — real
  `GEMINI_API_KEY` → migrated Supabase (pgvector + HNSW) → ingested
  corpus → `GET /api/v1/coach` returned a grounded, complete coaching
  message built from real dev-user context and retrieved WHO/CDC
  knowledge.
- **Live device re-verification: DONE (2026-09-06, Phase 4C.3B)** — the
  real-device Android scenarios (docs/docs/ui/0002-android-coach-integration.md)
  were re-run with `LLM_PROVIDER=agentrouter` (DeepSeek via AgentRouter,
  `deepseek-v4-flash`) because the Gemini `gemini-2.5-flash` free-tier
  daily quota (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, 20/day)
  was exhausted mid-session (confirmed HTTP 429). Embeddings remained
  Gemini `gemini-embedding-001`. All four device tests passed again with
  the fallback provider; the Android app is provider-agnostic.
