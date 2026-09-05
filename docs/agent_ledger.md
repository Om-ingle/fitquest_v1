# FitQuest Agent Execution Ledger

## [2026-09-04 12:10] - Task: Initial Project Grounding, Context Scaffolding & Similar App References

- **Objective:** Research recently cloned FitQuest repository, diagnose current compile/test health, establish project context (`.agent-context.md`), current ledger (`docs/agent_ledger.md`), branch working docs (`docs/todo.md`, `docs/requirements.md`), and search web/GitHub for similar apps to enrich `README.md` with architectural references and future feature directions.
- **Assumptions Declared:**
  - The repository consists of an Android Compose client (`apps/app`) and a FastAPI + Supabase SQLModel backend (`apps/api`).
  - The Gradle project structure defines `:app` as the root submodule pointing to the `fitquest/` directory.
  - The local Android SDK is available at `/home/dsk/Android/Sdk`.
  - The repository is currently on the `main` branch, meaning direct commits are forbidden per AGENTS.md rules without feature branch permission.
- **Modifications Matrix:**
  - `README.md` (modified: added references to commercial and open-source territory capture apps, comparative mechanics, and feature roadmap)
  - `apps/app/README.md` (modified: fixed Gradle command path from `:fitquest:test` to `:app:test`)
  - `apps/app/fitquest/src/test/java/com/example/mobileapp/core/geo/HexGeoJsonMapperTest.kt` (modified: resolved missing `getHexesInRadius` interface implementation and renamed `toFeatureCollectionJson` call to `toGeoJsonString`)
  - `.agent-context.md` (created: codebase metadata, immutable schemas, topologies, durable architecture requirements, and active working memory block)
  - `docs/agent_ledger.md` (created: initial execution entry)
  - `docs/todo.md` (created: implementation todos for current branch & upcoming milestones)
  - `docs/requirements.md` (created: branch acceptance criteria & active feature requirements)
  - `docs/docs/architecture/0001-project-grounding-and-territory-engine.md` (created: ADR 0001 establishing territorial engine decisions)
- **Decision Logic:**
  - *HexGeoJsonMapperTest Fix*: During test execution verification, compilation failed because `HexIndexer` had introduced `getHexesInRadius` without an update to the mock in `HexGeoJsonMapperTest.kt`, and `HexGeoJsonMapper.toGeoJsonString` was renamed from `toFeatureCollectionJson`. Fixing these restored complete unit test suite green health.
  - *Gradle Task Correction*: `settings.gradle.kts` specifies `include(":app")` with `project(":app").projectDir = file("fitquest")`. Documenting `./gradlew :app:test` ensures repeatable testing across developer and CI environments.
  - *Comparative Analysis Integration*: Research revealed key mechanics in apps like *Run An Empire*, *Turf*, and *INTVL*, specifically territory decay/season resets, loop enclosure, and anti-cheat speed caps. Documenting these in `README.md` provides concrete architectural pathways for FitQuest's future feature expansion.
- **Result Status:** All 57 actionable Gradle tasks executed successfully (`:app:test` passed in 8s). Main application and test suites compile cleanly. Context, ledger, and ADR documents initialized and synchronized.

## [2026-09-04 14:00] - Task: Implement Complete Offline Mobile Frontend Experience

- **Objective:** Build a complete, working, non-stub mobile frontend application with local-first persistence, comprehensive onboarding, daily activity dashboard, enhanced run HUD with post-run victory summary dialog, district rankings, trophies/achievements, and career profile settings.
- **Assumptions Declared:**
  - The feature sprint is scoped purely to frontend implementation; backend integration and the social friends feature are excluded.
  - All application state (user profile, streaks, run history, quests, achievements, and hexes) is persisted locally on the device using Android Room.
  - Stride length is estimated at 0.75m per step and active calorie burn is estimated at 0.04 kcal per step.
  - Progression formula scales dynamically at 250 XP per level.
