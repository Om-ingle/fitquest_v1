# FitQuest — Phase 2 Living SRS / Development Context

---

## 1. Document Control

| Field | Value |
|---|---|
| **Document title** | FitQuest — Phase 2 Living SRS / Development Context |
| **Project name** | FitQuest |
| **File** | `FitQuest_PHASE2_SRS.md` (repository root) |
| **Purpose** | Long-term living development context. Enables a developer or AI agent to resume after 6–12 months without re-deriving settled decisions or rewriting working systems. |
| **Last updated** | 2026-09-12 |
| **Current project phase** | Phase 2 — post-presentation development |
| **Current milestone** | **M10 — Telemetry & Run Integrity** (not started) |
| **Document status** | Active, living. Update at the end of every milestone. |
| **Repository state at authoring** | branch `main`, HEAD `53e35f7` ("gradel"), working tree clean |

### Source-of-truth hierarchy

When any two sources disagree, the higher entry wins:

1. **Current repository / code behaviour** — the final authority. A feature exists if the code implements it, regardless of what any document claims.
2. **`FitQuest_PHASE2_SRS.md`** (this document) — current phase context, decisions, and status.
3. **`FitQuest_AS_BUILT_SRS.md`** — as-built snapshot at M9.4. Authoritative for M1–M9 history; already stale in places (see §5 note).
4. **`FitQuest_SRS.md`** — the original planned SRS (1802 lines). Authoritative for *intent and scope boundaries*, not for implementation status.
5. **Historical audits / reports / early design papers** — background only.

**Conflict procedure:** do not silently reconcile. Investigate the repository, then record the resolution here (and in §13 Decision Log if it changes architecture). §18 lists contradictions found during authoring that remain unresolved.

### Writing rules for this document

- As-built + forward-development, not marketing.
- Never claim a capability the repository does not support.
- Always label status explicitly: **IMPLEMENTED** / **PARTIALLY IMPLEMENTED** / **PLANNED** / **DEFERRED**.
- Never include API keys, tokens, passwords, JWT secrets, or connection strings. Public base URLs that ship inside the APK are not secrets and may be cited.

---

## 2. Project Identity

FitQuest is a **territory-capture fitness game**. Physical movement is converted into ownership of real-world map cells; the game is the motivational wrapper around ordinary walking and running.

### Core concept

The user starts a run. GPS position is indexed into **Uber H3 resolution-10 hexagons** (~15 m edge). Steps taken while inside a hex accumulate as that hex's *steps*. On finishing a run the session is synced to the backend, which applies three turf-war rules and returns the outcome. Owned hexes persist, can be reinforced, and can be stolen by other players whose step count in that hex exceeds the current defence.

### Primary user experience

