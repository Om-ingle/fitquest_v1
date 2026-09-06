# RAG Knowledge Base (Phases 4C.1 + 4C.2 + 4C.3A)

> **What exists here:** the database schema (pgvector), deterministic
> chunking, a REAL embedding provider (Gemini), a small curated fitness
> corpus with a repeatable ingestion command, and cosine-similarity
> retrieval with a minimum-similarity threshold.
> **What does NOT exist here:** the LLM or coaching output — that lives in
> [`app/modules/coach/`](../coach/README.md) (Phase 4C.2). No coaching
> text is generated or faked anywhere in this module.

## Architecture

```text
curated knowledge documents (corpus.py; ingestion via CLI only)
        │
        │  python -m app.modules.rag.ingestion
        │  → service.ingest_document(db, ..., provider)
        ▼
   chunking.chunk_text          deterministic, paragraph-first,
        │                       configurable size/overlap
        ▼
   GeminiEmbeddingProvider      REAL provider (4C.2); injectable via the
        │                       EmbeddingProvider protocol
        ▼
   ragdocument + ragchunk       PostgreSQL + pgvector (migration 0003)
        │
        │  service.retrieve_chunks(db, query_embedding, top_k,
        │                           min_similarity, filters)
        ▼
   ranked chunks                cosine similarity (pgvector <=> on PG;
        │                       pure-Python cosine on SQLite/tests)
        │
        └──► app/modules/coach/ (4C.2): query text → embedding →
             retrieval → grounded prompt → Gemini LLM → coaching
```

## Schema (Alembic migration `0003_rag_knowledge_base.py`)

**ragdocument** — `id` UUID PK, `title`, `source` (indexed), `source_url`
nullable, `content`, `metadata` (JSONB), `created_at`, `updated_at`.
Natural upsert key: `(source, title)`.

**ragchunk** — `id` UUID PK, `document_id` FK → ragdocument (indexed),
`chunk_index`, `content`, `metadata` (JSONB; chunks inherit the document's
metadata at ingest time), `embedding vector(1536)`, `created_at`.
Unique `(document_id, chunk_index)` so re-ingestion replaces chunks
wholesale and stays idempotent.

PostgreSQL-only migration steps (skipped on SQLite): `CREATE EXTENSION IF
NOT EXISTS vector` and an HNSW cosine index (`embedding
vector_cosine_ops`) — HNSW over IVFFlat because the corpus starts empty
and HNSW needs no training rows.

### Embedding dimension

`EMBEDDING_DIMENSION = 1536` lives in exactly one place —
[`constants.py`](constants.py) — and is frozen into migration 0003 (the
value when that migration was written; migrations must not read live
settings). **Phase 4C.2 verification:** the selected model
(`gemini-embedding-001`, default width 3072) supports
`outputDimensionality`, and the provider pins it to **1536** — matching
migration 0003 exactly, so **no migration change was needed** (0003 has
never been deployed to Supabase). The provider validates the width on
every call; if a future model change breaks the contract, the fix is a
NEW migration (alter column + re-embed the corpus), never a silent edit
of the constant.

### The embedding column without the pgvector Python package

