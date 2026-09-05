# AI Coach (Phase 4C.2 — grounded LLM coaching)

> **What exists here:** a real LLM provider (Gemini), a grounded prompt
> builder, and a coach service that composes the Phase 4A recommendation
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
GeminiLLMProvider.generate (coach/llm.py)
        │
        ▼
validation (non-empty, ≤ 4000 chars) → CoachResponse
```

## LLM provider ([llm.py](llm.py))

`LLMProvider` is a runtime-checkable protocol (`generate(prompt) -> str`).
The single real implementation is `GeminiLLMProvider` — Gemini
`generateContent` over REST (httpx, no vendor SDK), model configurable
via `LLM`-side settings (default `gemini-2.5-flash`), temperature 0.4,
1024-token cap with thinking disabled (`thinkingBudget: 0` — gemini-2.5
models think by default and thinking tokens count toward the output cap,
which truncated live messages until this was set). Typed failures:
`LLMProviderNotConfigured` (no key → HTTP 503), `LLMProviderTimeout`
(504), `LLMProviderError` / `MalformedLLMResponse` (502). The API key
travels in the `x-goog-api-key` header and never appears in errors or
responses.

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
passes the Gemini factories). Post-generation validation: the message
must be non-empty and ≤ 4000 characters, else `CoachValidationError`
(HTTP 502). The response carries retrieval metadata (query text, top_k,
threshold, per-chunk title/source/similarity) for testing/debugging —
never the raw prompt or any credentials.

## API ([router.py](router.py))

`GET /api/v1/coach` — no parameters; uses the dev-user identity, builds
the context fresh from the database on every call.

| Failure | HTTP |
|---|---|
| provider key missing (`GEMINI_API_KEY`) | 503 |
| embedding / LLM timeout | 504 |
| provider transport/API error, malformed LLM output, failed validation | 502 |

Upstream failures are never turned into HTTP 200.

## Configuration (names only — values live in backend `.env`)

| Env var | Purpose | Default |
|---|---|---|
| `GEMINI_API_KEY` | ONE key for both embeddings and the LLM | (unset → 503) |
| `GEMINI_EMBEDDING_MODEL` | embedding model | `gemini-embedding-001` |
| `GEMINI_LLM_MODEL` | LLM model | `gemini-2.5-flash` |
| `EMBEDDING_TIMEOUT_SECONDS` / `LLM_TIMEOUT_SECONDS` | upstream timeouts | `30.0` |
| `RAG_SIMILARITY_THRESHOLD` | minimum cosine similarity | `0.30` |
| `COACH_TOP_K` | chunks retrieved per coaching call | `4` |

The key is backend-only; it is never sent to Android, logged, or echoed.

## Limitations / what remains for Phase 4C.3

- The similarity threshold (`0.30`) is a conservative default. Live
  observation (2026-09-05): on-topic queries scored 0.60–0.65 against the
  curated corpus, comfortably above it — but a formal calibration
  (recall@k over a labeled query set) is still future work.
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