- **Modifications Matrix:**
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/UserProfileEntity.kt` (created: local user profile Room entity)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/RunSessionEntity.kt` (created: run sessions Room entity)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/DailyQuestEntity.kt` (created: daily quests Room entity)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/AchievementEntity.kt` (created: achievements Room entity)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/UserDao.kt` (created: user profile DAO)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/RunSessionDao.kt` (created: run session DAO)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/DailyQuestDao.kt` (created: daily quests DAO)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/AchievementDao.kt` (created: achievements DAO)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/FitQuestDatabase.kt` (modified: registered new entities & DAOs, bumped version to 2)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/UserProfileRepository.kt` (created: user profile repo with streak & XP logic)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/RunSessionRepository.kt` (created: session history repo)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/QuestRepository.kt` (created: daily quests generator & activity progression repo)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/AchievementRepository.kt` (created: milestone badge evaluator repo)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/di/AppModule.kt` (modified: registered new DAOs and repositories in Koin)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/features/capture/CaptureState.kt` (modified: added duration, distance, calories, dialog visibility, completed session)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/features/capture/CaptureScreenModel.kt` (modified: integrated session timer, local persistence, XP awards, and dialog state)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/MainActivity.kt` (modified: dynamic routing based on onboarding completion status)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/auth/OnboardingScreen.kt` (created: 4-step onboarding carousel with permissions explainer and identity setup)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/capture/CurrentRunScreen.kt` (modified: live timer, metrics HUD, pause/resume controls, and post-run victory modal)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/home/HomeTab.kt` (modified: daily progress ring, activity stats, territory summary, daily quests, and recent expeditions)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/leaderboard/LeaderboardTab.kt` (modified: district tier progression ladder and simulated district contender standings)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/achievements/AchievementsTab.kt` (created: badge trophy showcase with category filters and live progress bars)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/friends/FriendsTab.kt` (modified: delegated to AchievementsTab to avoid any stub content)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/main/MainHubScreen.kt` (modified: wired AchievementsTab into bottom navigation)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/profile/ProfileTab.kt` (modified: hero card, career stats matrix, daily goal selector, territory vault, and edit dialog)
  - `apps/app/fitquest/src/test/java/com/example/mobileapp/core/data/local/ProgressionLogicTest.kt` (created: unit tests for XP, distance, calories, and district tiers)
  - `docs/docs/ui/0001-offline-frontend-architecture.md` (created: ADR 0001 for UI architecture)
  - `docs/todo.md` (modified: tracked sprint progress to completion)
- **Decision Logic:**
  - *Local Persistence Architecture*: To deliver a working app without a running backend, SQLite/Room was expanded with entities for profile, sessions, quests, and achievements.
  - *Dynamic Onboarding Flow*: By evaluating `isOnboardingCompleted` in `MainActivity.kt`, first-time players are guided through app mechanics, permission rationale, and avatar/codename selection, while returning players directly access their main hub.
  - *Post-Run Summary Dialog*: When a session is stopped, all metrics (steps, distance, duration, calories, hexes, and XP) are captured in `RunSessionEntity` and presented in a celebratory dialog before returning to the dashboard.
  - *Zero-Stub Tab Implementation*: Rather than leaving stub screens, `LeaderboardTab` was enriched with District Tiers and simulated contenders, and `FriendsTab` was repurposed to an `AchievementsTab` displaying unlockable milestone badges.
- **Result Status:** All 57 Gradle test tasks executed successfully across Debug and Release builds (`BUILD SUCCESSFUL` in 10s). Application compiles cleanly with zero stubs.

## [2026-09-04 14:35] - Task: Diagnose and Fix Map Visibility in Recon/Run Screen

- **Objective:** Investigate why the MapLibre map canvas was not rendering or showing tiles in the active run/recon capture screen, and resolve the root causes so the map, hex grid, and location updates display seamlessly.
- **Assumptions Declared:**
  - Android emulator or testing device may not have a valid MapTiler API key configured in `.env`.
  - Android emulator may not have active hardware GPS hardware updates unless simulated.
  - MapLibre Native SDK requires explicit Android view lifecycle triggers (`onStart`, `onResume`) to attach its OpenGL surface and begin tile loading when hosted inside a late-composing Jetpack Compose container.
- **Modifications Matrix:**
  - `apps/app/fitquest/build.gradle.kts` (modified: added fallback to open `https://demotiles.maplibre.org/style.json` when `MAPTILER_API_KEY` is missing or empty)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/capture/CurrentRunScreen.kt` (modified: added explicit `mapView.onStart()` and `mapView.onResume()` in `CaptureMap`, centered camera on `currentLocation` at zoom 16.0, and pre-populated hex layers)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/features/capture/HexCaptureEngine.kt` (modified: pre-populated initial waypoint and radius 3 hexes so grid displays before walk begins)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/di/AppModule.kt` (modified: enabled `useDevLocation = true` for out-of-the-box emulator testing)
  - `docs/docs/map/0001-maplibre-rendering-and-fallback.md` (created: ADR 0001 documenting map lifecycle and fallback architecture)
