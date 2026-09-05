# FitQuest API Backend Documentation

This document outlines the architecture, data models, and API structure for the FitQuest backend. The backend is built with **FastAPI**, **SQLModel**, and **Supabase-hosted PostgreSQL**.

> Status note: this README describes the **actual** current implementation. Authentication is intentionally deferred (a fixed dev user is returned by `get_current_user`); Supabase Auth/JWT validation is a later phase.

## 🚀 Tech Stack
* **Framework:** FastAPI
* **ORM:** SQLModel (Pydantic + SQLAlchemy), sync `Session` engine
* **Database:** PostgreSQL, hosted on Supabase, connected via `DATABASE_URL`
* **Driver:** psycopg2
* **Authentication:** deferred — dev-user stub
* **Migrations:** Alembic

## ⚙️ Setup

1. Create a virtual environment and install dependencies:
   ```bash
   cd apps/api
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   pip install -r requirements.txt -r requirements-dev.txt
   ```

2. Configure the database connection. The app reads `DATABASE_URL` from the
   environment or from a `.env` file — it checks `apps/api/.env` first, then
   the repository root `.env`. Copy `.env-example` to `.env` and set:
   ```
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres
   ```
   Optional (backend-only, unused in Phase 1): `SUPABASE_URL`, `SUPABASE_SECRET_KEY`.

   > **IPv4 note:** the direct host `db.YOUR_PROJECT_REF.supabase.co` resolves
   > to an **IPv6-only** address. If your network has no IPv6 route (common on
   > home/office IPv4 networks) connections fail with
   > *"could not translate host name"*. Use the Supavisor **pooler** instead
   > (IPv4-compatible, session mode):
   > ```
   > DATABASE_URL=postgresql://postgres.YOUR_PROJECT_REF:YOUR_PASSWORD@aws-0-YOUR_REGION.pooler.supabase.com:5432/postgres
   > ```
   > The region and exact host are shown in Supabase Dashboard → Project
   > Settings → Database → Connection string → "Connection pooling". This
   > project lives in `ap-south-1` (Mumbai).

   > Never commit a `.env` containing real credentials.

3. Apply the database schema with Alembic (the canonical schema source — do
   **not** create tables by hand in the Supabase dashboard):
   ```bash
   alembic upgrade head
   ```

4. Run the API:
   ```bash
   uvicorn app.main:app --reload
   ```
   Health check: `GET http://127.0.0.1:8000/health`

5. Run the tests:
   ```bash
   pytest
   ```
   (The tests use a throwaway local SQLite file and do not need Supabase
   credentials. PostgreSQL connectivity is verified by running the app and
   migrations against the real `DATABASE_URL`.)

## 🧩 Architecture: Domain-Driven Design
The project uses a **Feature-Based (Module-Wise)** structure. Each domain encapsulates its own logic, schemas, models, and endpoints.

```text
apps/api/
├── app/
│   ├── main.py             # Main FastAPI app and router mounting
│   ├── core/               # Global settings, config, security, db connection
│   ├── api/                # Global API routing & dependencies
│   └── modules/            # Domain Modules (The core logic)
│       ├── users/
│       ├── map/
│       ├── runs/
│       └── quests/
├── alembic/                # Migrations (versions/0001_initial_schema.py …)
└── tests/
```

### Modules Breakdown

### 1. Users Module (`app/modules/users`)
Handles core identity, profile stats, streaks, and friendships.
* **Models:** `User`, `Friendship`
* **Stats:** Tracks lifetime steps and hexes captured.
* **Auth note:** `get_current_user` currently returns a fixed dev user (`DEV_USER_ID` in `app/api/dependencies.py`) because authentication is deferred. Endpoints that mutate on behalf of "the current user" (run sync, map viewport) use this dev user.

### 2. Map Module (`app/modules/map`)
The multiplayer turf-war engine.
* **Models:** `HexOwnership` (H3 string as the Primary Key).
* **Endpoints:** zoom-aware viewport queries.
    * High zoom (>= 14): returns exact `HexDetailResponse` rows.
    * Low zoom (< 14): returns an aggregated (empty for now) response until H3-pg aggregation is implemented.