`models.EmbeddingType` renders `vector(N)` on PostgreSQL and degrades to a
plain text column on SQLite (the test suite's database). Vectors cross the
driver boundary as pgvector text literals (`"[0.1,0.2,...]"`) in both
directions, so the same models work on both dialects with no new
dependency.

## Chunking ([chunking.py](chunking.py))

Pure, stdlib-only, deterministic. Split on blank lines; keep paragraphs
whole when they fit; word-split oversized paragraphs (words are never
cut); greedily pack into chunks of ≤ `chunk_size` new characters; each
chunk after the first starts with the trailing `overlap` characters of the
previous chunk (snapped to a word boundary). Defaults: 1200 chars / 150
overlap (`constants.py`), overridable per ingest call. Same input → same
chunks → same `chunk_index` values, which is what makes ingestion
idempotent.

## Embedding provider ([providers.py](providers.py))

`EmbeddingProvider` is a runtime-checkable Protocol (`dimension`,
`embed_texts(texts) -> vectors`). Services accept it as a parameter —
nothing in the retrieval path knows a vendor.

**Phase 4C.2 adds the real provider: `GeminiEmbeddingProvider`** —
Gemini `batchEmbedContents` over REST (httpx, no vendor SDK), behind the
same protocol. `get_embedding_provider()` returns it when
`GEMINI_API_KEY` is set, and still raises
`EmbeddingProviderNotConfigured` otherwise — there is no fake/random
provider anywhere in production code. The provider requests
`outputDimensionality = EMBEDDING_DIMENSION` and validates every
returned vector's width and finiteness at runtime, so a model change
that breaks the schema contract fails loudly instead of corrupting rows.

### Why Gemini (provider decision, 4C.2)

SRS §14 names Gemini/OpenRouter. Gemini is the choice because it is the
only candidate offering **both embeddings and the LLM behind one key**
(OpenRouter has no embeddings endpoint), it has a student-friendly free
tier, and it was the SRS's first-named direction. The Protocol
abstraction keeps the vendor swappable later.

## Retrieval ([service.py](service.py))

`retrieve_chunks(db, query_embedding, top_k, source, metadata_filters,
min_similarity)` — HTTP-independent. Validates the embedding width (must
equal `EMBEDDING_DIMENSION`) and finiteness. Orders by cosine similarity
descending with a deterministic `(document_id, chunk_index)` tie-break.
Filters: exact `source` match on the document; `metadata_filters` as
subset containment on chunk metadata (JSONB `@>` on PostgreSQL).

**Minimum-similarity threshold (4C.2, recalibrated 4C.3A):** chunks scoring
below `min_similarity` are dropped — before top_k truncation, so a filtered
result may contain fewer than `top_k` chunks (including zero). Unrelated
chunks are never silently returned. The coach flow uses the
`RAG_SIMILARITY_THRESHOLD` setting (default **0.50**, calibrated against
the live corpus on 2026-09-06 — see *Retrieval quality evaluation* below).

`retrieve_chunks_for_text(db, query_text, provider, ...)` — the full
text → embedding → search flow used by the coach service: it embeds the
query with the injected provider (width-validated) and delegates to
`retrieve_chunks`.

Two engines, picked by the session dialect:

- **PostgreSQL** — similarity computed in the database via pgvector `<=>`
  (cosine distance), served by the HNSW index. This path runs for the
  first time when migration 0003 is applied to Supabase (see Limitations).
- **SQLite** (tests) — the same ranking computed in pure Python over the
  stored vectors. A test/dev convenience; the vectors ranked are the real
  persisted ones, nothing is fabricated.

## Curated corpus + ingestion ([corpus.py](corpus.py), [ingestion.py](ingestion.py))

`corpus.py` holds a SMALL curated corpus (6 documents, ~1 page each) of
general fitness guidance — activity principles, walking, gradual
progression, recovery/rest, consistency, returning after a break — each
paraphrased conservatively and attributed to a public source (WHO / CDC,
with `source_url`). No diagnosis, treatment, medication advice, or
fabricated claims; the only numbers are the cited organizations' own
published activity recommendations. The corpus is distinct from the
clearly-marked TEST-FIXTURE text used by the automated tests.

Ingestion is repeatable, not manual:

```bash
cd apps/api
python -m app.modules.rag.ingestion             # ingest into DATABASE_URL
python -m app.modules.rag.ingestion --dry-run   # validate corpus + key only
```

It uses REAL Gemini embeddings, refuses to run without `GEMINI_API_KEY`,
is idempotent on (source, title), and is never executed by the test
suite (tests ingest fixture documents with fixture providers).

## API surface ([router.py](router.py))

- `POST /api/v1/rag/retrieve` — `{query_embedding, top_k, source?,
  metadata?, min_similarity?}` → ranked chunks. The caller supplies the
  query embedding; the coach endpoint (`/api/v1/coach`) is the flow that
  produces embeddings server-side from raw text.
- `GET /api/v1/rag/documents` — read-only listing with chunk counts.

**No ingestion endpoint exists, on purpose.** FitQuest auth is deferred
(SRS §4.2; every caller is currently the dev user), so administrative
ingestion is not exposed over HTTP. Ingestion is the CLI above.

## Retrieval quality evaluation (Phase 4C.3A)

[evaluation.py](evaluation.py) holds a fixed query set of **10
representative coaching queries** (cold start / beginner, walking
consistency, gradual progression, recovery/rest, weekly activity guidance,
inactive-lapsed return, motivation, general safe activity, soreness after
a return, everyday-activity counting), each labeled with the corpus
documents a reviewer expects retrieval to surface, plus simple metrics:
per-query **Recall@k** and **hit rate**. The manual tool
`tools/evaluate_retrieval.py` runs the set live (real Gemini embeddings —
ONE batched call — against the ingested Supabase corpus, read-only) and
also probes a few clearly off-topic queries with no threshold to expose
raw similarity scores.

### Results (live run, 2026-09-06, gemini-embedding-001 @ 1536 dims)

- **mean Recall@4 = 1.00, hit rate = 1.00 (10/10 queries)** at
  `top_k=4`: every expected document appeared in the top 4 for every
  query.
- On-topic chunk similarities ranged **0.60–0.77** (the expected document
  was the top-ranked chunk for every query).
- Off-topic probes (sourdough baking, quantum computing, used-car buying)
  scored raw **0.43–0.46** against the fitness corpus.

### Threshold decision: 0.30 → 0.50

The original 0.30 default was uncalibrated. The live probe showed a clean
empty band between unrelated text (≤ 0.46) and on-topic retrieval
(≥ 0.60); 0.30 sat below BOTH, i.e. it admitted clearly unrelated text as
"knowledge". **0.50** sits mid-band with ~0.10 margin on each side:
every on-topic chunk observed stays above it (verified by re-running the
evaluation under 0.50 — Recall@4 unchanged at 1.00), and every off-topic
probe falls below it. The failure mode of a too-high threshold is the
honest `grounded=false` fallback, not fabricated grounding — so erring
toward the middle of the band is the safe side. This is calibration on 13
developer-written queries, not optimization against one lucky response.

### Honesty / limitations

- **This is a small project-level sanity evaluation, not a scientific
  benchmark.** The queries and expected-document labels were written by
  the project's developers against the project's own 6-document corpus.
  Recall@4 = 1.00 means "retrieval surfaces the documents we expect for
  the queries we expect users to ask" — it is NOT real-user evidence and
  NOT population-level performance.
- Absolute similarity scores can drift if the embedding model is
  retrained upstream; the recorded numbers are a snapshot. The threshold
  has ~0.10 margin on both sides, so small drift is tolerated.
- With only 6 documents / 1 chunk each, top-4 retrieval saturates the
  corpus — the metric will get harder (and more meaningful) as the corpus
  grows. Re-run `tools/evaluate_retrieval.py` after any corpus change.

## What is intentionally deferred (beyond 4C.3A)

- Per-chunk metadata (section titles, per-chunk topics).
- Corpus growth/curation tooling beyond the fixed curated set.
- Retrieval evaluation over real user queries (requires real traffic).

## Limitations

- **Live embedding verification: DONE (2026-09-05).** With the owner's
  `GEMINI_API_KEY`, a real `gemini-embedding-001` round-trip returned
  exactly 1536 finite dimensions, the curated corpus (6 documents) was
  ingested into live Supabase with real embeddings, and pgvector
  retrieval returned semantically relevant chunks (cosine 0.60–0.65 for
  on-topic queries). No key value was ever printed or stored by the agent.
- **pgvector on Supabase: installed and verified (2026-09-05).**
  `alembic upgrade head` took the live instance (PostgreSQL 17.6) from
  revision 0001 → 0003; the `vector` extension (0.8.2), both RAG tables,
  and the HNSW cosine index were confirmed present afterwards.
- The PostgreSQL retrieval path (pgvector `<=>` SQL) is now exercised
  live by the coach flow; the automated suite still covers the portable
  path on SQLite.
- Chunk-level metadata currently only carries inherited document metadata;
  per-chunk metadata (e.g. section titles) is future work.