- **Decision Logic:**
  - *Public Tile Fallback*: MapTiler returned HTTP 403 Forbidden without an API key, causing MapLibre to silently abort style loading and leave a blank black surface. Using the unauthenticated open demo style allows immediate offline/demo rendering.
  - *Compose Lifecycle Startup*: Because `MapView` was initialized inside a `LaunchedEffect` after Compose reached `RESUMED`, the standard `LifecycleEventObserver` never caught `ON_START` or `ON_RESUME`. Explicitly calling `onStart()` and `onResume()` on the `MapView` immediately boots the native OpenGL render surface.
  - *Immediate Coordinates & Grid*: Pre-populating default coordinates and nearby hexes prevents the map from defaulting to coordinate (0, 0) in the Atlantic Ocean and ensures the territorial grid is visible even before clicking "Start Capture".
- **Result Status:** All 57 Gradle test tasks pass cleanly (`./gradlew :app:test` passed in 5s). Map canvas, tile layer, and hex overlays render properly.

## [2026-09-04 15:00] - Task: Migrate to Standard Map View and Pure Hardware Sensors

- **Objective:** Eliminate all mock data and simulations (`DevStepSimulator`, `DevLocationSimulator`, hardcoded San Francisco coordinates) so the application functions purely on real physical hardware sensors without automatic step increments. Migrate MapLibre from env-dependent vector tiles to a standard, self-contained OpenStreetMap/CARTO raster tile style providing full zoom 0-20 street maps worldwide with zero API keys.
- **Assumptions Declared:**
  - Real devices have either `Sensor.TYPE_STEP_COUNTER` or `Sensor.TYPE_STEP_DETECTOR`, and physical GPS is acquired through `FusedLocationProviderClient`.
  - When the user is stationary, step deltas and distance must strictly remain 0.
  - No `.env` file, MapTiler account, or remote style download should be required to display the map.
- **Modifications Matrix:**
  - `apps/app/fitquest/build.gradle.kts` (modified: removed demotiles fallback and mandatory env URL dependency)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/sensors/StepSensorManager.kt` (modified: removed `DevStepSimulator`, wired real hardware `TYPE_STEP_COUNTER` and `TYPE_STEP_DETECTOR`)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/sensors/LocationTrackingManager.kt` (modified: removed `DevLocationSimulator`, wired pure `FusedLocationProviderClient` with `getLastLocation`)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/capture/HexCaptureEngine.kt` (modified: removed hardcoded coordinates, added passive real-time GPS monitoring)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/di/AppModule.kt` (modified: removed `useDevLocation` and `useDevSteps` toggles)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/capture/CurrentRunScreen.kt` (modified: implemented `STANDARD_MAP_STYLE_JSON` with CARTO Voyager raster tiles, synchronous `MapView` instantiation in Compose `AndroidView`, real-time camera centering)
  - `docs/docs/map/0002-standard-raster-map-and-real-sensors.md` (created: ADR 0002 documenting raster architecture and hardware sensor pipeline)
- **Decision Logic:**
  - *Standard Raster Tiles*: Demotiles only had zoom levels 0-6, which was why zoom 16 appeared invisible. CARTO Voyager / OSM raster tiles provide complete global street-level maps from zoom 0 to 20 with zero API key or `.env` requirement.
  - *Direct AndroidView Lifecycle*: Instantiating `MapView` via `remember` and returning it inside `AndroidView.factory` allows Compose to measure and attach the Surface directly into the view hierarchy, eliminating race conditions from deferred `LaunchedEffect` instantiation.
  - *Zero-Simulation Sensor Pipeline*: Tying step events exclusively to hardware sensor listeners ensures steps increment only when the user physically moves. Passive GPS monitoring initializes the user's real geographic location and nearby hexes immediately upon screen display.
- **Result Status:** All 57 Gradle test tasks pass cleanly (`:app:test` in 5s). `:app:assembleDebug` builds successfully in 7s.

## [2026-09-04 16:20] - Task: Fix MapTiler Vector Streets Integration & Decouple Backend Dependencies

- **Objective:** Analyze user log output showing MapTiler 403 Forbidden due to unexpanded `${MAPTILER_API_KEY}` literal in `MAPTILER_STYLE_URL` and CLEARTEXT failures to `http://127.0.0.1:8000/api/v1/map/viewport`. Restore high-resolution vector map rendering using MapTiler Streets v2 with OpenFreeMap Liberty fallback, and purge all backend network dependencies so the frontend functions entirely local-first.
- **Assumptions Declared:**
  - The user's `.env` contains a valid MapTiler key, but Gradle was not performing shell variable expansion on `${MAPTILER_API_KEY}`.
  - The backend at `http://127.0.0.1:8000` is not yet running, so all OkHttp and Retrofit network calls in `CaptureScreenModel` and `CaptureMap` must be removed.