1. Onboarding (username, avatar, daily step goal) — **IMPLEMENTED**
2. Start a run from the map/capture screen — **IMPLEMENTED**
3. Live map with own territory, rival territory, and current hex — **PARTIALLY IMPLEMENTED** (§5 F-06: no legend, no hex inspection)
4. Live AI coaching pushed over WebSocket, spoken aloud via native TTS — **IMPLEMENTED**
5. Finish run → local save → background sync → XP and territory awarded — **IMPLEMENTED**
6. Home dashboard: steps, goal progress, XP, streak, quests, AI coach card — **PARTIALLY IMPLEMENTED** (§5 F-01: today's steps undercount)
7. Leaderboard of real users by territory — **IMPLEMENTED** (§5 F-05: single metric, no pagination)
8. Achievements / Trophies — **IMPLEMENTED** (device-local only, §5 F-13)

### Gamification concepts

| Concept | Status | Notes |
|---|---|---|
| Territory capture | IMPLEMENTED | +50 XP new hex, +10 reinforce own, +100 steal |
| XP and level | PARTIALLY IMPLEMENTED | Computed and stored locally; **no XP/level column exists on the backend `user` table** |
| Streaks | IMPLEMENTED | Device-local day, per `RunSession` history |
| Daily step goal | IMPLEMENTED | `user_profile.dailyStepGoal` |
| Quests | PARTIALLY IMPLEMENTED | Backend has 6 routes; Android uses a local Room engine only |
| Achievements / Trophies | PARTIALLY IMPLEMENTED | 8+ badges, device-local evaluation only |
| Leaderboard | IMPLEMENTED | Server-ranked, real users, `metric="hexes"` |

### Territory / H3 model

- Resolution **10**, grid ring **k=2** for nearby hexes.
- Stored as H3 cell ID strings. **Raw latitude/longitude never leaves the device.**
- Android computes cell IDs locally via `com.uber:h3-android:4.4.0`; the backend recomputes/validates with `h3==4.5.0`.
- Ownership lives in a single `hexownership` row per cell with a `king_id` owner column — a deliberately simple shape (relevant to the Deferred Web3 discussion, §15).

### Fitness tracking

- Steps: Android `TYPE_STEP_COUNTER` hardware sensor, consumed as deltas **only while a run is active**.
- Location: FusedLocationProvider, `PRIORITY_HIGH_ACCURACY`, 2 s interval, via a location-typed foreground service.
- Metrics: distance and calories derived from step count by `RunMetrics`.
- **Ambient steps** (walking outside a run) are **not** currently captured into telemetry — see F-01.

### Backend / cloud architecture

Android → HTTPS/WSS → Railway (FastAPI) → Supabase PostgreSQL (+ pgvector) → AI providers. See §3.

### AI coaching stack — all IMPLEMENTED

| Layer | Component | Status |
|---|---|---|
| Deterministic recommendations | `modules/recommendations/service.py`, rules R1–R5 | IMPLEMENTED |
| Retrieval | RAG over a 7-document WHO/CDC corpus in pgvector | IMPLEMENTED |
| Embeddings | Gemini `gemini-embedding-001`, 1536 dims, HNSW cosine | IMPLEMENTED |
| LLM | Provider abstraction: Gemini `gemini-2.5-flash` or AgentRouter `deepseek-v4-flash` | IMPLEMENTED |
| Grounding | Similarity threshold 0.50, top-k 4, honest `grounded=false` fallback | IMPLEMENTED |
| Caching | `CoachCache` LRU 200 users, fingerprint `fix-e-v1` | IMPLEMENTED |
| Pull path | `GET /api/v1/coach` → Android Coach card, manual Retry only | IMPLEMENTED |
| Push path | Trigger engine → `PushCoach` → WebSocket → Android | IMPLEMENTED |
| TTS | Native Android `TextToSpeech`, `QUEUE_FLUSH` | IMPLEMENTED |
| Personalization / ML | None — rules only | PLANNED (F-16) |

### Multi-user direction

**PLANNED.** The system is architecturally multi-user (every table and route is keyed by user id) but operationally single-user: authentication is a fixed dev stub (§9). Making identity real is F-04 / milestone M11, and it gates friends, meaningful rankings, and server-authoritative progression.

### Explicit non-scope

Web3/blockchain/NFT/IPFS, Kafka, production ML infrastructure — **DEFERRED** by SRS §4.1/§4.3/§4.4. See §15.

---

## 3. Current Production / Deployment Baseline

```
Android app (railway flavor APK)
   │  HTTPS  (REST, Retrofit/OkHttp)
   │  WSS    (/api/v1/triggers/coaching)
   ▼
Railway  →  FastAPI (uvicorn, apps/api)   ← render.yaml blueprint also present
   │  psycopg2 / SQLModel (sync engine)
   ▼
Supabase PostgreSQL  (+ pgvector, 1536-dim, HNSW cosine)
   ▲
   │  HTTPS (server-to-server, backend-only keys)
   └─ Google Gemini (embeddings, always)  ·  Gemini or AgentRouter (LLM, switchable)
```

### Railway production role

The deployed production backend. Verified as live by the project owner as part of the current baseline. Its URL is baked into the `railway` product flavor as `BACKEND_BASE_URL`.

### Android build flavors — verified in `apps/app/fitquest/build.gradle.kts`

One flavor dimension, `backend`, with two flavors. Variant names are `<flavor><buildType>`, e.g. `railwayDebug`, `localRelease`.

| Flavor | `BACKEND_BASE_URL` | Overridable? | Purpose |
|---|---|---|---|
| `railway` | `https://fitquest-api-production.up.railway.app/` | **No — hard-coded deliberately** | Production APK |
| `local` | `envOrDefault("BACKEND_BASE_URL", "http://10.0.2.2:8000/")` | Yes, via `apps/app/.env` or an environment variable | Laptop-LAN fallback for demo/dev |

The design intent is recorded in the Gradle comment: the production flavor deliberately omits the `envOrDefault` chain *so a local `.env` carrying a LAN IP can never leak into the production APK*. `local` defaults to the emulator host alias and accepts a laptop LAN IP for a physical device.

> **Important:** the plain-HTTP `local` flavor is a development/demo posture only. SRS §16 accepted it for the demo; it is not production transport.

### Backend URL strategy

- The base URL is injected at build time as a `BuildConfig` field, one per flavor.
- `di/AppModule.kt` reads `BuildConfig.BACKEND_BASE_URL` and builds both the Retrofit `FitQuestApi` and the coaching WebSocket URL from that single value.
- No secrets are involved in this mechanism. Backend-held secrets (database URL, Gemini key, AgentRouter key) never reach Android — stated explicitly in the code comments in `FitQuestApiClient.kt` and `AppModule.kt`, and enforced by their absence from Gradle.

### WebSocket endpoint pattern

Derived, not hard-coded: `coachingWsUrl(baseUrl)` in `core/network/OkHttpCoachingSocketFactory.kt` converts the HTTP base URL to a WS URL (http→ws, https→wss, host normalised through OkHttp's `toHttpUrl()`). Backend route: `@router.websocket("/coaching")` under the triggers module, i.e. `/api/v1/triggers/coaching`.

### Supabase role

- **Central backend source of truth.** All shared/competitive state lives here.
- Accessed by the backend via `DATABASE_URL` over the **Supavisor transaction pooler** — the direct `db.<ref>.supabase.co` host is not reachable from the development machine (recorded project memory: IPv6 limitation).
- Schema managed by Alembic from `apps/api` (`alembic upgrade head`), 3 migrations.
- `SUPABASE_URL` / `SUPABASE_SECRET_KEY` are declared in config but **optional and unused by the running app today**; `supabase_jwt_secret` defaults to `"change-me"` and is only read by the currently-unused `decode_supabase_jwt`.
- Supabase Auth is **not** in use (§9).

### AI provider architecture — verified in `apps/api/app/core/config.py`

| Setting | Value | Notes |
|---|---|---|
| `gemini_embedding_model` | `gemini-embedding-001` | 1536 dims. **Always Gemini, in both LLM modes** — the pgvector schema is frozen to 1536. |
| `gemini_llm_model` | `gemini-2.5-flash` | Default LLM |
| `llm_provider` | `gemini` (default) \| `agentrouter` | Backend-only switch |
| `agentrouter_model` | `deepseek-v4-flash` | OpenAI-compatible `/chat/completions` gateway |
| `rag_similarity_threshold` | `0.50` | Calibrated 2026-09-06 from a live probe: on-topic chunks 0.60–0.77, unrelated 0.43–0.46 |
| `coach_top_k` | `4` | |
| `push_coach_cooldown_seconds` | `30.0` | One generation per user per window |
| `push_coach_max_workers` | `2` | Bounds concurrent LLM calls |
| `llm_timeout_seconds` / `embedding_timeout_seconds` | `30.0` | |

`AgentRouterLLMProvider` requires an app-level client filter header (`User-Agent: claude-cli/1.0.0 (external, cli)`) or the gateway rejects the request — verified live and worth preserving if the provider is re-enabled.

### Local development backend

- `uvicorn app.main:app --host 0.0.0.0 --port 8000` from `apps/api`, run from the project virtualenv `apps/api/.venv`.
- Android `local` flavor targets `http://10.0.2.2:8000/` (emulator) or `http://<LAPTOP_LAN_IP>:8000/` (physical device) via `apps/app/.env`.
- Same Supabase database as production unless `DATABASE_URL` is pointed elsewhere.

### Production vs local differences — summary

| Aspect | Production (`railway` flavor) | Local (`local` flavor) |
|---|---|---|
| Backend | Railway-managed uvicorn | Laptop uvicorn on :8000 |
| Transport | HTTPS / WSS | Plain HTTP / WS on LAN |
| URL mutability | Fixed at build time | Overridable by `.env` |
| Database | Supabase (same project) | Supabase (same project) |
| AI providers | Same config, set as Railway env vars | `.env` |

### Configuration & secret handling

- **Backend:** `pydantic-settings` reads `.env` from `apps/api/` then the repo root; `extra="ignore"` so the shared master `.env` may also hold Android-side variables. `DATABASE_URL` is required — there is deliberately no silent fallback.
- **Deployment:** `render.yaml` (repo root) declares every secret as `sync: false` with the comment that secrets are set in the provider dashboard and never in the file. No database resource is provisioned by the blueprint — the backend connects to Supabase.
- **Android:** `.env` is read only at build time by Gradle to populate `BuildConfig`. No backend secret is ever placed in `BuildConfig`.
- Secrets are **never** committed. Do not add them to this document.

---

## 4. Completed Baseline — M1–M9

Milestone names below are drawn from `docs/agent_ledger.md` and `FitQuest_AS_BUILT_SRS.md`. Where the ledger records a phase label rather than an `M` number, the label is used verbatim.

| Milestone | Purpose | Status | Verification |
|---|---|---|---|
| **Phase 1** (2026-09-05) | Supabase PostgreSQL foundation | COMPLETE | Live DB, Alembic migrations applied |
| **Phase 2** (2026-09-05) | Android ↔ FastAPI run-sync integration | COMPLETE | Real-device run synced |
| **Phase 4C** (2026-09-05) | RAG knowledge base + grounded LLM coach (backend only) | COMPLETE | Live end-to-end |
| **Phase 4C.2** | Live verification once the Gemini key was supplied | COMPLETE | Live API calls |
| **Phase 4C.3A** (2026-09-06) | Coach quality, retrieval evaluation, backend hardening | COMPLETE | Retrieval calibration probe |
| **Phase 4C.3B** (2026-09-06) | Android AI coach integration | COMPLETE | Real Samsung device; `docs/docs/ui/evidence-4c3b/` |
| **M8.1** | Trigger engine | COMPLETE | Backend tests |
| **M8.2** | WebSocket transport | COMPLETE | `test_ws.py` |
| **M8.3** | Trigger → AI push (8.3A backend, 8.3B Android client) | COMPLETE | `test_push.py`, `test_triggers.py` |
| **M8.4** | Native Android TTS | COMPLETE | Device utterance evidence |
| **M8.5** | Coach freshness audit / fix (`CoachCache` fingerprint `fix-e-v1`) | COMPLETE | `test_coach_cache.py` |
| **M9.1–M9.2** | Pre-demo reliability fixes | COMPLETE | Android reliability changes committed by the owner in `85f2232` |
| **M9.3** (2026-09-07) | Final pre-demo reliability & AI preflight | COMPLETE | 391 backend tests collected |
| **M9.4** (2026-09-07) | Final presentation polish & demo readiness | COMPLETE | `docs/DEMO_DAY_CHECKLIST.md` |

### Completed M8/M9 systems — as built

**Trigger engine (`apps/api/app/modules/triggers/`)** — IMPLEMENTED.
In-process, no broker. Three trigger types: `WORKOUT_COMPLETED`, `TERRITORY_CAPTURED`, `ACTIVITY_MILESTONE` (milestones at 5 000 / 10 000 / 15 000 / 20 000 steps). Dedupe via an LRU of 100 000 entries. Deliberately requires neither Redis nor Kafka; the substitution point is documented in the module.

**WebSocket transport (`modules/triggers/ws.py`)** — IMPLEMENTED.
Per-session `asyncio.Queue` with `SESSION_QUEUE_SIZE = 256`, drop-on-full policy. **No server-side ping/keepalive and no backlog/replay.**

**Trigger → AI push (`modules/coach/push.py`)** — IMPLEMENTED.
`PushCoach` coalesces bursts, enforces a 30 s per-user cooldown, and runs 2 workers. **Skips generation entirely when the user has no live WebSocket session** — so a push produced while the app is backgrounded is lost, not queued. Tests disable the stage via `push_coach_enabled=False`.

**Android WebSocket client (`core/network/CoachingWsClient.kt`)** — IMPLEMENTED.
Capped exponential backoff: initial 1 000 ms, ×2 multiplier, 30 000 ms cap, **5 attempts maximum**, no jitter. On exhaustion it stops and reports `DISCONNECTED`; nothing reconnects it except a foreground `connect()`.

**Native TTS (`core/coaching/` → `AndroidTtsSynthesizer`)** — IMPLEMENTED.
Android `TextToSpeech`, `QUEUE_FLUSH`. Fed by a `drop(1)`-filtered flow through `CoachingSpeechGate` so a newer coaching line pre-empts a stale one.

**Coach freshness audit/fix** — IMPLEMENTED.
`CoachCache` is an LRU of 200 users keyed by a context fingerprint (`fix-e-v1`), so identical contexts reuse a generation instead of paying for a new LLM call.

**Presentation reliability fixes / AI preflight (M9.3)** — IMPLEMENTED.
Includes an AI preflight check and the associated reliability work recorded in the ledger.

**Production deployment** — IMPLEMENTED *beyond* what the as-built SRS records.
`render.yaml` (repo root) is a real Render blueprint, and the Railway production backend is live. The as-built SRS §20 still describes deployment as deferred; the repository and the verified baseline supersede it.

**Railway production APK** — IMPLEMENTED.
Built from the `railway` flavor with the production URL fixed at build time.

**Cable-less real-device operation** — VERIFIED.
The physical Samsung demo device operated against the deployed backend with no USB tether — the verified baseline for the whole cloud architecture.

---

## 5. Current Known Issues / Technical Debt

Every row below was re-verified against the repository on 2026-09-12, not copied from the audit. Priorities: **P0** foundational, **P1** important product functionality, **P2** quality/UX/infrastructure, **P3** research/advanced.

| ID | Area | Current Problem | Impact | Planned Resolution | Priority | Milestone |
|---|---|---|---|---|---|---|
| **F-01** | Daily telemetry | `HomeTab.kt` reads `observeRecentSessions(limit = 3)` then filters to today, so a 4th run in a day is dropped. Separately, only run-tracked steps are counted; ambient steps from `TYPE_STEP_COUNTER` are never included. | Home undercounts and disagrees with the snapshot sent to the backend. Downstream ML trains on this table. | Query the day window (`getSessionsBetween`) instead of "3 most recent"; make the definition of "today's steps" explicit in the UI. Ambient steps only if requirements justify it. | **P0** | M10 |
| **F-02** | Pause/resume | `HexCaptureEngine.applyStepDelta()` guards on `isTracking` only, never `isPaused`. Steps, per-hex tallies, distance and calories keep accruing while paused. | Session reports paused-excluded duration alongside pause-included step volume → internally inconsistent telemetry. | Gate step collection and hex attribution on pause; freeze distance/calories; reflect paused state in UI and FGS notification. | **P0** | M10 |
| **F-03** | Live coaching | Client stops after 5 reconnect attempts until the next foreground. No jitter, no connectivity awareness. Server keeps no backlog and skips generation with no live session. | Live coaching dies silently mid-run; user is never told. | Jittered/connectivity-aware retry; reconnect after foreground reconcile; explicit offline state. Decide backlog explicitly. | **P0** | M12 |
| **F-04** | Identity | `get_current_user()` returns the constant `DEV_USER_ID`. `decode_supabase_jwt()` exists in `core/security.py` but **is imported by nothing**. | Blocks friends, meaningful leaderboard identity, server-authoritative progression, meaningful multi-user testing. | Activate the dormant JWT path; add an auth subject column; real login on Android + secure token storage + interceptor. | **P0** | M11 |
| **F-05** | Leaderboard | `select(User)` loads **all** users into memory, sorted in Python, no pagination. One metric (`hexes`). Client-side District Tier ladder matches nothing server-side. | Will not scale past small user counts; tier display is unverifiable against the server. | Ranked query + pagination; make metric explicit; server-driven or explicitly-cosmetic tiers; pull-to-refresh and offline fallback. | **P1** | M13 |
| **F-06** | Shared territory UX | No legend distinguishing own/rival; no hex inspection; no refresh. On fetch failure `sharedMapFetchFailed` is set but **stale geometry stays on screen**. | Rival territory is unlabelled; stale data is presented as current — the most misleading failure mode. | Legend, hex tap target (using the existing unused `GET /map/{hex_id}`), refresh affordance, honest stale state. | **P1** | M13 |
| **F-07** | Quests | Six backend quest routes exist; **Android calls none**. Quest progress is local-Room-only against a locally generated daily set. | Two devices on one account hold divergent quest state; server never knows. | Server-authoritative quest generation and progress computed from run-sync outcomes; local cache for offline. | **P1** | M14 |
| **F-08** | Profile sync | SRS §19's fourth required flow is absent. Profile lives only in the Room row `local_user`. `user.total_hexes_captured` is **never incremented**. | Profile, level, XP and streak are device-local and device-specific; `/users` routes unused. | Write-through + foreground pull with server-wins resolution; backend gains XP/level representation. | **P1** | M14 |
| **F-09** | Map aggregation | Below `MIN_DETAIL_ZOOM = 14.0` the endpoint returns `is_aggregated=True` with empty `hexes` **and empty `heatmaps`**; the code comments that the aggregation algorithm is not implemented. | Zoomed out, the map shows nothing — the natural "see my empire" view is blank. | Implement H3 parent-cell roll-up; populate `heatmaps`; move viewport filtering into SQL. | **P1** | M13 |
| **F-10** | Battery / privacy | `HexCaptureEngine.init` calls `startLocationMonitoring()`; `stopTracking()` cancels only `stepsJob`, so **`locationJob` runs for the whole process lifetime**. | Continuous high-accuracy GPS with no run active — a real battery drain and a privacy concern. | Cancel `locationJob` on stop; adaptive sampling; consider coarser priority while paused. | **P2** (leak fix pulled into M10) | M10 / M15 |
| **F-11** | Horizontal scaling | Trigger engine, dedupe LRU, WS session registry and coach cache are all **process-local**. No Redis in either requirements file. | Two backend instances split coaching state arbitrarily — a push on A is invisible to a socket on B. | Substitute Redis behind the existing documented seams. | **P2** | M15 (only when a 2nd instance is real) |
| **F-12** | Prod hardening | CORS is `allow_origins=["*"]`; no rate limiting on LLM-spending endpoints; `supabase_jwt_secret` defaults to `"change-me"`; **no CI**. | Prototype-grade security posture; both test suites are run manually. | Restrict CORS; fail fast on default secrets; rate-limit coach/RAG; CI on every change. | **P2** | M11 (CI) / M15 |
| **F-13** | Achievements | 8+ badges evaluated client-side only; nothing server-side references them. | Unlock state is device-local; not portable, not authoritative. | Evaluate inside the existing run-sync transaction; new tables + migration. | **P2** | M14 |
| **F-14** | Repo hygiene | `DevLocationSimulator.kt` and `DevStepSimulator.kt` are unreferenced yet compile into the release APK. Stale `full_run.log`, `ws_run.log`, `test_fitquest.db` at the API root; `tools/synthetic_fitness/output/` carries a committed dataset. | Dead code in production builds; repository noise. | Delete dead code and stale artefacts; reconcile the ignore intent. | **P2** | M15 (any time) |
| **F-15** | Anti-cheat | Server accepts client step totals and hex attribution at face value. No velocity cap, no plausibility check, no adjacency validation. | Leaderboard is now real and server-ranked, making it worth cheating. | Velocity plausibility + H3 contiguity in run-sync; must not reject legitimate runs. | **P2** | M15 |
| **F-16** | Personalization | Pipeline exists (`tools/synthetic_fitness/`) but **no trained model, no serving path, no provider seam** — `recommend()` is a plain function. | SRS §12.2's `RuleBased`/`XGBoost` abstraction is unbuilt; no personalization. | Provider seam behind `recommend()`, rules stay default; train only on sufficient real data. | **P3** | M16 |
| **F-17** | Research instrumentation | Retrieval harnesses exist but run by hand. **Nothing logs which recommendation was shown or whether it was acted on.** | No way to measure whether coaching changes behaviour — the central research claim. | Impression/outcome event table; quota-free subset in CI; consent surface if needed. | **P3** | M16 |
| **F-18** | RAG ingestion API | No ingestion endpoint; ingestion runs via `python -m app.modules.rag.ingestion`. | Corpus updates require backend shell access. | Authenticated admin route wrapping the existing service. | **P3** | M11 (after F-04) |

### Note on the as-built SRS

`FitQuest_AS_BUILT_SRS.md` is authoritative for M1–M9 but is **already stale** on three points, all resolved in favour of the repository:

1. It lists production deployment as deferred (§20) — `render.yaml` exists and Railway is live.
2. It describes auth as having no UI — `ui/auth/LoginScreen.kt` and `ui/auth/WelcomeScreen.kt` exist (though both are unreachable; see §9).
3. Its §21.7 caveat about the 391-test figure being "M9.3 historical, not re-run" is **resolved**: 391 tests collect cleanly today (verified 2026-09-12 via `pytest --collect-only`).

---

## 6. Phase 2 Roadmap

Sequencing is driven by two constraints, not by feature appeal: **correctness items precede anything built on their output**, and **identity precedes anything whose meaning depends on who the user is**. Each milestone is intended to be independently verifiable on a device.

---

### M10 — Telemetry & Run Integrity

- **Objective:** Make the run data the rest of the system depends on correct.
- **Scope:** F-01 (daily telemetry correctness), F-02 (pause/resume integrity), plus the F-10 `locationJob` leak fix at near-zero marginal cost.
- **Included F-items:** F-01, F-02, F-10 (leak only).
- **Dependencies:** None. This is the entry point of Phase 2.
- **Files/modules likely involved:** `core/capture/HexCaptureEngine.kt`, `core/run/RunTiming.kt`, `core/run/ActiveRunController.kt`, `core/run/RunTrackingService.kt`, `features/capture/CaptureScreenModel.kt`, `ui/capture/CurrentRunScreen.kt`, `ui/home/HomeTab.kt`, `core/telemetry/DailyActivitySnapshotBuilder.kt`, `core/data/local/RunSessionDao.kt`.
- **Expected DB/API impact:** **None required.** The snapshot contract already accepts absolute day-to-date values. No migration, no new endpoint. Adding a `paused_seconds` field is *optional* and should be justified before doing it.
- **Android impact:** The bulk of the work. Day-window query; pause gating; UI/FGS paused state; `locationJob` cancellation.
- **Backend impact:** None. Note that the server cannot detect either defect today — it trusts the client's totals. Do not "fix" this by adding server-side inference; that is F-15's separate concern.
- **Testing:** Engine unit tests for paused deltas and resume; pause across process death; Home-vs-snapshot equality for N>3 sessions in one day; device-local day-boundary cases; idempotent re-sync of the same day; a regression test that no location subscription outlives a run.
- **Exit criteria:** See §7.4.
- **Known risks:** The snapshot path is shared with the ML export — a change here silently changes the training dataset. `pendingStepsBeforeHex` accounting must be preserved exactly (§7.3).

---

### M11 — Real Authentication & Identity

- **Objective:** Replace the fixed dev user with real identity.
- **Scope:** F-04, plus CI (F-12) and the RAG ingestion route (F-18) which is unblocked by auth.
- **Included F-items:** F-04, F-12 (CI portion), F-18.
- **Dependencies:** M10 (do not change identity and telemetry semantics in the same step).
- **Files/modules likely involved:** `apps/api/app/api/dependencies.py`, `core/security.py`, `core/config.py`, `modules/users/models.py`, a new Alembic migration `0004_*`, `apps/api/seed.py`, `ui/auth/LoginScreen.kt`, `ui/auth/WelcomeScreen.kt`, `MainActivity.kt`, `core/network/FitQuestApiClient.kt`, `di/AppModule.kt`.
- **Expected DB/API impact:** Add an auth subject column to `user` (migration 0004). Every route swaps its dependency from the stub to bearer validation. `POST /users` needs idempotent-on-subject provisioning or retirement.
- **Android impact:** Real login UI replacing the unreachable placeholder chain; secure token storage (EncryptedSharedPreferences or DataStore); an OkHttp interceptor supplying `Authorization`; 401 → re-auth; a token on the WebSocket URL; the local profile row acquires a server identity.
- **Backend impact:** Confined to `dependencies.py` plus the migration. **Every domain module already keys off `current_user["id"]`**, so runs/map/leaderboard/coach logic needs no change. That is precisely why auth can land without a rewrite — do not restructure domain modules to accommodate it.
- **Testing:** 401 on every route without a valid token; expired-token handling; cross-user isolation on sync, capture and ownership; first-login provisioning; interceptor and token-refresh unit tests.
- **Exit criteria:** Two real accounts can run, capture and rank without ever seeing each other's data; no route answers without a valid token.
- **Known risks:** The existing dev user (`DEV_USER_ID`) owns all current data. Decide explicitly whether to migrate it to a real account or leave it as a seeded test user. Do not silently orphan it.

---

### M12 — Live Coaching Reliability

- **Objective:** Make live coaching survive real network conditions.
- **Scope:** F-03.
- **Included F-items:** F-03.
- **Dependencies:** M11 (per-user push targeting is only meaningful with real identity).
- **Files/modules likely involved:** `core/network/CoachingWsClient.kt`, `core/network/OkHttpCoachingSocketFactory.kt`, `MainActivity.kt`, `apps/api/app/modules/triggers/ws.py`, `apps/api/app/modules/coach/push.py`.
- **Expected DB/API impact:** None for retry hardening. A delivery backlog would require a per-user pending-coaching store with a TTL — a **genuine new decision**, not a given. Record the outcome either way in §13.
- **Android impact:** Jittered longer-horizon retry; reconnect on connectivity change via `ConnectivityManager`; reconnect after foreground reconcile; an explicit "live coaching offline" state instead of silent degradation.
- **Backend impact:** Keep-alive tuning on the WS endpoint. Optionally decide whether a missed push is replayed on reconnect.
- **Testing:** Scripted-fake socket tests for the give-up path (already present) plus reconnect-after-restore; server tests for the no-live-session skip and the queue-full drop.
- **Exit criteria:** A socket killed repeatedly mid-run recovers without an app restart; the UI never claims live coaching is available when it is not.
- **Known risks:** Land both halves together — fixing retry alone exposes the missing-backlog problem *more* often, not less.

---

### M13 — Shared World

- **Objective:** Make the multiplayer game legible and make rankings scale.
- **Scope:** F-05, F-06, F-09.
- **Included F-items:** F-05, F-06, F-09.
- **Dependencies:** M11 for ownership to be meaningful per-user.
- **Files/modules likely involved:** `apps/api/app/modules/leaderboard/{service,router,schemas}.py`, `apps/api/app/modules/map/service.py`, `features/capture/CaptureScreenModel.kt`, `ui/capture/CurrentRunScreen.kt`, `ui/leaderboard/LeaderboardTab.kt`, `core/network/LeaderboardFetcher.kt`.
- **Expected DB/API impact:** Pagination and ranked queries; the viewport query moves from load-all-then-filter-in-Python to SQL — this is the moment to reconsider indexing. `GET /map/{hex_id}` (already implemented, unused by Android) becomes the hex-detail source. `heatmaps` starts being populated.
- **Android impact:** Legend, hex tap target, refresh, honest stale state; pull-to-refresh and offline fallback on the leaderboard; a zoom-dependent heatmap layer.
- **Backend impact:** Ranked leaderboard query; H3 parent-cell roll-up aggregation.
- **Testing:** Own/rival/unclaimed layer split against a fixture viewport; stale-state rendering; tap resolution at bbox edges; tie semantics at the top-N boundary; rank stability under inserts; aggregate totals equal the sum of detail hexes; behaviour exactly at zoom 14.
- **Exit criteria:** A second player's territory is visibly attributed and inspectable; rankings hold under load; zooming out shows the shape of a territory rather than a blank map.
- **Known risks:** Rewriting the viewport query touches the capture screen's hot path. Verify on a real device, not only in unit tests.

---

### M14 — Server-Authoritative Progression

- **Objective:** Settle — once — which progression state the server owns, then move quests, profile and achievements behind it.
- **Scope:** F-07, F-08, F-13.
- **Included F-items:** F-07, F-08, F-13.
- **Dependencies:** M11 (identity), M13 (a settled ranking model informs XP semantics).
- **Files/modules likely involved:** `apps/api/app/modules/quests/*`, `apps/api/app/modules/users/*`, `apps/api/app/modules/runs/service.py`, `core/data/local/{QuestRepository,UserProfileRepository,AchievementRepository}.kt`, `core/network/FitQuestApi.kt`, `ui/profile/ProfileTab.kt`, `ui/achievements/AchievementsTab.kt`.
- **Expected DB/API impact:** New `achievement` / `userachievement` tables plus a migration. XP and level have **no backend representation at all** today — plan a schema addition. `user.total_hexes_captured` is dead and must be either maintained or removed.
- **Android impact:** Replace three working local surfaces with server-backed ones, keeping local caches so offline still works.
- **Backend impact:** Quest progress, achievements and XP/level become server-side computations of run-sync outcomes rather than stored client claims.
- **Testing:** Wipe-local-data-and-reinstall restores state from the server alone; enrol conflict (409); progress idempotency across a replayed sync; achievement unlocked exactly once; streak transitions across day boundaries; server-wins conflict resolution; offline edits reconciling on foreground.
- **Exit criteria:** Wiping the app's local data and reinstalling restores quest progress, profile and achievements from the server alone.
- **Known risks:** **Highest regression risk in the phase** — this milestone replaces working surfaces. Verify offline-first, and do not remove the local caches to "simplify".

---

### M15 — Hardening & Operations

- **Objective:** Operate the system safely and stop it being trivially cheatable.
- **Scope:** F-10 (remainder), F-11, F-12 (remainder), F-14, F-15.
- **Included F-items:** F-10, F-11, F-12, F-14, F-15.
- **Dependencies:** M13 (viewport query rewrite shares the scaling work with F-11); M14 for XP semantics used by anti-cheat.
- **Files/modules likely involved:** `core/sensors/LocationTrackingManager.kt`, `core/permissions/PermissionManager.kt`, `apps/api/app/modules/coach/{cache,push}.py`, `apps/api/app/modules/triggers/{engine,ws}.py`, `apps/api/app/core/config.py`, `apps/api/app/main.py`, `apps/api/app/modules/runs/{schemas,service}.py`, `core/dev/*`.
- **Expected DB/API impact:** A flag column or audit table for rejected/suspicious syncs; CORS and rate-limit configuration.
- **Android impact:** Battery/adaptive-sampling work; dead-code removal slightly shrinks the release APK.
- **Backend impact:** Velocity plausibility and H3 contiguity inside the run-sync transaction — **must not reject legitimate runs**; false positives are worse than the cheating they prevent. Rate limiting needs shared state across instances, which is F-11's territory.
- **Testing:** A battery trace proving no location subscription outlives a run; teleport and near-supersonic traces rejected while pause-heavy and treadmill sessions are accepted; boundary cases at the velocity cap; CI gating both suites; a smoke check that a default secret refuses to start.
- **Exit criteria:** An idle process holds no location subscription; a synchronised trace is rejected while a treadmill run is accepted; CI gates both suites.
- **Known risks:** **Introduce Redis only if a second backend instance is actually being deployed.** Until then it adds operational risk with no benefit — that is the recorded SRS §17 position.

---

### M16 — Research & Personalization

- **Objective:** Measure whether coaching changes behaviour, then — only then — personalize.
- **Scope:** F-17 first, then F-16.
- **Included F-items:** F-17, F-16.
- **Dependencies:** M10 (telemetry must be correct before it becomes training data), M11 (per-user attribution), M14 (server-side XP/streak give the model honest labels).
- **Files/modules likely involved:** `apps/api/app/modules/rag/evaluation.py`, `tools/evaluate_retrieval.py`, `tools/evaluate_live_coach.py`, `apps/api/app/modules/recommendations/service.py`, `tools/synthetic_fitness/*`, `apps/api/requirements-dev.txt`.
- **Expected DB/API impact:** An impression/outcome event table (recommendation served → what the user did next). Serving needs a model artefact store and request-time feature assembly.
- **Android impact:** Emit an event when a recommended target is met or missed; a consent surface if behavioural logging is introduced.
- **Backend impact:** Impression logging alongside the existing `context_fingerprint` (already a stable join key). Then a provider seam in `recommend()`, keeping R1–R5 as the deterministic default.
- **Testing:** Deterministic metric tests on fixture data in CI (no provider call, no quota); impression-logging correctness; consent gating; seam parity (rules path unchanged); deterministic inference; feature-assembly parity between the training export and serving.
- **Exit criteria:** A measured comparison against the R1–R5 baseline, on real labelled data, with numbers reproducible from a committed script.
- **Known risks:** **F-16 is data-gated, not effort-gated.** It cannot start responsibly until the `userdailyactivity` table holds enough real (user, day) rows — the existing `real_telemetry_exporter` makes that readiness measurable. Starting early means training on too little data or on synthetic data, either of which would produce a claim the project must not make (§11).

---

## 7. M10 Detailed Definition — Telemetry & Run Integrity

**Status: NOT STARTED. Scope is F-01 and F-02 only.**

This milestone changes no database schema, no API contract, and no backend behaviour. It is an Android correctness milestone.

### 7.1 F-01 — Daily telemetry correctness

**Current problems, as verified in the repository.**

1. **The Home query is capped at three sessions.** `ui/home/HomeTab.kt`:
   ```kotlin
   val recentSessions by runSessionRepo.observeRecentSessions(limit = 3)...
   val todayString = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
   val todaySteps = recentSessions
       .filter { SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date(it.startedAt)) == todayString }
       .sumOf { it.totalSteps }
   ```
   This reads the **three most recently ended** sessions and *then* filters to today. On a day with four or more runs, the fourth is excluded regardless of date. `RunSessionDao.observeRecentSessions` is `ORDER BY endedAt DESC LIMIT :limit`; the default is 10, but Home passes 3.

2. **Home and the backend snapshot use different sources.** The snapshot path uses `RunSessionDao.getSessionsBetween(start, end)` over the whole local day, so it includes sessions Home omits. The two figures therefore disagree, and Home is the one the user sees.

3. **Only run-tracked steps are counted.** `DailyActivitySnapshotBuilder.build()` sums `RunSessionEntity.totalSteps` across the day's sessions. `StepSensorManager` is consumed by `HexCaptureEngine` only between start and stop tracking. Steps walked outside a run are never read, even though the `TYPE_STEP_COUNTER` sensor reports an absolute device-lifetime total that would make them computable.

**Definitions to make explicit.** "Today's steps" currently means *steps recorded during runs that were saved today*. It does not mean *steps the phone recorded today*. Any UI copy or fix must state which. These are different numbers and the gap is the walking a user does outside the app.

**What must NOT change without an explicit requirement.** Do not add ambient step tracking merely because it seems desirable. Neither `FitQuest_SRS.md` nor `FitQuest_AS_BUILT_SRS.md` requires ambient capture; §5.3 of the planned SRS concerns run steps. Adding it introduces a second step source, a double-counting hazard with run steps, and a new persisted daily baseline. Treat it as a separate, explicitly-approved decision.

**Backend daily activity behaviour (already correct — do not change).**
- Route: the `daily_activity` block of the run-sync payload.
- Contract: `DailyActivitySnapshot` with absolute day-to-date values, validated as date ≤ UTC+1 day, steps 0..1 000 000, active_minutes 0..1440 (`modules/runs/schemas.py`).
- Storage: `upsert_daily_activity` in `modules/runs/service.py` — **merge-upsert on `(user_id, activity_date)`**, where a `None` keeps the stored value.
- **Idempotency:** because the device sends absolute values for the whole day, re-sending the same day upserts to identical values. The run is also guarded by the `run_id` ledger, so an `IntegrityError` resolves to `already_processed`. This is correct by construction and is the invariant M10 must preserve.
- **Day boundary:** `activity_date` is the **device-local** calendar date (`DailyActivitySnapshotBuilder.localDateKey`, and `localDayWindow` for the query window). The server tolerates up to one day of skew (UTC+1). Keep using the device-local date; do not switch to UTC.

**Work items (for the M10 implementation audit, not to be done now).** Replace the Home read with a day-window query; assert Home equals the snapshot in a test; label what the number means; preserve the merge-upsert contract and device-local date.

### 7.2 F-02 — Pause / resume tracking integrity

**Current state — pause is a timing concern only.**

`core/run/RunTiming.kt` is correct and should not be rewritten. Elapsed time is derived, never accumulated:
```kotlin
val reference = pausedSinceMillis ?: atMillis
val active = reference - startedAtMillis - pausedAccumulatedMillis
return active.coerceAtLeast(0L)
```
`paused()` / `resumed()` are idempotent, and the whole struct round-trips through `ActiveRunEntity` for process-death recovery.

`core/run/ActiveRunController.kt` — `pause()` and `resume()` mutate **`_timing` and nothing else**.

`ui/capture/CurrentRunScreen.kt` — the Pause/Resume control is wired to the controller and works.

**The defect.** `core/capture/HexCaptureEngine.kt`:
```kotlin
fun applyStepDelta(delta: Int): HexCaptureSnapshot {
    if (!isTracking) return this          // ← the only guard; paused still accrues
    ...
}
```
While paused:
- `applyStepDelta` keeps adding to `sessionSteps` and to `hexesToSteps[currentHex]`;
- `applyLocationUpdate` keeps registering newly-entered hexes (it also guards on `isTracking` only);
- `CaptureScreenModel` derives distance and calories from `totalSteps`, so they climb too.

**The resulting inconsistency.** In `CaptureScreenModel.finishActiveRun()`:
```kotlin
val durationSeconds = timing.elapsedSeconds(endTime)   // pause EXCLUDED
val totalSteps = hexCaptureEngine.state.value.sessionSteps   // pause INCLUDED
val distance = RunMetrics.distanceMeters(totalSteps)
val calories = RunMetrics.calories(totalSteps)
```
One session object therefore reports an active duration that excludes paused time alongside a step volume that includes it. `DailyActivitySnapshotBuilder` propagates the mismatch: `active_minutes` is derived from `durationSeconds`, `steps` from `totalSteps`.

**No pause signal reaches the backend.** `RunSyncPayload` carries `total_session_steps`, `hexes_to_steps`, `daily_activity` and `run_id` — there is no pause field, and `RunTrackingService` exposes only `ACTION_START_RUN` and `ACTION_STOP_RUN` (with a 5 000 ms notification tick). Adding a pause action to the service and a paused indicator to the notification is in scope; adding a *payload field* is not required by the fix.

**Work items (for the M10 implementation audit).** Gate step consumption while paused; prevent hex attribution while paused; freeze distance and calories; surface the paused state in the HUD and the FGS notification. Do not modify `RunTiming`'s derivation.

### 7.3 Invariant that must be preserved

`HexCaptureEngine` maintains a deliberately exact accounting, introduced in M9.2:

```
sessionSteps = sum(hexesToSteps.values) + pendingStepsBeforeHex
```

Two mechanisms keep it true, and both must survive any change:

- `applyStepDelta` — with a known hex, `delta` goes to both `sessionSteps` and `hexesToSteps[hex]`; without a known hex (no GPS fix yet), `delta` goes to `sessionSteps` **and** to the `pendingStepsBeforeHex` buffer.
- `applyLocationUpdate` — when a hex becomes known and the buffer is non-empty, the buffered steps are attributed to that hex **exactly once** and the buffer is cleared. They are never added to `sessionSteps` again.

**The buffer is not checkpointed.** `resumeTracking()` restarts it empty; pre-hex steps from before a process death live in `sessionSteps` (which is persisted). This is intentional and documented in the code.

Any pause fix must not break this. In particular, do not "simplify" the buffer away, and do not route paused steps into `sessionSteps` on the assumption they will be discarded later.

### 7.4 M10 exit criteria

1. For any number of runs in one device-local day, Home's today-steps equals the `steps` value the snapshot sends to the backend.
2. No steps, hexes, distance or calories accrue while a run is paused; resuming continues correctly from the paused state.
3. Pause survives process death and restores the paused state.
4. `sessionSteps = sum(hexesToSteps.values) + pendingStepsBeforeHex` still holds after pause/resume cycles, including across a process death.
5. No location subscription outlives a run (F-10 leak fix).
6. Existing Android tests remain green; new tests cover each of 1–5.
7. A real-device run confirms 1–3 with logcat evidence.
8. No backend, schema, or API change was required.

---

## 8. Architecture & Authority Rules

Permanent rules. Verify each against the repository before overriding; add any change to §13 first.

### Layering and authority

| # | Rule | Rationale / evidence |
|---|---|---|
| A1 | **FastAPI is the business-logic layer.** No game logic in Android that the server also computes. | `apps/api/app/modules/*` hold the rules; Android mirrors only for offline display. |
| A2 | **Supabase PostgreSQL is the central backend source of truth** for all shared state. | `DATABASE_URL` required with no fallback; Alembic-managed. |
| A3 | **The backend is authoritative for competitive state** — territory, ownership, and (as of M14) XP, quests and achievements. | Turf war is applied server-side in `runs/service.py`. |
| A4 | **Android Room is a local/offline cache and state store, not a source of truth.** | Room v5; `RunReconciler` treats the server as the destination of record. |
| A5 | **Run sync is idempotent via run identity.** The `run_id` ledger plus byte-identical payload replay is the sync design. | `RunSession` ledger; `pendingSyncPayloadJson`; `IntegrityError → already_processed`. |
| A6 | **Daily activity is an absolute, idempotent, device-local-day merge-upsert.** | `upsert_daily_activity`; `DailyActivitySnapshot` validators. |

### Client architecture

| # | Rule | Rationale / evidence |
|---|---|---|
| A7 | **Do not rewrite the working Android architecture.** Voyager navigation + ScreenModels, Orbit MVI, Koin DI, Compose/Material 3, Room, Retrofit/OkHttp are settled. | Consistent across all 75 main source files; rewriting is pure regression risk. |
| A8 | **Pause is a timing concept in `RunTiming`; do not reimplement elapsed time as an accumulated counter.** | The derived form is correct across backgrounding, lock and process death. |
| A9 | **Preserve the hex step-accounting invariant** (§7.3). | Introduced deliberately in M9.2; protects against step loss and double counting. |
| A10 | **Native Android TTS is the current presentation layer** for coaching. | `AndroidTtsSynthesizer`, `QUEUE_FLUSH`, gated by `drop(1)`. |

### AI / data

| # | Rule | Rationale / evidence |
|---|---|---|
| A11 | **The recommendation engine stays rules-first until ML has enough real data.** R1–R5 remain the default and the baseline to beat. | SRS §12.2; F-16 is data-gated. |
| A12 | **RAG uses pgvector** with a frozen 1536-dimension schema and HNSW cosine. A future embedding-model change requires a migration and full re-ingestion. | `config.py` comments; `0003_rag_knowledge_base`. |
| A13 | **The LLM stays behind the existing provider abstraction** (`get_llm_provider()`), selected by `LLM_PROVIDER`. Embeddings are always Gemini in both modes. | `modules/coach/llm.py`; `config.py`. |
| A14 | **Never present synthetic data as real-user evidence.** | `tools/synthetic_fitness/README.md` states this explicitly; every artefact is labelled. |
| A15 | **Backend secrets never reach Android**; no secret is logged or echoed in a response. | Enforced by absence from Gradle; comments in `FitQuestApiClient.kt` and `AppModule.kt`. |

### Scope boundaries

| # | Rule |
|---|---|
| A16 | **Web3 / blockchain / NFT / IPFS stay deferred.** SRS §4.1 and Rule 6 forbid implementation; §34 forbids presenting the product as having it. |
| A17 | **Kafka / an event broker stays deferred.** SRS §4.3. The trigger engine is in-process by design. |
| A18 | **Redis is optional and must not be introduced without a real multi-instance requirement.** SRS §17. Substitution seams exist; use them when the need is real. |
| A19 | **Do not invent new game rules without an explicit product decision.** SRS §10.4: retain capture / defend / steal. |
| A20 | **No generic outbox framework.** The run ledger + reconcile superseded it. A narrow, entity-specific queue is acceptable if a second entity ever needs offline replay. |

---

## 9. Multi-user & Identity Direction

**Status: PLANNED. Do not implement in M10.**

### Current state — verified

**Backend.** `apps/api/app/api/dependencies.py` contains the entire auth surface:
```python
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"

def get_current_user() -> dict[str, str]:
    """Dev stub — returns a fixed user. Replace with real auth in production."""
    return {"id": DEV_USER_ID}
```
A `TODO(production)` block immediately above sketches the intended replacement using `HTTPBearer` and `decode_supabase_jwt`. Because the stub is a FastAPI dependency, every route already receives a user id through the same interface — this is what makes the swap contained.

**Dormant JWT capability.** `apps/api/app/core/security.py` implements `decode_supabase_jwt(token)` using `jose.jwt.decode` with HS256 and `verify_aud=False`, raising `ValueError` on failure. It is **imported by nothing in the codebase**. `python-jose[cryptography]==3.5.0` is nevertheless a *production* dependency and `settings.supabase_jwt_secret` exists (defaulting to the literal `"change-me"`). The seam is built; only the wiring is missing.

**Android auth UI.** `ui/auth/WelcomeScreen.kt` pushes `ui/auth/LoginScreen.kt`, whose only button runs:
```kotlin
// Simulate auth success and navigate to hub,
// completely replacing the auth stack
navigator.replaceAll(MainHubScreen())
```
**Reachability, verified:** `WelcomeScreen` is referenced by **nothing**, and `MainActivity.resolveStartScreen()` returns only `OnboardingScreen`, `CurrentRunScreen` or `MainHubScreen`. The Welcome → Login chain is therefore unreachable dead code. Do not mistake its presence for a partial auth implementation.

**Identity today.** The app's profile is the Room row `local_user`. It has never been synced to the backend `user` table. Backend users exist only because `seed.py` creates them.

### Intended transition

1. Choose the identity provider (Supabase Auth is the natural fit given the existing secret and decoder).
2. Add an auth subject column to `user` (migration `0004_*`).
3. Replace the `get_current_user` stub with bearer-token validation.
4. Make `POST /users` idempotent on the subject, or retire it in favour of auto-provision-on-first-login.
5. Replace the Android placeholder chain with real login and signup.
6. Store tokens securely; add an OkHttp interceptor; handle 401 by re-authenticating.
7. Authenticate the WebSocket connection.

### Server-side user isolation requirements

- Every existing route must return 401 without a valid token — including `GET /health`? **No:** `/health` is a liveness probe and must stay unauthenticated. All `/api/v1/*` routes must be gated.
- Cross-user isolation must be proven for: run sync (a payload must never be applied to another user's territory), hex ownership reads, the leaderboard's "current user" entry, and coaching pushes (which must target only the authenticated session's user).
- `DEV_USER_ID` currently owns all existing data. Its fate must be an explicit decision, not a side effect.

### Expected impact on REST and WebSocket

- **REST:** mechanically small — one dependency function, one migration, one client-side interceptor. Domain modules should not change.
- **WebSocket:** the connection currently carries no identity, so the server cannot associate a socket with a user. Real auth requires passing a token on connect (query parameter or first frame) and validating it before registering the session. This is a genuine change to `triggers/ws.py`, not a dependency swap.
- **Configuration:** `supabase_jwt_secret` must stop defaulting to `"change-me"`; the app should fail fast at startup when it is left unset in a non-development environment (F-12).

---

## 10. AI / Coaching Architecture

**Status: IMPLEMENTED end to end.** Personalization is the only unbuilt part.

### Pipeline

```
FitnessContext  (steps, streak, level, hexes, recent activity)
      │
      ▼
Recommendation          modules/recommendations/service.py — rules R1–R5, deterministic, no provider seam
      │
      ▼
RAG retrieval           modules/rag/ — pgvector, gemini-embedding-001 (1536d), HNSW cosine
      │                 threshold 0.50 · top-k 4 · honest grounded=false fallback
      ▼
LLM                     modules/coach/llm.py — get_llm_provider()
      │                 gemini (gemini-2.5-flash) | agentrouter (deepseek-v4-flash)
      ▼
CoachResponse           grounded flag + retrieval info + advice text
      │
      ├──────────────► PULL: GET /api/v1/coach  → Android CoachFetcher → Home Coach card (manual Retry only)
      │
      └──────────────► PUSH: TriggerEngine → PushCoach → WS fan-out → CoachingWsClient → LiveCoachStore
                                                                              │
                                                                              ▼
                                                                    CoachingSpeechController (drop(1))
                                                                              ▼
                                                                    CoachingSpeechGate
                                                                              ▼
                                                                    AndroidTtsSynthesizer (QUEUE_FLUSH)
```

### Component notes

**Recommendation rules.** R1–R5 produce the deterministic recommendation embedded in `FitnessContext`. `recommend()` is a **plain function with no provider/model seam** — this is what F-16 must introduce (SRS §12.2 specifies `RuleBasedRecommendation` / `XGBoostRecommendation` behind a `RecommendationService` abstraction). R1–R5 must remain the default and the evaluation baseline.

**RAG role.** Grounds coaching advice in a 7-document WHO/CDC corpus stored in pgvector. Retrieved chunks are supplied to the LLM as context. When retrieval is weak the response is honestly marked `grounded=false` rather than embellished — a deliberate product decision, not a limitation to "fix".

**Embedding model / dimension.** Gemini `gemini-embedding-001`, **1536 dimensions**, HNSW cosine index. Frozen: a different embedding model requires a migration and full re-ingestion.

**Similarity threshold.** **0.50**, derived from a recorded live calibration probe (2026-09-06) rather than guessed: on-topic chunk similarities 0.60–0.77, clearly unrelated queries 0.43–0.46, leaving an empty band with roughly 0.10 margin on each side. Too high degrades to the grounded=false fallback; too low admits unrelated text as knowledge.

**LLM provider abstraction.** `get_llm_provider()` selects by `LLM_PROVIDER`. Both providers sit behind one interface, so no caller changes when the provider switches. AgentRouter requires the `User-Agent` client-filter header noted in §3.

**Pull vs push.**
- *Pull* (`GET /api/v1/coach`) renders in the Home Coach card. Failures are **never auto-retried**; the UI offers a manual Retry. The AI section is independent of the deterministic recommendation section, so a slow or failing LLM call never blocks the rest of Home.
- *Push* is triggered by real events during a run — `WORKOUT_COMPLETED`, `TERRITORY_CAPTURED`, `ACTIVITY_MILESTONE` (5 000 / 10 000 / 15 000 / 20 000 steps) — and delivered over the WebSocket. Display precedence is decided by `CoachDisplaySelector`: a live pushed message wins when present, otherwise the pull outcome is shown exactly as before.

**Coach caching / freshness.** `CoachCache` is an LRU of 200 users keyed by a context fingerprint (`fix-e-v1`), so an unchanged context reuses a generation rather than paying for another LLM call. `PushCoach` coalesces bursts with a 30 s per-user cooldown and 2 workers.

**WebSocket delivery.** `triggers/ws.py` — one `asyncio.Queue` per session, `SESSION_QUEUE_SIZE = 256`, drop-on-full. No server-side keepalive, no backlog. `PushCoach` skips generation when the user has no live session.

**TTS.** Native Android `TextToSpeech` with `QUEUE_FLUSH`, fed through `CoachingSpeechController` (a `drop(1)` that keeps only the newest line) and `CoachingSpeechGate`.

**Failure behaviour — by design.**
| Failure | Behaviour |
|---|---|
| LLM unavailable / quota exhausted | Graceful state; no fabricated coaching text; manual Retry |
| Retrieval below threshold | `grounded=false`; honest, non-embellished response |
| WebSocket disconnected | Silent degradation to the pull path (**F-03**: the silence is the defect, not the fallback) |
| Push attempt with no live session | Skipped entirely; the message is lost, not queued |

**Future personalization.** Not implemented. See §11 and F-16. The rules engine remains authoritative until a model demonstrably beats it on a documented protocol.

---

## 11. Research & Evaluation Plan

### Current RAG evaluation — IMPLEMENTED, manual by design

- `apps/api/app/modules/rag/evaluation.py` holds 10 labelled coaching queries with Recall@k and hit-rate metrics.
- `apps/api/tools/evaluate_retrieval.py` and `apps/api/tools/evaluate_live_coach.py` run them against live providers.
- These sit **outside pytest deliberately**, because they spend API quota. This is a considered decision, not an oversight.

**Limitations.** The harness has no CI presence, so threshold drift is not caught automatically. Ten queries is a small sample. There is no automated comparison against a committed baseline result.

### Synthetic fitness data tooling — IMPLEMENTED

`apps/api/tools/synthetic_fitness/`:
- a deterministic dataset generator with 7 behavioural archetypes;
- leakage-safe feature engineering — **21 features**, with windows proven by future-perturbation and cross-user-tampering tests;
- a deliberately **non-circular target**: `inactive_next_3d`, a future-behaviour label rather than the rules engine's own output;
- a first XGBoost experiment;
- `real_telemetry_compat.py` and `real_telemetry_export.py`, which turn the live `userdailyactivity` table into the **identical feature shape** under a different `data_source` label.

The toolkit is standard-library-only plus a dev-scoped XGBoost dependency (`requirements-dev.txt`); `xgboost` is deliberately absent from production requirements.

**Honesty rules, from `tools/synthetic_fitness/README.md`:** every artefact is labelled synthetic; synthetic metrics must never be presented as real-user evidence. The README states plainly that no real telemetry had been collected at the time of writing.

### Real telemetry requirements

Real training data flows: run → `RunSession` (Room) → run sync → `DailyActivitySnapshot` → `upsert_daily_activity` → `userdailyactivity` (Supabase) → `real_telemetry_export.py` → feature rows labelled `real`.

**The table is currently populated only by runs.** It contains no ambient activity and, until F-01 is fixed, is derived from a Home/snapshot pair that can disagree. Readiness for F-16 should be measured by running the exporter and counting distinct real (user, day) rows.

### Recommendation baseline

R1–R5 are the baseline. They are deterministic, cheap, explainable, and testable without any model or API call — which makes them the correct default and the correct yardstick.

### Future XGBoost personalization — see F-16

Requires: a trained model, a serving path, and a provider seam in `recommend()`. None exist. `xgboost` would be promoted to a production dependency or moved to a separate service.

### Need for impression / outcome instrumentation — see F-17

Nothing currently records which recommendation was shown or whether the user acted on it. Without that, no claim about coaching effectiveness is measurable. The existing `context_fingerprint` is already a stable join key for such an event table.

### Requirement to compare ML against the rules baseline

Any model must be evaluated against R1–R5 on real labelled data, using a documented protocol, with results reproducible from a committed script — not from an ad-hoc notebook run.

### Why F-01 must precede F-16

1. **The training set is the telemetry table.** F-01 fixes an undercount in exactly the data F-16 trains on. Training first would bake a known measurement defect into the model, and the model would then be evaluated against a baseline measured on the same defective data — a comparison that cannot be trusted in either direction.
2. **A deployed model is hard to invalidate.** Once personalization ships, "the model is wrong because the labels were wrong" is expensive to establish.
3. **Ordering is cheap; re-training is not.** F-01 is a small contained fix. Fixing the substrate first costs little and removes an unbounded later risk.

---

## 12. Testing & Definition of Done

### Current baseline — verified 2026-09-12

| Suite | Size | Notes |
|---|---|---|
| Backend (`apps/api/tests/`) | **21 test files** + `conftest.py` · **245 `def test_` functions** · **391 tests collected** | Verified via `./.venv/Scripts/python.exe -m pytest --collect-only -q` → `391 tests collected in 5.64s`. The function-to-case gap is parametrization (3 `@pytest.mark.parametrize` sites). |
| Android (`apps/app/fitquest/src/test/`) | **22 test files** · **153 `@Test` methods** | JVM unit tests (JUnit). |
| Android source | **75 main `.kt` files** | |

**Build verification.** Android debug build is the routine check; the release path is exercised by producing the `railway`-flavor APK.

**Real-device verification.** The project's working practice: install on the physical Samsung device, exercise the flow, and capture **logcat evidence** (FGS notification, sync confirmation, TTS utterance completion). `docs/docs/ui/evidence-4c3b/` holds a prior example. This is required for anything touching sensors, the foreground service, the WebSocket, or TTS — unit tests cannot substitute.

**Production verification.** Deploy to Railway and exercise the same flow with the `railway`-flavor APK over a real network, with no cable attached.

**Test environment caveat.** The backend suite runs over a SQLite-compatible stack; the pgvector path is exercised on PostgreSQL with a portable cosine fallback for SQLite. A green suite therefore does not by itself prove the Postgres-specific path.

### Standard Phase 2 milestone Definition of Done

A milestone is complete only when **all ten** hold:

1. **Code implemented** to the milestone's stated scope — no more, no less.
2. **Integration verified** — the changed component behaves correctly with the components it talks to.
3. **Data flow verified** end to end — device state → payload → server → database, inspected at each hop.
4. **Errors handled** — the failure path is deliberate and shows an honest state to the user. No silent swallowing.
5. **Tests added or updated** covering the new behaviour, including its boundaries.
6. **Existing tests remain green** — both suites.
7. **Real-device test** where the change touches sensors, location, the foreground service, networking or TTS.
8. **Documentation updated** — this document's §5, §6, §13 and §14 at minimum; component docs in `docs/` where behaviour changed.
9. **No accidental architecture regressions** — §8's rules still hold, or the change was recorded in §13 first.
10. **Claims match actual implementation** — every statement of what was built is checkable in the repository. No inflation.

**Additionally, for this project:** run the backend suite from `apps/api/.venv`, and prefer reporting a count you actually observed over one copied from an older document.

---

## 13. Decision Log

Living log of established decisions. Every entry is grounded in the SRS, the repository, or a recorded project event — nothing is invented. **Add new decisions here rather than silently changing architecture.**

| D-ID | Date | Decision | Reason | Affected area | Status |
|---|---|---|---|---|---|
| **D-001** | 2026-09-05 | Supabase PostgreSQL is the backend database, accessed via the Supavisor transaction pooler. | Managed Postgres with pgvector; the direct `db.<ref>` host is unreachable (IPv6 limitation on the dev machine). | Backend, deployment | Active |
| **D-002** | 2026-09-05 | Alembic manages schema from `apps/api`; no destructive auto-migration. | Explicit, reviewable schema changes. | Backend | Active |
| **D-003** | — | H3 resolution 10, grid ring k=2. | ~15 m cells give meaningful territory granularity for walking. | Android, backend | Active |
| **D-004** | — | Raw latitude/longitude never leaves the device; only H3 cell IDs are synced. | Privacy: the server never stores a movement trace. | Android, backend | Active |
| **D-005** | — | Turf war is exactly three rules: +50 new capture, +10 reinforce, +100 steal. | SRS §10.4 — do not invent new game rules. | Backend | Active |
| **D-006** | — | Run sync is idempotent via a `run_id` ledger with byte-identical payload replay. | Survives retries and process death without double-capturing. | Android, backend | Active |
| **D-007** | — | The generic outbox pattern is superseded; do not build it. | The run ledger + reconcile solved the same problem with less machinery. | Android | Active |
| **D-008** | 2026-09-05 | Authentication is deferred; a fixed dev user is returned by `get_current_user`. | SRS §4.2 — out of scope for the demo phase. | Backend | **Superseded by M11** |
| **D-009** | 2026-09-05 | `decode_supabase_jwt` is implemented but intentionally unwired. | Prepares the seam without enabling auth prematurely. | Backend | Active (consumed by M11) |
| **D-010** | 2026-09-05 | One provider (Gemini) covers both embeddings and the LLM. | SRS §14. | AI | Active |
| **D-011** | 2026-09-05 | pgvector with a frozen 1536-dimension schema and HNSW cosine. | Changing the embedding model requires a migration and full re-ingestion. | AI, database | Active |
| **D-012** | 2026-09-06 | Retrieval similarity threshold is 0.50, from a live calibration probe rather than a guess. | On-topic 0.60–0.77 vs unrelated 0.43–0.46; an empty band sits between. | AI | Active |
| **D-013** | 2026-09-06 | An `AgentRouterLLMProvider` was added behind `LLM_PROVIDER` after Gemini's free-tier daily quota was exhausted mid-session. | Device testing could not proceed otherwise; embeddings stay on Gemini. | AI, config | Active |
| **D-014** | 2026-09-06 | AgentRouter requires `User-Agent: claude-cli/1.0.0 (external, cli)` or it returns 401. | App-level client filter on the gateway; verified live. | AI | Active |
| **D-015** | 2026-09-06 | A weak retrieval result returns `grounded=false` rather than an embellished answer. | Honesty over apparent capability. | AI | Active |
| **D-016** | 2026-09-06 | Coach pull failures are shown with a manual Retry; there is no polling or auto-retry. | Avoids burning LLM quota on a failing provider. | Android | Active |
| **D-017** | — | The push coaching stage is in-process with no broker, bounded by a 30 s cooldown and 2 workers. | SRS §17 treats Redis as optional; bounds are safe at demo load. | Backend | Active |
| **D-018** | — | Redis is optional and must not be introduced without a real multi-instance requirement. | SRS §17 warns against adopting it because a research paper mentions it. | Infrastructure | Active |
| **D-019** | — | Kafka is out of scope for the MVP. | SRS §4.3. | Infrastructure | Active |
| **D-020** | — | Web3 / blockchain / NFT / IPFS are not implemented and must not be claimed. | SRS §4.1, Rule 6, §34. | Product | Active |
| **D-021** | 2026-09-07 | M9.2 reliability changes were committed by the project owner in `85f2232`. | Recorded in the as-built SRS. | Process | Historical |
| **D-022** | 2026-09-12 | Android ships **two backend flavors**: `railway` (production URL fixed at build time) and `local` (overridable LAN fallback). The production flavor deliberately does not read `.env`. | Prevents a local LAN IP from leaking into the production APK. | Android, deployment | Active |
| **D-023** | 2026-09-12 | The recommendation engine remains rules-first; ML is data-gated, not effort-gated. | F-01 must fix telemetry before it becomes training data. | AI, research | Active |
| **D-024** | 2026-09-12 | Phase 2 proceeds as M10–M16 with correctness before identity before multi-user features. | Two ordering constraints: output-dependence and identity-dependence. | Process | Active |

---

## 14. Milestone History

Update this section at the end of every milestone. Do not mark anything complete without repository or device evidence.

| Milestone | Status | Date completed | Evidence |
|---|---|---|---|
| **M1–M9** (pre-Phase 2) | COMPLETE | through 2026-09-07 | See §4 and `docs/agent_ledger.md` |
| **M10 — Telemetry & Run Integrity** | **NOT STARTED** | — | — |
| **M11 — Real Authentication & Identity** | NOT STARTED | — | — |
| **M12 — Live Coaching Reliability** | NOT STARTED | — | — |
| **M13 — Shared World** | NOT STARTED | — | — |
| **M14 — Server-Authoritative Progression** | NOT STARTED | — | — |
| **M15 — Hardening & Operations** | NOT STARTED | — | — |
| **M16 — Research & Personalization** | NOT STARTED | — | — |

### Record template (for completed milestones)

```
### M<n> — <Name>   [COMPLETED <YYYY-MM-DD>]
- Changes:
- Files / modules:
- Tests added or updated (and observed counts):
- Real-device evidence:
- Known limitations carried forward:
- Decisions recorded (§13):
```

---

## 15. Deferred / Explicitly Rejected Features

These are **decisions, not oversights**. Do not add any of them without a new explicit product requirement recorded in §13.

| Item | Why deferred | What would justify revisiting |
|---|---|---|
| **Web3 / blockchain / NFT / IPFS / marketplace** | SRS §4.1 forbids implementation; Rule 6 restates it; §34 forbids presenting the product as having it. No trace exists in the repository — no contract, wallet, chain client, or token dependency. | A concrete product requirement. The architectural seam is clean — territory ownership is one table with one owner column — so nothing needs to be built in advance. |
| **Kafka / event broker** | SRS §4.3 rules it out for the MVP. The trigger engine is in-process by design and needs no broker. | Almost certainly never. If cross-instance delivery is genuinely needed, Redis pub/sub behind the existing seam is the proportionate answer. |
| **Generic outbox framework** | Superseded — the run ledger plus byte-identical replay solved the same problem with less machinery, and is verified working. | A second entity type needing offline replay. **A narrow, entity-specific queue is acceptable; a generic framework is not.** Profile edits (F-08) are the first candidate. |
| **Territory decay, seasons, loop-enclosure capture, factions/clubs, fog of war** | SRS §10.4: retain capture / defend / steal and do not invent new game rules without need. None are implemented; capture is strictly per-hex. | A deliberate game-design decision. Decay in particular would change XP and ownership semantics and interact with every leaderboard and recommendation rule. |
| **Production ML infrastructure** (feature store, serving cluster, MLOps pipeline, training orchestration) | SRS §4.4. The toolkit is deliberately standard-library-only plus a dev-scoped XGBoost. | Never at this project's scale. F-16 should be **one loadable model artefact, not a platform.** |
| **Redis before a real multi-instance need** | SRS §17: optional, and explicitly not to be adopted merely because research literature mentions it. Substitution seams are documented rather than pre-built. | An actual second backend instance. Until then it adds operational risk with no benefit (F-11). |
| **Social / friendship** | `docs/requirements.md` declares it out of scope for the offline sprint. A complete `Friendship` model exists in `modules/users/models.py` and is imported by `seed.py`, but **no router exposes it, nothing queries it, and there is no UI**. | After M11 — a friends system without real identity is not meaningful. **Note:** `ui/friends/FriendsTab.kt` is currently a UI misnomer — it is titled "Trophies" and delegates to `AchievementsTab`. Renaming or removing it is cheap and could be done at any time. |
| **RAG ingestion API** | Correctly absent: exposing ingestion requires authorisation that does not exist, and an unauthenticated write path into the vector store would be a vulnerability. | Immediately after M11 (F-18). |

---

## 16. Repository Hygiene / Operational Notes

### Directory map

| Path | Contents |
|---|---|
| `apps/api/` | FastAPI backend. `app/modules/*` (runs, map, leaderboard, recommendations, coach, rag, quests, users, triggers), `app/core/` (config, database, security), `alembic/versions/`, `tests/`, `tools/` |
| `apps/app/` | Android project. Module `fitquest/` holds `src/main/java/com/example/mobileapp/` |
| `docs/` | Component deep-dives (`architecture.md`, `hex-system.md`, `capture-engine.md`, `sensors-and-simulators.md`, `persistence.md`, `backend-schema.md`), `DEMO_DAY_CHECKLIST.md`, `agent_ledger.md`, `requirements.md`, `todo.md`, and a nested `docs/docs/` holding ADRs and device evidence |
| `graphify-out/` | Generated analysis output |
| root | `FitQuest_SRS.md`, `FitQuest_AS_BUILT_SRS.md`, `FitQuest_PHASE2_SRS.md` (this file), `README.md`, `AGENTS.md`, `LICENSE`, `render.yaml` |

### Key locations

- **Backend:** `apps/api` — run with `apps/api/.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000`. Migrations: `alembic upgrade head`. Tests: `pytest` (391 collected).
- **Android:** `apps/app` (Gradle wrapper 8.13). Unit tests: `apps/app/fitquest/src/test/`.
- **Tools:** `apps/api/tools/` — evaluation harnesses and `synthetic_fitness/`.
- **Deployment blueprint:** `render.yaml` at the **repository root** (not under `apps/api` — its `rootDir` key points there).
- **Configuration:** backend via `.env` at `apps/api/` or the repo root; Android build-time via `apps/app/.env`.

### Environment variable strategy

- Backend settings are declared in `apps/api/app/core/config.py`. `DATABASE_URL` is required with no fallback; everything else is optional with a working default. `extra="ignore"` lets one master `.env` serve both backend and Android without conflict.
- Android build-time values are read by Gradle and written into `BuildConfig`. Only the `local` flavor consults `.env` for its backend URL; `railway` deliberately does not.

### Secret handling

- Secrets live in `.env` files (never committed) and in the Railway/Render dashboards as `sync: false` variables.
- **Never commit, log, echo in a response, or copy into a document:** `DATABASE_URL`, `SUPABASE_SECRET_KEY`, `GEMINI_API_KEY`, `AGENTIC_API_KEY`, `SUPABASE_JWT_SECRET`, `MAPTILER_API_KEY`.
- The `railway` backend base URL is **not** a secret — it is compiled into the shipped APK. The MapTiler **key** is a secret even though it is injected into a style URL.
- `supabase_jwt_secret` still defaults to the literal `"change-me"`; production adoption of auth (M11) must make that a startup failure.

### Deployment notes

- Backend: Railway (primary, live) with `render.yaml` as an alternative blueprint. Health check at `/health` — this route stays unauthenticated after M11.
- Database: Supabase, schema via Alembic. The pooler endpoint is required from the development machine.
- Android: build the `railway` flavor for production; the `local` flavor is for development and demo only, and its plain-HTTP transport is not a production posture.

### Git ownership rule

> **The user manually controls Git history.**
>
> AI agents and automated tooling **must not** commit, push, reset, revert, checkout, restore, amend, create branches, or stash **unless explicitly authorized in a future task.**

This rule is authoritative for Phase 2 and overrides prior standing instructions in the repository:

- `AGENTS.md` §6 ("Git Commit Policy") instructs agents to `git add` and `git commit` for every change. **That policy is suspended.** Do not follow it unless the user re-authorizes it in the current task.
- `.agent-context.md` §6 ("Git Branching Policy") states commits must never be made directly on `main` and that feature branches require explicit permission. Consistent with the rule above; both are gated on explicit authorization.

When in doubt: make the change, report it, and leave Git entirely to the user.

### Working protocol files

`AGENTS.md` and `.agent-context.md` describe a session protocol (read `.agent-context.md` at turn start, maintain `docs/todo.md` per branch, log completed work in `docs/agent_ledger.md`, keep the stable-architecture section append-only). The **Git portions of that protocol are suspended**; the rest remains useful. `.agent-context.md`'s `## Stable Architecture Requirements Log` is append-only and durably records project-wide build/test/run/deploy guidance.

---

## 17. Current Next Action

```
CURRENT MILESTONE:
M10 — Telemetry & Run Integrity

NEXT ACTION:
Perform a read-only M10 implementation audit/plan before making code changes.
```

**Stage 1 — Read-only M10 implementation audit.** Before any code is touched:

1. Re-verify every claim in §7 against the repository (they were verified on 2026-09-12; confirm nothing has drifted).
2. Trace the full step path end to end: `StepSensorManager` → `HexCaptureEngine.applyStepDelta` → `CaptureScreenModel.finishActiveRun` → `RunSessionEntity` → `DailyActivitySnapshotBuilder` → `RunSyncPayload` → `upsert_daily_activity`. Identify every point where paused steps enter and where the two telemetry sources diverge.
3. Identify every call site of `observeRecentSessions` and `getSessionsBetween` and determine which are affected by the limit-3 defect.
4. Decide — explicitly, and before coding — what "today's steps" means to the user, and whether ambient step capture is in scope. **The default answer is no**: no current requirement demands it (§7.1).
5. Confirm the §7.3 invariant and write down the exact place a pause guard must sit so the invariant cannot break.
6. Produce an implementation plan with the test list that will satisfy §7.4's exit criteria.

**Stage 2 — Implement** only after Stage 1's plan is reviewed. M10 changes no schema, no API contract and no backend behaviour; if a plan starts to require one, stop and re-examine it against §8.

> **Do not start M11 until M10's exit criteria (§7.4) are satisfied.**

---

*End of document. Update §1 (last updated), §5, §6, §13 and §14 at the end of every milestone.*