* **Known Phase 1 limitation:** the viewport query does not yet filter by the bounding box — it returns up to 500 hexes regardless of bbox. Fixing this properly (H3-pg / bbox filtering) is planned for Phase 2.

### 3. Runs (Capture Sync) Module (`app/modules/runs`)
Handles ingestion of completed runs from the mobile frontend.
* **DTOs:** `RunSyncPayload` mirrors the Android `Map<String, Int>` (`hex_id` → steps).
* **Logic:** iterates the payload, upserts `HexOwnership` rows, calculates defense scores, and returns a gamified `RunSyncSummary` (stolen/defended/new hexes, XP).

### 4. Quests Module (`app/modules/quests`)
Dynamic challenges.
* **Models:** `Quest` (system-wide definitions) and `UserQuest` (per-user progress).

### 5. RAG Module (`app/modules/rag`) — Phases 4C.1 + 4C.2
The retrieval side of LLM-grounded coaching (SRS §13). Read
[`app/modules/rag/README.md`](app/modules/rag/README.md) before touching it.
* **Models:** `RagDocument`, `RagChunk` (pgvector `vector(1536)` embedding
  column; migration `0003`), unique `(document_id, chunk_index)`.
* **Services:** deterministic chunking (`chunking.py`), a REAL Gemini
  embedding provider (`providers.py`, REST via httpx — enabled by
  `GEMINI_API_KEY`, width-validated, no fake fallback), idempotent document
  ingestion, and cosine-similarity retrieval with a minimum-similarity
  threshold, source/metadata filters, and `top_k`.
* **Corpus + ingestion:** small curated fitness corpus (WHO/CDC-sourced
  general guidance) in `corpus.py`; repeatable CLI
  `python -m app.modules.rag.ingestion` (real embeddings, never run by
  tests).
* **Endpoints:** `POST /rag/retrieve` (caller supplies the query embedding)
  and `GET /rag/documents` (read-only listing). **No ingestion endpoint** —
  auth is deferred, so ingestion stays CLI/service-level.

### 6. Coach Module (`app/modules/coach`) — Phase 4C.2
Grounded AI coaching (SRS §13/§14). Read
[`app/modules/coach/README.md`](app/modules/coach/README.md) first.
* **Providers:** `GeminiLLMProvider` (REST, configurable model, typed
  timeout/error handling) behind the `LLMProvider` protocol — ONE key
  (`GEMINI_API_KEY`) serves both embeddings and the LLM.
* **Flow:** real Phase 4A `FitnessContext` → unchanged rules engine →
  topical query → embedding → thresholded pgvector retrieval → grounded
  prompt (context / knowledge / instructions, synthesize-don't-echo) →
  LLM → validated `CoachResponse`. The recommendation engine remains the
  authority; the LLM is the explanation layer.
* **Endpoint:** `GET /api/v1/coach` (dev user) with honest error mapping
  (503 unconfigured, 504 timeout, 502 upstream/malformed). Ungrounded
  responses (retrieval empty) are flagged `"grounded": false` — never
  presented as RAG-grounded (SRS §13.4).
* **Honesty note:** requires `GEMINI_API_KEY` to produce real output; the
  automated tests mock every provider boundary (zero API credits).

## 🗄 Migrations

The schema lives in `alembic/versions/` and is reproducible from code:

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"   # create a new migration after model changes
alembic current               # show applied revision
```

The migration URL comes from `DATABASE_URL` (env/`.env`) — `alembic.ini` contains no credentials.

`create_db_and_tables()` in `app/core/database.py` still exists for the dev
seed script (`seed.py`), but Alembic is the canonical schema source.

## 🛠 Typical Developer Workflow
1. **Adding a Feature:** Create a new folder under `app/modules/`.
2. **Define the Database Table:** `models.py`.
3. **Define the Input/Output JSON:** `schemas.py`.
4. **Write Business Logic:** `service.py` functions (No HTTP logic here).
5. **Expose Endpoints:** Tie the schemas and services together in `router.py`.
6. **Mount:** Add the router to `app/api/router.py`.
7. **Migrate:** `alembic revision --autogenerate -m "..." && alembic upgrade head`.