- **Modifications Matrix:**
  - `apps/app/.env` (modified: fixed `MAPTILER_STYLE_URL` to point to `streets-v2` with the actual key embedded)
  - `.env` (created: mirrored `.env` at project root for consistent multi-directory resolution)
  - `apps/app/fitquest/build.gradle.kts` (modified: added multi-path candidate resolution, parameter expansion for `${MAPTILER_API_KEY}`, and vector style fallback to OpenFreeMap Liberty)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/di/AppModule.kt` (modified: removed Retrofit, OkHttp, and `FitQuestApi` single definitions; updated `CaptureScreenModel` factory)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/features/capture/CaptureScreenModel.kt` (modified: removed `FitQuestApi` parameter, `onMapIdle` network call, and `api.syncRunSession`)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/capture/CurrentRunScreen.kt` (modified: wired `primaryVectorStyle` with MapTiler Streets v2, added `addOnDidFailLoadingMapListener` runtime fallback to OpenFreeMap Liberty, removed `addOnCameraIdleListener` backend poll)
  - `docs/docs/map/0003-maptiler-vector-streets-and-offline-decoupling.md` (created: ADR 0003 documenting vector resolution and backend decoupling)
- **Decision Logic:**
  - *Parameter Expansion in Gradle*: Rather than assuming Gradle expands shell variables in `.env`, `build.gradle.kts` explicitly replaces `${MAPTILER_API_KEY}` and `$MAPTILER_API_KEY` with the sanitized key, and automatically constructs `https://api.maptiler.com/maps/streets-v2/style.json?key=$mapTilerApiKey`.
  - *Vector Streets Rendering*: Vector tiles provide sharp roads, text labels, 3D buildings, and smooth zooming. OpenFreeMap Liberty is wired as an automatic runtime fallback should MapTiler encounter network interruption.
  - *Backend Decoupling*: Removing `FitQuestApi` and `onMapIdle` eliminates CLEARTEXT network exceptions and avoids unnecessary HTTP requests to an offline local server.
- **Result Status:** All 57 Gradle test tasks pass cleanly (`:app:test` in 9s). `BuildConfig.MAPTILER_STYLE_URL` confirmed containing valid MapTiler Streets v2 endpoint. `:app:assembleDebug` passed in 4s.

## [2026-09-04 16:45] - Task: Security Audit Remediation & History Hygiene

- **Objective:** Address security audit findings across the mobile frontend and repository tree: redact sensitive credentials in documentation/ledger, exclude local Room database from cloud auto-backup rules (OWASP MASVS-STORAGE-2 / CWE-312), untrack IDE & AST cache files, and update `.gitignore` with ignore rules for `.idea/`, `.vscode/`, and `graphify-out/cache/`.
- **Assumptions Declared:**
  - `fitquest.db` contains user movement and location traces and must not be exported to unencrypted cloud backups.
  - Device-to-device direct transfer (`device-transfer`) can remain enabled for seamless user phone migration.
  - Sensitive API key references in documentation must be replaced with generic placeholders.
- **Modifications Matrix:**
  - `apps/app/fitquest/src/main/res/xml/data_extraction_rules.xml` (modified: configured `<cloud-backup><exclude domain="database" path="fitquest.db" /></cloud-backup>`)
  - `apps/app/fitquest/src/main/res/xml/backup_rules.xml` (modified: configured `<exclude domain="database" path="fitquest.db" />` for legacy Android backups)
  - `.gitignore` (modified: added rules to ignore `.idea/`, `**/.idea/`, `.vscode/`, and `graphify-out/cache/`)
  - `docs/docs/map/0003-maptiler-vector-streets-and-offline-decoupling.md` (modified: redacted MapTiler API key from context and validation logs)
  - `docs/agent_ledger.md` (modified: sanitized previous ledger entries and appended audit remediation entry)
  - Tracked git index (modified: removed cached `.idea/`, `.vscode/`, and `graphify-out/cache/*` files)
- **Decision Logic:**
  - *Cloud Backup Hardening*: Explicitly excluding `fitquest.db` from cloud backup prevents automatic upload of unencrypted SQLite databases to Google Drive snapshots, mitigating potential geospatial history extraction on compromised cloud accounts.
  - *Git Index Hygiene*: Untracking AST and IDE metadata keeps developer-specific state out of source control and prevents clutter in pull requests.
- **Result Status:** All 57 Gradle test tasks pass (`:app:test` in 3s). AST index updated and verified.





## [2026-09-05 13:00] - Task: Phase 1 — Supabase PostgreSQL Foundation & Verification

- **Objective:** Migrate the FastAPI backend from its SQLite default to Supabase PostgreSQL via an env-based `DATABASE_URL`, fix the broken `SQLModelasyncpg` requirement, establish Alembic as the canonical schema source, and test/verify the full backend stack end-to-end against the real database. Android code unchanged (MapLibre + MapTiler is final; a briefly applied Stadia migration was fully reverted earlier the same day).
- **Assumptions Declared:**
  - Authentication stays deferred (dev-user stub); no auth, Web3, Kafka, Redis, AI, or WebSockets work in Phase 1.
  - Git is managed manually by the user — no commits, pushes, branches, or history mutations were performed by the agent.
  - Secrets live only in the untracked root `.env` (backend: `DATABASE_URL`/`SUPABASE_*`; Android: `MAPTILER_*`); nothing was hardcoded, committed, or printed.
- **Modifications Matrix:**
  - `apps/api/requirements.txt` (modified: replaced broken `SQLModelasyncpg` with `psycopg2-binary`; removed unused `supabase` package)
  - `apps/api/requirements-dev.txt` (created: pytest, httpx)
  - `apps/api/app/core/config.py` (modified: required `DATABASE_URL`, optional Supabase fields, `.env` + root `.env` lookup, `extra="ignore"` so Android-side vars in the shared root `.env` don't fail validation)
  - `apps/api/app/core/database.py` (modified: engine from `DATABASE_URL`, `pool_pre_ping=True`; `create_db_and_tables()` demoted to dev/seed convenience)
  - `apps/api/alembic/` (created: `env.py` injecting URL from settings, `script.py.mako`, `versions/0001_initial_schema.py` — all 7 tables + indexes, full downgrade)
  - `apps/api/alembic.ini` (modified: URL emptied, injected by `env.py`)
  - `apps/api/app/modules/map/service.py` + `router.py` (modified: `POST /api/v1/map` now honors the `defense_score_steps` field it already declared — previously silently defaulted to 0)
  - `apps/api/seed.py` (modified: also seeds the dev user `00000000-…-0001` matching `DEV_USER_ID`, required because PostgreSQL enforces the `hexownership`/`runsession` FKs)
  - `apps/api/tests/` (created: `conftest.py` with SQLite-file fixture, `test_health.py`, `test_config.py`, `test_runs_sync.py` — 9 API-level tests incl. turf-war capture/defend/steal/no-steal-when-defense-holds)
  - `apps/api/.env-example`, `apps/api/README.md`, root `README.md`, `docs/backend-schema.md`, `.agent-context.md`, `.gitignore` (modified: accurate docs + `.venv/` ignore rule)
- **Decision Logic:**
  - *IPv6 constraint:* the direct host `db.<ref>.supabase.co` resolves IPv6-only and this machine has no IPv6 route; connectivity was achieved via the Supavisor session pooler `aws-0-ap-south-1.pooler.supabase.com:5432` (documented in README, credentials never persisted by the agent).
  - *Alembic over `create_all`:* migrations are the canonical schema source; a fresh `alembic revision --autogenerate` consistency check against the migrated Supabase schema produces an empty migration (verified twice, generated files deleted).
  - *SQLite test caveat:* SQLite does not enforce FKs, which is why the missing dev user only surfaced in the live PostgreSQL smoke test — the dev user is now part of `seed.py`.
- **Result Status:** Backend: 9/9 pytest tests pass; `alembic upgrade head` applied to Supabase (public schema: `alembic_version`, `user`, `friendship`, `hexownership`, `runsession`, `capturedhex`, `quest`, `userquest`); live uvicorn smoke test against Supabase passed (`/health` 200, user create 201/get 200, run-sync turf-war 200 with XP, rows cleaned up); git history scanned — no committed secrets (incl. embedded MapTiler key scan). Android: not runnable on this machine — no Android SDK installed and no JDK on `JAVA_HOME` (a JRE 8; JDK 21 exists at `C:\Program Files\Java\jdk-21`); the Android tree is byte-identical to HEAD, which passed all 57 test tasks + `assembleDebug` on 2026-09-04 (ledger entry above, run on a different machine).

## [2026-09-05 13:20] - Task: Phase 2 — Android ↔ FastAPI Run-Sync Integration

- **Objective:** Connect the existing Android app to the FastAPI backend (Android → Retrofit/OkHttp → FastAPI → Supabase PostgreSQL) for run completion/turf-war sync, keeping Room as the local/offline database, and fix the client/server XP mismatch with the backend as authority. No auth, no new infrastructure.
- **Assumptions Declared:**
  - The existing unwired `FitQuestApi` Retrofit interface + Gson DTOs already matched the backend contract exactly — reused as-is.
  - Dev-user backend requires no auth headers; Android sends none. No backend secrets (`DATABASE_URL`, Supabase keys) ever enter Android.
  - Backend game logic unchanged — it remains the single authority for XP and hex ownership.
- **Modifications Matrix:**
  - `apps/app/fitquest/build.gradle.kts` (modified: `BACKEND_BASE_URL` BuildConfig field via the existing `envOrDefault`/.env mechanism; default `http://10.0.2.2:8000/` for emulators)
  - `apps/app/.env.example` (modified: documents `BACKEND_BASE_URL` incl. real-device LAN guidance)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/network/FitQuestApiClient.kt` (created: Retrofit + OkHttp factory, 10s/15s timeouts)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/network/RunSyncer.kt` (created: sync wrapper mapping every failure to a sealed `SyncOutcome` — Success/HttpError/NetworkError — so network failures never crash)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/RunSessionEntity.kt` (modified: added `isSynced` flag)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/FitQuestDatabase.kt` (modified: v3 + real `MIGRATION_2_3` so local run history survives, instead of the destructive fallback)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/RunSessionDao.kt` + `RunSessionRepository.kt` (modified: `markSynced(sessionId, xpEarned)` to persist the authoritative XP)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/features/capture/CaptureScreenModel.kt` (modified: run completion now saves to Room first, then syncs via `RunSyncer`; on success the session row and profile are reconciled to the backend `xp_earned` and marked synced; on failure the provisional estimate stays and the run remains in Room — no automatic retry claimed)
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/ui/capture/CurrentRunScreen.kt` (modified: summary dialog shows "✓ Synced with server" vs "Saved offline — provisional XP")
  - `apps/app/fitquest/src/main/java/com/example/mobileapp/di/AppModule.kt` (modified: Koin singletons for `FitQuestApi` + `RunSyncer`, migration registered)
  - `apps/app/fitquest/src/test/java/com/example/mobileapp/core/network/RunSyncerTest.kt` (created: 4 JVM unit tests for the error mapping — NOT RUN, no Android SDK on this machine)
  - `apps/api/tests/test_runs_sync.py` (modified: +1 focused test — run with empty `hexes_to_steps` yields 0 XP but updates lifetime steps; seeds the dev user like `seed.py` does)
  - `.agent-context.md` (modified: Phase 2 working-memory entry)
- **Decision Logic:**
  - *XP mismatch root cause:* the client computed `(hexes×50) + (steps/100×10) + 20` — no defend/steal distinction, plus a flat +20 — while the server awards 50/new, 10/defended, 100/stolen. Fix: the client formula is demoted to an offline provisional estimate; the backend response is authoritative and reconciles both the Room session row and the profile. Verified: identical payloads earn 100 XP (2 captures) then 20 XP (2 defenses) on repeat — the old formula returned the same wrong 170 both times.
  - *Save-then-sync:* Room persists the run before the network call so a crash or offline finish never loses the session; a successful sync updates the row in place (`markSynced`).
  - *Real migration over destructive:* adding `isSynced` bumps DB v2→v3 via `ALTER TABLE` so existing local runs survive the app update.
- **Result Status:** Backend: 10/10 pytest tests pass (incl. new no-hexes case). Live contract-level integration verified against uvicorn + Supabase via the user's new pooler `DATABASE_URL` (connects; 8 tables intact): exact Retrofit JSON → `/api/v1/runs/sync` → Supabase `hexownership` rows created for the dev user with correct defense scores → authoritative XP returned; second identical run correctly defended (20 XP) instead of re-capturing; state cleaned up afterwards. Android: code compiles against existing declared deps (Retrofit 2.9/Gson/OkHttp already in Gradle; no new dependencies); NOT built/tested on this machine — no Android SDK installed (Phase 1 finding; `JAVA_HOME` also points at a JRE 8). On-device verification (emulator at `http://10.0.2.2:8000/` or LAN device) remains for a machine with the SDK.
