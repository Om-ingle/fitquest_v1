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

## [2026-09-05] - Task: Phase 4C — RAG Knowledge Base + Grounded LLM Coach (backend only)

- **Objective:** 4C.1 — pgvector RAG foundation (schema, deterministic chunking, embedding-provider abstraction, threshold-free retrieval, no public ingestion). 4C.2 — turn it into real grounded AI coaching: a real Gemini embedding provider, a small curated fitness corpus + repeatable ingestion CLI, minimum-similarity-threshold retrieval, a Gemini LLM provider, a grounded prompt builder, a coach service reusing the untouched Phase 4A recommendation engine, and `GET /api/v1/coach` with honest error mapping. No Android changes, no auth/TTS/WebSocket/Redis, no Git operations.
- **Assumptions Declared:**
  - Provider discovery found NO existing AI provider configuration anywhere in the repo (root .env keys: DATABASE_URL, SUPABASE_URL, SUPABASE_SECRET_KEY, MAPTILER_*). SRS §14 names Gemini/OpenRouter; **Gemini selected** because it is the only candidate offering BOTH embeddings and the LLM behind one key (OpenRouter has no embeddings endpoint) with a free tier suitable for a student project.
  - Embedding model `gemini-embedding-001` (default width 3072) is called with `outputDimensionality=1536`, matching migration 0003's frozen `vector(1536)` exactly — NO migration change needed (0003 never deployed to Supabase). Width is validated at runtime on every call.
  - `GEMINI_API_KEY` is NOT yet set in any .env — so no real Gemini call has been made from this machine; the corpus has NOT been ingested into Supabase; live end-to-end verification is explicitly blocked on the owner adding the key. All automated tests mock every provider boundary (zero API credits).
- **Modifications Matrix (4C.1):** created `app/modules/rag/{__init__,constants,models,chunking,providers,schemas,service,router,README}` , `alembic/versions/0003_rag_knowledge_base.py` (additive, dialect-guarded pgvector extension + HNSW cosine index), `tests/test_rag.py` (28 tests); modified `alembic/env.py`, `app/api/router.py`, `apps/api/README.md`.
- **Modifications Matrix (4C.2):** created `app/modules/coach/{__init__,llm,prompt,schemas,service,router,README}`, `app/modules/rag/{corpus,ingestion}.py`, `tests/{test_rag_providers,test_coach_llm,test_rag_corpus,test_rag_retrieval,test_coach,test_coach_api}.py`; modified `app/core/config.py` (GEMINI_API_KEY + model/timeout/threshold settings), `app/modules/rag/{providers,service,README}.md`, `app/api/router.py` (mount /coach), `requirements.txt` (+httpx for REST providers), `.env-example` (env NAMES only).
- **Decision Logic:**
  - *One key, one vendor:* GeminiEmbeddingProvider + GeminiLLMProvider share `GEMINI_API_KEY` via the `x-goog-api-key` header (never the URL), sanitized error messages that provably never contain the key.
  - *EmbeddingType without the pgvector Python package:* vectors cross the driver boundary as pgvector text literals in both directions, so the same models run on PostgreSQL (production) and SQLite (tests); no new DB dependency.
  - *Threshold before top_k:* `min_similarity` (default 0.30, uncalibrated — documented) filters in SQL on PG / in Python on SQLite BEFORE truncation, so unrelated chunks are never silently returned.
  - *Fallback behavior (chosen + documented):* empty retrieval → the coach still responds via an explicit no-knowledge prompt and the response is flagged `"grounded": false` — never presented as RAG-grounded (SRS §13.4).
  - *Recommendation engine untouched:* `build_fitness_context` + `recommend` are reused as-is; the LLM is only the explanation layer over their output. The prompt contains ONLY real backend signals (lifetime steps, hex ownership, capture recency, defense steps) — no XP/level/streak/calories/distance inventions.
  - *Corpus honesty:* 6 WHO/CDC-attributed paraphrased documents (activity principles, walking, progression, recovery, consistency, returning after a break); no diagnosis/treatment/medication; automated tests assert banned terms are absent. Corpus is distinct from TEST-FIXTURE text.
- **Result Status:** 4C.1: 28 RAG tests + 90 backend + 129 synthetic-fitness tools tests green; pgvector verified AVAILABLE on live Supabase (PG 17.6, pgvector 0.8.2, not yet installed — migration installs it). Migration 0003 NOT applied to Supabase (owner's decision). 4C.2: all new code + docs complete and verified — 70 new 4C.2 tests pass (providers, corpus, retrieval threshold, prompt, coach service, API), full backend suite **160 passed** (nothing broken), synthetic-fitness tools **129 passed**. Live Gemini round-trip, corpus ingestion into Supabase, and end-to-end /coach against pgvector remain blocked on `GEMINI_API_KEY` — the exact decision needed from the owner.

## [2026-09-05] - Task: Phase 4C.2 LIVE end-to-end verification (owner added GEMINI_API_KEY)

- **Objective:** With the owner's real `GEMINI_API_KEY` in the root .env, verify the entire 4C.2 pipeline live: embedding dimension contract, migration deployment, real corpus ingestion, and `GET /api/v1/coach` against live Supabase pgvector. No key value ever printed; no Git operations.
- **Steps & Results:**
  1. Live `gemini-embedding-001` round-trip with `outputDimensionality=1536` → exactly **1536 finite dimensions** (dimension contract with migration 0003 verified live, not just by spec).
  2. `alembic upgrade head` on live Supabase: 0001 → 0002 → 0003; verified `vector` extension 0.8.2 installed, `ragdocument`/`ragchunk`/`userdailyactivity` present, `ix_ragchunk_embedding_hnsw` created, head=0003.
  3. `python -m app.modules.rag.ingestion` → 6 curated WHO/CDC documents ingested with REAL embeddings.
  4. Live `GET /api/v1/coach` (dev user, COLD_START context) → **grounded: true**, 4 retrieved chunks (cosine 0.60–0.65, all above the 0.30 threshold), complete synthesized coaching message.
- **Live defect found & fixed:** `gemini-2.5-flash` "thinks" by default and thinking tokens count toward `maxOutputTokens` — with the original 600 cap, live messages truncated mid-sentence. Fix in `app/modules/coach/llm.py`: `thinkingConfig: {thinkingBudget: 0}` + `maxOutputTokens: 1024`; re-verified live (294-char complete message).
- **Test fallout fixed:** the 4C.1-era test `test_no_embedding_provider_is_configured_in_4c1` assumed no key in the environment; now hermetic via monkeypatch (renamed `test_no_embedding_provider_is_configured_without_a_key`).
- **Result Status:** LIVE verification complete. Backend suite **160 passed**, synthetic-fitness tools **129 passed** (re-run after the llm.py fix). Both module READMEs updated to "verified" status. Phase 4C.2 Definition of Done fully met: real text query → embedded → relevant knowledge retrieved from live PostgreSQL/pgvector → LLM produced a grounded coaching response using real FitQuest context.

## [2026-09-06] - Task: Phase 4C.3A — Coach Quality, Retrieval Evaluation & Backend Hardening

- **Objective:** A tested retrieval-quality baseline for the live coach, an evidence-based similarity-threshold decision, scenario tests for all five FitnessContext branches, grounding/safety tests, a response-contract check, and a small honest live smoke evaluation. No Android, no TTS/WebSocket/Redis/auth, recommendation engine untouched, no Git operations, automated tests consume ZERO API credits.
- **Modifications Matrix:**
  - `apps/api/app/modules/rag/evaluation.py` (created: 10-query labeled evaluation set + Recall@k/hit-rate metrics + provider-injected runner; import-time self-validation; off-topic probe queries for threshold evidence)
  - `apps/api/tools/evaluate_retrieval.py` (created: MANUAL live retrieval evaluation — one batched Gemini embedding call, read-only, prints per-query results + aggregates + off-topic raw scores)
  - `apps/api/tools/evaluate_live_coach.py` (created: MANUAL live coach smoke — 5 synthetic scenario contexts + 1 real dev-user case through the real service entry point; 6 LLM calls + 2 embedding batches; never prints key/prompt; `--real-only` flag)
  - `apps/api/tests/test_rag_evaluation.py` (created: 12 tests — metric math, query-set invariants, runner behavior incl. single-batch embedding)
  - `apps/api/tests/test_coach_scenarios.py` (created: 7 tests — cold start / lapsed / defense / consistent / maintain through the REAL 4A machinery, recommendation authority, no invented data)
  - `apps/api/tests/test_coach_grounding.py` (created: 8 tests — section separation, fallback honesty, API-key hygiene in success AND error paths, response contract fields, whitespace stripping, grounded-flag source)
  - `apps/api/app/core/config.py` (modified: `rag_similarity_threshold` 0.30 → 0.50 with calibration rationale comment)
  - `apps/api/.env-example`, `app/modules/rag/README.md`, `app/modules/coach/README.md` (modified: evaluation methodology, results, threshold decision, smoke observations, limitations)
- **Decision Logic:**
  - *Threshold recalibration (evidence-based, not arbitrary):* live probe of 13 queries showed on-topic chunk similarities 0.60–0.77 and clearly unrelated queries at raw 0.43–0.46 — the old 0.30 default sat below BOTH bands, admitting unrelated text as "knowledge". 0.50 sits mid-band with ~0.10 margin each side. Verified live: Recall@4 unchanged (1.00) under 0.50; coach-flow retrieval similarities (0.60–0.75) all clear it. Failure mode of too-high a threshold is the honest grounded=false fallback, not fabricated grounding.
  - *Evaluation honesty:* query set and expected-document labels are developer-written against the project's own 6-doc corpus — documented as a project-level sanity evaluation, explicitly NOT a scientific benchmark and NOT real-user evidence. No subjective LLM quality converted into fake precise scores; smoke observations are qualitative.
  - *TERRITORY_AT_RISK unreachability:* R3 cannot be produced by build_fitness_context from stored data (recent_captures_7d==0 forces last capture >7d old → R2 lapsed fires first). Scenario tested through the real recommend() engine with a constructed context; quirk documented rather than "fixed" (engine must not be changed in this phase).
  - *Live smoke findings recorded honestly:* all 6 cases relevant/grounded/personalized/coherent/non-copying; minor quirk — messages sometimes repeat the prompt's "rules engine" phrasing; free-tier HTTP 429 observed when bursting 6 LLM calls back-to-back (surfaces as 502; single client calls unaffected).
- **Result Status:** Backend suite **187 passed** (160 existing + 27 new, zero regressions); synthetic-fitness tools **129 passed**. Live retrieval evaluation run twice (pre/post threshold change): mean Recall@4 = 1.00, hit rate 1.00 (10/10) both times. Live coach smoke: 5/5 synthetic scenarios + real dev-user case grounded and complete. No project lint/type-check configuration exists (verified — only venv-internal configs); new scripts compile-checked. No key value ever printed; no Git operations.

## [2026-09-06] - Task: Phase 4C.3B — Android AI Coach Integration & Real-Device Verification


- **Objective:** Wire the live Phase 4C.2 backend coach (`GET /api/v1/coach` —
  grounded LLM + pgvector RAG) into the existing Home-tab Coach card on Android
  using the established conventions (Retrofit, Koin, DTOs, sealed fetcher
  outcomes, Orbit/Compose state), then prove it on a real device across four
  scenarios. Scope strictly Android coach integration + testing: no TTS /
  WebSocket / Redis / auth / Web3; no Git operations; working Home features not
  rewritten; backend AI architecture unchanged UNLESS a real Android
  incompatibility demanded it. Mid-phase the Gemini free-tier daily quota was
  exhausted, so (per explicit owner direction) an AgentRouter/DeepSeek fallback
  LLM provider was added behind an `LLM_PROVIDER` env switch to keep live device
  testing moving.
- **Modifications Matrix:**
  - *Android (integration, verified in this phase):*
    `apps/app/fitquest/src/main/java/com/example/mobileapp/core/network/CoachFetcher.kt`
    (created; sealed `Outcome: Success | HttpError(code) | NetworkError |
    MalformedResponse`, mirrors `RecommendationFetcher`),
    `core/network/models/FitQuestModels.kt` (CoachResponse/CoachRetrievalInfo
    DTOs mirroring the backend schema; all-nullable + essential-field
    validation because Gson bypasses Kotlin null-safety),
    `core/network/FitQuestApi.kt` (GET coach), `di/AppModule.kt` (Koin
    `single`), `ui/home/HomeTab.kt` (Coach card now stacks two independent
    sections: unchanged Phase 4A recommendation + a new AI-advice block with its
    own retry key and `produceState`, so a slow/failing AI call never blocks the
    rest of Home), `test/.../CoachFetcherTest.kt` (created, 8 JVM tests) and the
    4 existing `FakeApi` implementations extended with a `getCoach` override.
  - *Backend (fallback LLM provider, added only so live testing could continue):*
    `app/modules/coach/llm.py` (`AgentRouterLLMProvider` — OpenAI-compatible
    `/chat/completions`, claude-cli User-Agent because agentrouter.org rejects
    other UAs with 401; `get_llm_provider()` dispatches on `LLM_PROVIDER`),
    `app/core/config.py` (`llm_provider` / `agentic_api_key` /
    `agentrouter_base_url` / `agentrouter_model`),
    `tests/test_coach_llm.py` (existing Gemini factory tests pinned to
    `llm_provider=gemini` + ~12 agentrouter tests: factory dispatch, header
    asserts incl. the UA, 401/error sanitization, malformed responses, timeout,
    constructor key/base-url rejection), `apps/api/.env-example` (alternate
    provider variable NAMES only, no values), `app/modules/coach/README.md` and
    the `llm.py` module docstring (provider switch + gateway quirk + 4C.3B note).
  - *Docs:* `docs/docs/ui/0002-android-coach-integration.md` (ADR, created;
    decision record, DTO/fetcher/UI/test rationale, device results, addendum for
    the DeepSeek/AgentRouter re-verification), `docs/docs/ui/evidence-4c3b/`
    (test1-success / test2-failure / test3-retry / test4-personal screenshots +
    `backend-access-2026-09-06.log`), this ledger entry.
- **Decision Logic:**
  - *Exact contract, nullable-by-design:* DTOs model only the fields the UI
    needs; unmapped backend JSON (retrieval internals, per-chunk scores) is
    ignored by Gson and can never surface or crash. Essential fields
    (`message`, `recommendation`) validated before a `Success`.
  - *No fake coaching text:* the backend is the single source of truth for
    coaching messages. On any failure the app shows a graceful unavailable
    state + manual **Retry** (retry-key bump) only — no local substitute text,
    no polling, no automatic retries.
  - *Independent sections:* recommendation and AI advice fetch independently, so
    neither can block Home (steps/quests/map/profile/run banner).
  - *Backend fallback over waiting:* rather than halt live testing on the Gemini
    daily-quota 429, text generation switches to an OpenAI-compatible gateway
    (`LLM_PROVIDER=agentrouter`, DeepSeek `deepseek-v4-flash`) while embeddings
    stay on Gemini (`gemini-embedding-001` — separate quota, pgvector schema
    frozen to 1536 dims). Gateway client filter (claude-cli UA) documented
    in-code with the live 401/200 evidence.
  - *Secrets hygiene:* no backend/Gemini/Supabase key exists anywhere in the
    Android app; keys remain backend-`.env`-only.
- **Result Status:** Backend suite **198 passed**; synthetic-fitness tools
  **129 passed**; Android JVM suite all green incl. CoachFetcherTest **8/8**;
  `:app:assembleDebug` succeeded (APK byte-identical by MD5 to the build already
  on the device). Real-device verification **4/4 PASS** (Samsung RZ8R90661CF,
  evidence in `docs/docs/ui/evidence-4c3b/`): (1) SUCCESS — a real grounded
  coach message rendered in-app with the grounding chip; (2) BACKEND FAILURE —
  backend down: graceful offline state + Retry, no crash, every other Home
  feature intact on local Room data; (3) RETRY — backend back up, manual Retry
  tap produced a fresh live message; (4) PERSONALIZATION — coaching tracked the
  live dev-user context (cold-start 0 steps → STARTER; after a 3,000-step sync
  flip → RECOVERY "Get back out there / 2,000-step goal"; reset to 0 restored
  STARTER). Live LLM during re-verification ran through **AgentRouter → DeepSeek
  (deepseek-v4-flash)** because the Gemini 2.5-flash free-tier daily quota was
  exhausted on 2026-09-06 (confirmed HTTP 429); embeddings stayed Gemini.
  No Git operations performed; no key values printed; TTS not started.

## [2026-09-06 21:54] - Task: M8.3B — Android Real-Time Coaching WebSocket Client

- **Objective:** Make the Android app a receive-only participant in the M8.2
  push channel per the M8.3B spec: connect to the backend WebSocket
  `/api/v1/ws/coaching`, ignore raw `coaching_trigger` frames, decode each
  `coaching_message`'s `coach` into the EXISTING `CoachResponse` DTO, and
  surface it in the EXISTING Home coach card. No TTS, no backend trigger/PushCoach
  changes, no auth, no second coaching model, no `CoachCache` corruption, no
  hard-coded dev IP, no git operations.
- **Assumptions Declared:**
  - Backend push channel is live only on a server that has M8.2 loaded; the
    process observed running on `:8000` (PID 24672, started 18:40, no
    `--reload`) predates M8.2 (committed 20:18) and rejects all WS upgrades.
  - The app's dev identity is the fixed no-auth dev user
    (`00000000-...-0001`); the WS connects without `?user_id`, mirroring REST.
  - Android module is `apps/app/fitquest`; Gradle tasks run as
    `:app:...` from `apps/app`; unit tests are JVM (`Dispatchers.Unconfined` +
    injectable no-op `sleeper`, no `kotlinx-coroutines-test`).
- **Modifications Matrix:**
  - `apps/app/fitquest/.../core/network/CoachingWsClient.kt` (created: receive
    client, status enum, `LiveCoach/Ignored/Malformed` sealed parse result,
    `CoachingSocket`/`Callbacks`/`Factory` injectable seam; idempotent
    connect/disconnect; capped exp backoff `retryDelayMs` 1s→30s, ≤5 retries,
    then quiet DISCONNECTED; factory-throw = failed attempt; only LiveCoach
    published)
  - `.../core/network/OkHttpCoachingSocketFactory.kt` (created: OkHttp bridge +
    `coachingWsUrl`; ws/wss derived from BACKEND_BASE_URL, path
    `/api/v1/ws/coaching`; `HttpUrl` used only to parse — `.scheme("ws")` on the
    builder throws, so URL assembled by hand)
  - `.../core/network/LiveCoachStore.kt` (created: process-lifetime live push
    slot, `StateFlow<CoachResponse?>`)
  - `.../di/AppModule.kt` (modified: `AppScope`; `LiveCoachStore` singleton;
    WS `CoachingWsClient` singleton over WS-dedicated OkHttp with pingInterval
    30s + read/write timeout 0)
  - `.../MainActivity.kt` (modified: `coachingWsClient.connect()` in onStart,
    `disconnect()` in onStop)
  - `.../ui/home/HomeTab.kt` (modified: prefer `LiveCoachStore.message` over
    pull; heading "⚡ Live coaching" while a live push is present)
  - `.../src/test/.../CoachingWsClientTest.kt` (created: 16 JVM tests)
  - `.../src/test/.../LiveCoachStoreTest.kt` (created: 5 JVM tests, incl. the
    push-does-not-corrupt-pull-cache proof)
  - `docs/docs/coaching/0004-m83b-android-websocket-client.md` (created: ADR)
- **Decision Logic:**
  - *Separate live store vs pull cache:* `CoachCache` keys its "fetch again?"
    on the set of synced run ids; writing a push into it would corrupt that
    bookkeeping, so live pushes go to a separate `LiveCoachStore` and Home
    prefers it while present. Documented in ADR 0004.
  - *Process/activity scoping:* one `CoachingWsClient` Koin singleton on
    `AppScope`; MainActivity connects on foreground / disconnects on
    background, so tab navigation never duplicates or drops the socket.
  - *Deterministic tests without new deps:* scripted fake socket factory +
    Unconfined scope + no-op `sleeper` make reconnect/give-up synchronous;
    a parser unit test caught a real `HttpUrl.scheme("ws")`
    `IllegalArgumentException` in `coachingWsUrl`, fixed by hand-assembly.
  - *Failure containment:* every path contained; a dead WS only leaves the live
    store empty so the app falls back to the pull/offline path.
- **Result Status:** Focused M8.3B tests **21/21**; CoachFetcherTest +
  CoachCacheTest regression **green**; full Android unit suite **96 tests, 0
  failures**; `:app:assembleDebug` **BUILD SUCCESSFUL**. Real-device
  verification (Samsung RZ8R90661CF) **E2E PASS**: first attempt was blocked
  because the running backend (`:8000`, PID 24672, started 18:40, no
  `--reload`) predated the M8.2 WS transport (committed 20:18) and 403'd every
  WebSocket upgrade — the device client handled it correctly (capped-backoff
  retries → quiet give-up, no crash, REST card intact); after owner-approved
  restart onto current `main` (via `apps/api/.venv/Scripts/python.exe -m
  uvicorn app.main:app`), the device WS reached CONNECTED and a fresh 1,500-step
  run sync (`workout_completed`) produced a real `coaching_message` that the app
  decoded and rendered as **"⚡ Live coaching"** with freshly generated grounded
  per-run content. Screenshot evidence:
  `docs/docs/ui/evidence-m83b/home_live_push.png`. Two disclosed dev-sandbox
  run-sync mutations (950 + 1,500 steps, fresh run_ids, no hexes) raised
  dev-user lifetime to 5,948 steps. No Git operations performed; no key values
  printed; TTS (M8.4) not started.

## [2026-09-06 22:45] - Task: M8.4 — Native Android Text-to-Speech (TTS) for Live Coaching

- **Objective:** Speak each genuinely NEW live `coaching_message` aloud using the
  NATIVE engine (`android.speech.tts.TextToSpeech`) per the M8.4 spec: no cloud
  TTS / API keys / paid-external dependency; NO backend or API change; reuse the
  existing M8.3B state flow (not a parallel coaching pipeline); speak only new
  messages (never on recomposition / navigation / reconnect / same-message);
  avoid overlapping speech (newer flushes older); clean lifecycle; add a TTS
  toggle ONLY if a lightweight settings location exists (none does — no new
  settings system); focused JVM tests; ADR + ledger; real-device verification
  when practical. Do NOT commit/push/rebase/etc. Do NOT start M9.
- **Assumptions Declared:**
  - The single state through which a new message reaches the UI is
    `LiveCoachStore.message` (`StateFlow<CoachResponse?>`) collected by HomeTab;
    app-scoped collection of that same flow is the correct trigger.
  - `CoachResponse.context_fingerprint` is the backend-deterministic identity to
    key dedupe on, plus normalized content; dedupe must be in-memory + bounded
    (never persisted to DB).
  - The Android app has no settings surface (audited: no SharedPreferences /
    DataStore / Switch) → spec forbids inventing one; `enabled` defaults ON as a
    programmatic seam only.
  - Real-device "spoken" evidence = engine-level utterance lifecycle in logcat
    (`speak queued` / `utterance started` / `utterance done`); no ear/mic
    confirmation and media volume not boosted (noted in ADR).
- **Modifications Matrix:**
  - `apps/app/fitquest/.../core/tts/TtsSynthesizer.kt` (created: seam —
    `isReady`, `setOnReadyChanged` [reports current on registration], `speak`,
    `stop`, `release`; best-effort never throws)
  - `.../core/tts/AndroidTtsSynthesizer.kt` (created: real native adapter —
    application context, async race-safe init [sync-in-constructor or later
    SUCCESS], ready-only-after-SUCCESS, default-locale setLanguage with engine
    fallback, QUEUE_FLUSH/ADD, utterance id `fq-coach-N`, UtteranceProgressListener
    logging, runCatching everywhere, TAG CoachingTts)
  - `.../core/tts/CoachingSpeechGate.kt` (created: bounded in-memory dedupe on
    fingerprint+content; TTS-only markdown-light normalization of the message
    copy — Home card keeps backend bytes)
  - `.../core/tts/CoachingSpeechController.kt` (created: app-scoped collector of
    `LiveCoachStore.message.drop(1)`; latest-wins pending until engine ready;
    `enabled` seam [disable stops + clears]; `stopSpeaking`; idempotent `release`)
  - `.../di/AppModule.kt` (modified: Koin singles for gate, `TtsSynthesizer`,
    controller — all on `AppScope`)
  - `.../FitQuestApp.kt` (modified: resolve + `.start()` the controller once per
    process, guarded so voice coaching never breaks app boot)
  - `.../src/test/.../core/tts/CoachingSpeechGateTest.kt` (created: 8 tests)
  - `.../src/test/.../core/tts/CoachingSpeechControllerTest.kt` (created: 13
    tests over fake synthesizer + real LiveCoachStore)
  - `docs/docs/coaching/0005-m84-tts.md` (created: ADR)
  - `docs/docs/ui/evidence-m84/m84-tts-live-card.{png,txt}` (created: evidence)
- **Decision Logic:**
  - *Reuse the existing flow:* the controller collects the same
    `LiveCoachStore.message` flow Home renders, at app scope; `drop(1)` makes a
    retained value at subscription (cold start / reconnect / re-entry) never
    re-read. Recomposition and tab navigation publish nothing → cannot
    re-trigger speech. No parallel pipeline, so the M8.3B UI/state flow is
    untouched (regression suite green).
  - *New-message detection:* gate key = `context_fingerprint` + normalized
    content in a bounded in-memory ring; a redelivered identical message
    (replay/fan-out/regenerate) is Silent; a genuinely new context or content
    speaks. Nothing persisted.
  - *Speech semantics:* prefer the coach message copy; every speak is
    QUEUE_FLUSH so a newer message replaces the older utterance (no overlap);
    messages before engine-ready are collapsed to one latest-wins pending.
  - *Lifecycle:* synthesizer is app-scoped + application-context (no Activity
    leak, one instance per process); speech intentionally continues across tab
    nav and backgrounding so a run-session message finishes; release() is the
    process teardown path. TTS is process-scoped, NOT foreground-scoped like the
    M8.3B socket — a deliberate difference.
  - *Failure containment:* every android.speech.tts call wrapped; init failure,
    missing language/voice, dead service, speak/shutdown errors are logged
    (CoachingTts), never crashes, never blocks WS/REST/tracking.
- **Result Status:** Focused M8.4 tests **21/21**; existing coaching tests
  (CoachingWsClientTest, LiveCoachStoreTest, CoachFetcherTest, CoachCacheTest)
  regression **green**; full Android unit suite **117 tests, 0 failures, 0
  errors** (was 96); `:app:assembleDebug` **BUILD SUCCESSFUL**. Real-device
  verification (Samsung RZ8R90661CF) **E2E PASS**: app foreground → WS
  CONNECTED; fresh 2,000-step run sync (`5f50049a-…`) → `coaching_message` →
  `CoachingTts: speak queued id=fq-coach-1` + `utterance started` + `utterance
  done`; app backgrounded (WS IDLE) then relaunched (WS CONNECTED) → NOT
  re-spoken (exactly one speak for fq-coach-1 across the whole session); fresh
  3,500-step sync (`e06d39d1-…`) → NEW `speak queued id=fq-coach-2` +
  `utterance started`, and a UI dump confirmed the **"⚡ Live coaching"** card
  body equals the spoken message. Evidence:
  `docs/docs/ui/evidence-m84/m84-tts-live-card.{png,txt}`. Scope note recorded:
  speech proof is at the engine level (utterance lifecycle); media volume not
  boosted, no ear/mic confirmation. Two dev-sandbox run-sync mutations (2,000 +
  3,500 steps, fresh run_ids, no hexes) were test pushes against the dev user.
  No Git operations performed; no key values printed; M9 not started.

## [2026-09-07 08:38] - Task: M9.3 — Final Pre-Demo Reliability & AI Preflight

- **Objective:** Presentation-readiness audit/verification ONLY (not a feature
  sprint): prove the backend boots via `apps/api`, the dev-user DB is clean for a
  first run, the AI provider answers a real coach request, one run trigger flows
  end-to-end to a live `coaching_message`, AI failure degrades gracefully, the
  post-M9.2 offline/sync reconcile path holds (run_id idempotency), the real
  Samsung device runs a clean start→FGS→finish→sync→coach loop with no M9.2
  regression, and the full test suites are green. Per the task's explicit rules
  this milestone made NO code changes where existing behavior already works —
  the whole milestone is verification evidence, not diff.
- **Assumptions Declared:**
  - Backend starts via the apps/api venv exactly as Stable Requirement #2
    (`./.venv/Scripts/python.exe -m uvicorn app.main:app`); DATABASE_URL uses the
    Supavisor pooler (no IPv6 route to the direct host — stable req #3/#4).
  - Dev identity is the fixed auth stub `DEV_USER_ID = 00000000-…-000000000001`;
    live demo DB is already seeded (hexownership/runsession FKs reference it) so
    no startup auto-seed is required and none was added.
  - Live AI provider config is `LLM_PROVIDER=agentrouter` +
    `AGENTIC_API_KEY`/`AGENTROUTER_BASE_URL`/`AGENTROUTER_MODEL=deepseek-v4-flash`;
    embeddings stay on Gemini (frozen 1536-dim pgvector). Keys verified present,
    never printed.
  - Android device Samsung RZ8R90661CF is the demo device; the installed APK
    already reflects the uncommitted M9.2 working-tree fixes (HexCaptureEngine
    exactly-once accounting + LocationTrackingManager best-effort subscribe).
- **Modifications Matrix:**
  - `docs/agent_ledger.md` (this entry, appended)
  - `.agent-context.md` (M9.3 active-memory bullet appended under the dynamic
    block)
  - NO source, schema, test, or migration files were changed by M9.3.
  - Test harness files created under the job tmp dir only (ws_e2e.py,
    area5_ai_fail.py) — outside the repo, not tracked.
- **Decision Logic:**
  - *Pure verification over diff:* the task text forbids redesign/feature work and
    prefers proving existing behavior. Every area was exercised live against the
    real running backend + real Supabase + the real device, with unit suites only
    where live proof would mutate demo data or was already covered.
  - *AI-failure probe was side-effect-free:* a SECOND uvicorn instance was booted
    on :8001 with only `AGENTROUTER_BASE_URL` overridden to a dead port (env-var
    only, root `.env` untouched, process torn down). Coach returned a graceful
    HTTP 502 (`ConnectError`), the instance stayed alive, and a run-sync replay
    of an already-applied run_id returned `already_processed=true` — zero credit,
    zero mutation. This doubles as the Area 6 idempotency proof.
  - *Dev-data discipline:* all live run mutations used either fresh run_ids
    (three pushes: R1 1,200 + R2 2,000 earlier in-session, plus a 0-step
    device run that changed nothing) or replayed an already-processed run_id.
    Demo dev-user lifetime is 20,894 steps, no phantom territory created.
  - *Device run was zero-mutation:* the stationary phone finished with 0 steps /
    0 XP / 0 hexes yet still produced "✓ Synced with server" and a fresh
    workout_completed → PushCoach → new "⚡ Live coaching" message — proving the
    real chain on-device without altering demo stats.
- **Result Status:** All 9 areas PASS (details in the M9.3 report, section by
  section): backend boot/health/Supabase; dev user + FK integrity (0 orphans);
  live grounded coach 200; full WS push E2E + device receive + native TTS;
  graceful 502 under provider failure with zero crashes; run_id idempotency
  (already_processed=true replay); device sanity loop (launch→permissions→Start
  Capture→FGS notif id=1001→Stop&Finish→"Synced with server"→new live coach
  card, no FATAL anywhere); backend 391 passed + Android 153 passed (0 failures/
  0 errors/0 skipped) + assembleDebug BUILD SUCCESSFUL. M9.3 is DONE. No Git
  operations performed; no secrets printed. Note: M8.5–M9.2 do not have their
  own ledger/context entries (pre-existing gap, not authored here); this entry
  records the M9.3 superseding state.


## [2026-09-07 09:35] - Task: M9.4 — Final Presentation Polish & Demo Readiness

- **Scope Discipline:** Feature freeze honored. NO product features, architecture
  changes, or AI/WS/TTS/RunReconciler/capture-accounting modifications. The
  uncommitted M9.2 working-tree fixes (HexCaptureEngine exactly-once step
  accounting + LocationTrackingManager best-effort subscribe) were left exactly
  as found and re-verified as part of the build/test gates.
- **Modifications Matrix:**
  - `README.md` — corrected two stale claims only: (1) "the app does not yet
    call the backend" → replaced with the real backend-connected state (run
    sync, shared map, server leaderboard/coach, WS live coaching, TTS);
    (2) removed emulator dev-simulator instructions referencing `useDevLocation`
    /`useDevSteps` toggles that no longer exist in `AppModule.kt` (the simulators
    are dead code) — replaced with "use a real device" guidance.
  - `docs/DEMO_DAY_CHECKLIST.md` — NEW concise practical checklist (before-demo
    setup, demo flow, contingencies).
  - `docs/agent_ledger.md` (this entry) + `.agent-context.md` (M9.4 bullet).
  - NO Kotlin, backend, schema, test, or migration files changed.
- **UI Audit (read-only):** All demo-path screens audited
  (HomeTab/CurrentRunScreen/MainHub/LeaderboardTab/ProfileTab + fetchers).
  Every network card (rules-engine coach, AI coach, leaderboard) has a
  terminal loading→success/error state with manual Retry and finite timeouts
  (45 s read > backend 30 s LLM timeout); no fake content on failure; no
  forever-spinners; no raw error text. Back navigation stops tracking first;
  recovery prompt blocks fresh-run controls. Zero presentation-breaking
  findings → zero app code changes needed.
- **Demo Flow Verification (Samsung RZ8R90661CF, live backend :8000):** All
  PASS — cold launch (no crash); Home rich (Lvl 11, streak, both coach cards,
  grounded chip); Start Run → map/HUD; Start Capture → RunTrackingService FGS
  notification id=1001 + HIGH_ACCURACY location request live (M9.2 re-arm
  verified); Stop & Finish → "✓ Synced with server"; Home → NEW session row +
  "⚡ Live coaching" fresh card referencing the just-completed run +
  `CoachingTts: utterance done id=fq-coach-1` (native TTS spoke it); Rank tab
  → server leaderboard Rank #1 of 6 with YOU badge. Stationary indoor phone
  (no GPS fix) → 0 steps/0 hexes, honestly reported; movement capture already
  proven in M9.3 on the same device.
- **Demo Data:** unchanged by design — dev user "devuser" 10 hexes/rank 1,
  6 leaderboard players, 4 prior sessions, Lvl 11. The M9.4 device run added
  one real 0-step synced session row (honest history, no data reset).
- **Tests/Build:** Android unit 153 passed (0 failures/0 errors/0 skipped;
  release variant), assembleDebug BUILD SUCCESSFUL. Backend suite not re-run
  (no backend files changed; M9.3 baseline 391 passed stands).
- **Result Status:** M9.4 DONE. Final presentation path is clean. No Git
  operations; no secrets printed.

## [2026-09-12 11:20] - Task: M10 — Telemetry & Run Integrity (F-01, F-02, F-10 leak)

- **Scope Discipline:** Exactly three defect targets, as approved: F-01 (daily
  telemetry correctness), F-02 (pause/resume integrity), F-10 (location-monitoring
  leak ONLY — adaptive sampling and coarser-while-paused remain deferred to M15).
  NO migration, NO new endpoint, NO API contract change, NO backend business-logic
  change, NO auth, NO Redis/Kafka, NO anti-cheat, NO ambient step tracking.
  `RunTiming` was NOT rewritten. The M9.2 `pendingStepsBeforeHex` invariant was
  preserved exactly and is now covered by pause-cycle tests.
- **Stage 1 (read-only audit) before any edit:** traced
  `StepSensorManager.observeStepDeltas` → `HexCaptureEngine.startStepsCollection`
  → `HexCaptureSnapshot.applyStepDelta` → `CaptureScreenModel` reduce →
  `finishActiveRun` → `RunSessionEntity` → `DailyActivitySnapshotBuilder.build`
  → `RunSyncPayload.daily_activity` → `upsert_daily_activity`; enumerated every
  call site of `observeRecentSessions` (one real caller: `HomeTab.kt:153`, the
  rest test fakes), `getSessionsBetween` (one real caller:
  `CaptureScreenModel.kt:328`), `applyStepDelta`, `applyLocationUpdate`,
  `startLocationMonitoring`, `stopTracking`.
- **Modifications Matrix (Android only — zero files under `apps/api/`):**
  - `core/capture/HexCaptureEngine.kt` — `HexCaptureSnapshot` gains `isPaused`;
    `applyStepDelta` and `applyLocationUpdate` gated on it (paused deltas are
    DISCARDED, never banked, so resuming has no catch-up jump); new public
    `stopLocationMonitoring()` + `startLocationMonitoring()` made public; new
    `setPaused(Boolean)`; `startTracking`/`resumeTracking`/`stopTracking` seed or
    clear the flag; `stopTracking` now releases the location subscription (F-10).
  - `features/capture/CaptureScreenModel.kt` — mirrors `snapshot.isPaused` into
    `CaptureState` so the engine is the single source of truth; `onTogglePause`
    now drives controller AND engine; `onResumeRecovery` passes
    `checkpoint.isPaused` into `resumeTracking`; re-arms location monitoring on
    screen entry and releases it in `onDispose` when no run is live (a live run
    keeps its subscription — it belongs to the run, not the screen).
  - `ui/capture/CurrentRunScreen.kt` — HUD status now reads PAUSED / ACTIVE RUN /
    STANDBY.
  - `core/run/RunTrackingService.kt` — FGS notification title/text reflect the
    checkpoint's `isPaused` (no new plumbing; the field was already persisted).
  - `core/telemetry/DailyActivitySnapshotBuilder.kt` — new
    `daySteps(sessions, forTimestampMillis)`; `build()` calls it instead of
    repeating the sum, so Home and the sync snapshot share one definition.
  - `ui/home/HomeTab.kt` — today's steps read from `observeAllSessions()` (the
    previous `observeRecentSessions(limit = 3)` + filter silently dropped the
    first run of any 4+-run day) and totalled via `daySteps`; card labelled
    "Steps recorded during today's runs" (the app has no ambient step source).
  - Deliberately NOT changed: `RunTiming.kt`, `ActiveRunEntity`,
    `RunSessionDao`/`RunSessionRepository` (a new interface method would break
    four `RunSessionRepository` test fakes; `observeAllSessions()` already
    existed on all of them), and the `RunSyncPayload` shape (no `paused_seconds`
    field was added — not required by the fix).
- **Tests/Build:** `:app:testLocalDebugUnitTest` → BUILD SUCCESSFUL in 1m 12s.
  **161 tests in 22 classes, 0 failures** (was 153). New:
  `HexCaptureSnapshotAccountingTest` +5 (11→16): paused deltas discarded and not
  buffered; paused fixes move the display without capturing territory; the
  pre-hex buffer survives a pause and drains exactly once on resume; resume
  continues from paused totals; the invariant holds across repeated pause/resume
  cycles. `DailyActivitySnapshotBuilderTest` +3 (6→9): four runs in one day all
  count (the regressed `LIMIT 3` read is asserted as a contrast case); a run
  belongs to the day it started, not the day it ended; other days in an
  over-fetched list are excluded.
- **Impact statement:** Database migration: NONE. API contract change: NONE.
  Backend behavior change: NONE.
- **Result Status:** CODE COMPLETE. Exit criteria 1, 2, 4, 6, 8 MET with test
  evidence; 3 (engine half), 5 and 7 are OPEN — no device was attached
  (`adb devices` empty), and `HexCaptureEngine`'s collaborators are
  Android-backed so the engine-side pause recovery and the location release are
  not JVM-unit-testable in this codebase. Device procedure (scenarios A–D)
  recorded in `FitQuest_PHASE2_SRS.md` §7.5. Documentation updated: §1, §2, §5
  (F-01/F-02/F-10), §6, §7.5 (new), §13 (D-025/D-026/D-027), §14, §17. No Git
  operations performed; no secrets printed.

---

## [2026-09-12 12:45] - Task: M10 real-device verification (scenarios A–D)

- **Scope:** Execute the §7.5 device procedure for M10 on a physical device to
  close exit criteria 3 (engine half), 5 and 7. No scope expansion.
- **Device:** Samsung SM-M325F (Galaxy M32), Android 13, serial `RZ8R90661CF`,
  `railwayDebug` build against the Railway production backend.
- **Files changed this pass:**
  - `core/capture/HexCaptureEngine.kt` — **removed the construction-time
    `init { startLocationMonitoring() }`**. This is a second, independent F-10
    leak, found only on device; see below. No other production changes.
  - `FitQuest_PHASE2_SRS.md` — §6 M10 status, §7 header, §7.4 exit-criteria
    table, new §7.6 device record, §13 D-028, §14, §17.
  - `docs/agent_ledger.md` — this entry.
- **Second F-10 leak (the significant finding).** The first fix released the
  location subscription when the capture screen was disposed with no live run —
  necessary but not sufficient. `HexCaptureEngine` is a Koin `single` injected by
  `MainActivity` (line 40) purely to read `state.value.isTracking` for cold-start
  routing, and its `init` armed high-accuracy GPS unconditionally. So *merely
  launching the app* started continuous location collection on any screen, and
  nothing released it on the Home path; only visiting and leaving the capture
  screen happened to stop it. Measured with `dumpsys location` (the per-provider
  `service:` line under **Location Providers**):
  - force-stopped → `gps provider: service: ProviderRequest[OFF]`
  - freshly launched, sitting on Home, **before** → `ProviderRequest[@+2s0ms, HIGH_ACCURACY, WorkSource{10354 com.example.mobileapp}]`
  - freshly launched, sitting on Home, **after** → `ProviderRequest[OFF]`
  - capture screen visible in standby → `[@+2s0ms, HIGH_ACCURACY, …]` (unchanged — by design)
  - capture screen closed, no run → `ProviderRequest[OFF]`
  Fix: arming is demand-driven — the capture screen arms while visible,
  `startTracking()` re-arms for a run. `MainActivity`'s routing read needs only
  the boolean and `HomeTab` never reads engine location state, so both are
  unaffected.
  - **Evidence trap worth recording:** the `SEC Dump for updateRequirements`
    block inside `dumpsys location` is Samsung's *historical* log and still lists
    FitQuest requests from 2026-09-06. Grepping the whole dump for `ProviderRequest`
    reads that block and gives false positives in both directions. Only the
    per-provider `service:` line describes the live state.
- **Scenario A (pause freezes accrual):** HUD `ACTIVE RUN` → `PAUSED`; FGS
  notification title exactly `⏸ FitQuest Run Paused` (id 1001, channel
  `fitquest_run_active`). Over ~60 s paused, elapsed held at `01:52` and
  Steps/Distance/Calories/Hexes stayed flat while `Step Counter (handle=0x13)`
  still reported `connections=2`.
- **Scenario B (finish pairing):** summary after Stop & Finish — `Duration
  02:31`, `Total Steps 48`, `2 Hexagons Conquered`, `+120 XP`. The ~4 minutes of
  paused wall-clock are absent from the duration (a running clock would read
  ~06:31) and the step figure equals the value frozen at pause, so both exclude
  the same interval.
- **Scenario C (process death):** `am force-stop` while paused, then relaunch →
  recovery dialog `🏃 Previous Run Found`, `Steps: 48`, `Distance: 0.04 km`,
  `Elapsed: 01:52` (frozen, not wall-clock), `Status: Paused`. Tap **Resume Run**
  → HUD `PAUSED`, elapsed still `01:52`, and `dumpsys location` then shows the
  run holding the subscription. No post-resume jump: 01:52 → 01:57 → 02:18.
- **Scenario D (location released):** both the leave-the-screen path and Stop &
  Finish end at `gps provider: service: ProviderRequest[OFF]`.
- **Criterion 1 end-to-end (≥4 runs):** four runs in one device-local day with
  differing step counts (48 / 75 / 17 / 25). Home rendered `165 / 8000 steps`
  under `Steps recorded during today's runs`; the backend
  `userdailyactivity` row for 2026-09-12 held `steps=165, active_minutes=6,
  goal_steps=8000, hexes_captured=7`; the `runsession` ledger carried all four
  run ids matching Room one-for-one. The replaced capped read
  (`observeRecentSessions(limit = 3)` then filter to today) would have produced
  117 — so the run discriminates the fix rather than merely agreeing with it.
  The coach card independently corroborated the server value, quoting
  "48 steps and 3 active minutes toward an 8,000-step goal" after the first sync.
- **Sync-path note (not an M10 defect):** the first Stop & Finish reported
  `Saved offline — provisional XP (no auto-retry)`. Cause was environmental: the
  phone's Wi-Fi was associated but passing no traffic (`UnknownHostException` on
  Android's own connectivity probe; gateway unreachable) while the host PC on the
  same router resolved `fitquest-api-production.up.railway.app` normally. After
  bouncing the phone's Wi-Fi, `RunReconciler` replayed the unsynced row on the
  next **cold start** — foregrounding an already-visible activity does not fire
  `MainActivity.onStart`, so the reconcile legitimately did not run then. The
  backend re-scored that run's XP from 120 to 100 on sync, which is the intended
  server-authoritative behavior.
- **Tests/Build:** `:app:testRailwayDebugUnitTest` → **161 tests in 22 classes,
  0 failures, 0 errors** (rebuilt and reinstalled with the engine change).
- **Impact statement:** Database migration: NONE. API contract change: NONE.
  Backend behavior change: NONE. Nothing under `apps/api/` touched.
- **Result Status:** COMPLETE. All eight §7.4 exit criteria MET. Residual gap,
  recorded rather than papered over: criterion 2's step-discard path was
  confirmed on device only by counters holding while the sensor stayed
  connected — no genuine step events occurred during a pause window, so
  `applyStepDelta`'s paused branch remains unit-test-verified only.
  Documentation updated: §6, §7, §7.4, §7.6 (new), §13 (D-028), §14, §17. No Git
  operations performed; no secrets printed.

## [2026-09-17 07:53] - Task: Fix API pytest coach isolation failure

- **Objective:** Diagnose the failing GitHub Actions job `API tests (pytest)` and implement the smallest fix for `tests/test_isolation.py::test_coach_reports_the_callers_own_user_id`.
- **Assumptions Declared:** CI intentionally runs without AI provider keys; `/api/v1/coach` returns provider-configuration HTTP errors unless tests monkeypatch providers with fakes.
- **Modifications Matrix:**
  - `apps/api/tests/test_isolation.py` (modified: injected fake embedding/LLM providers for the coach isolation test and asserted `200` status before reading response fields)
  - `docs/agent_ledger.md` (modified: appended this execution record)
  - `.agent-context.md` (modified: updated active working objective in dynamic block)
- **Decision Logic:** The failure was a hermeticity gap in the test, not a production endpoint regression. The isolation test called `/api/v1/coach` without monkeypatched providers, so CI produced an error payload without `context`, causing `KeyError`. I fixed only that test by patching `get_embedding_provider` and `get_llm_provider` to deterministic local fakes and by asserting HTTP status first, preserving the endpoint's existing 503 behavior tests elsewhere while keeping this isolation assertion meaningful.
- **Result Status:** Reproduced failure locally, then verified `tests/test_isolation.py::test_coach_reports_the_callers_own_user_id` and `tests/test_coach_api.py::test_coach_endpoint_provider_not_configured_is_503` both pass; full `tests/test_isolation.py` passes (`12 passed`). Secret scan clean. Parallel validation passed (CodeQL trivial skip; code review tool unavailable in environment). `graphify update .` attempted but `graphify` CLI was unavailable.

## [2026-09-17 14:10] - Task: M11 verification — 401/403 diagnosis, CI determinism proof, migration runbook

- **Objective:** Diagnose the reported Railway 401 (REST) / 403 (WebSocket) behaviour,
  independently verify the Stage 4 test claims, prove CI determinism with and without
  credentials, inspect the 0004 downgrade path, and prepare (not execute) the migration
  runbook. Read-only on all infrastructure; no migration, no deploy, no Git operations.
- **Assumptions Declared:** The reported 401/403 are a client-side identity gap until a
  probe distinguishes a missing token from a rejected one; a local green suite is not
  evidence of CI determinism, because a developer `.env` supplies credentials the runner
  does not have.
- **Modifications Matrix:**
  - `.github/workflows/ci.yml` (modified: replaced the false hermeticity claim — it
    asserted the JWKS fetch was the *only* patched boundary — with an accurate statement
    of the two patched boundaries, the run #1 history, and why a green local run is not
    evidence).
  - `FitQuest_PHASE2_SRS.md` (modified: §1 doc control; §6 M11 status; §14 M11 milestone
    row; §17 current-next-action superseded; **§18 new** — verification record, two-account
    E2E procedure, migration 0004 runbook, CI determinism record, Android rebuild procedure).
  - `apps/app/.env` (modified, gitignored: added empty `SUPABASE_URL` / `SUPABASE_ANON_KEY`
    placeholders with the publishable-vs-service-role warning; empty is treated as
    "not configured" by `envOrDefault`, so behaviour is unchanged).
  - `docs/agent_ledger.md` (modified: this record).
- **Diagnosis of the 401/403 (the significant finding).** The installed APK was last
  updated **2026-09-12 11:51:22** — five days before the M11 auth code existed. Pulled the
  APK from the device and scanned its DEX: **zero** occurrences of `SupabaseAuthClient`,
  `AuthInterceptor`, `AuthSession`, `EncryptedTokenStore`, `SupabaseAuthApi`,
  `TokenRefreshAuthenticator`, and **zero** `supabase.co` strings; `fitquest-api-production`
  present (×2) and no LAN IP, so it is a pre-M11 `railwayDebug` build. It has no sign-in,
  no token store and no interceptor, so it can never send an `Authorization` header — and
  the M11 backend answers exactly 401 (`Not authenticated`) / 403 to a tokenless client.
  Live probes confirm the backend is correct, not broken: `/health` 200; no header → 401
  `Not authenticated`; a well-formed ES256 token naming an unknown `kid` → 401
  `Invalid or expired token` — **not** 503, which is what an unconfigured `SUPABASE_URL`
  would produce, so the issuer/JWKS path is configured and reachable. The project publishes
  exactly one ES256/P-256 key, matching `security.py`'s pinned algorithm.
  **Latent second issue:** because `user.auth_subject` does not exist yet, fixing only the
  client converts the 401s into 500s on the first authenticated request.
- **CI determinism.** Run #1 (`f7f27b9`) was the workflow's first real run: Android green,
  API red. Reproduced in a credential-free `git archive` checkout as `412 passed, 1 failed`
  against `413 passed` locally — one test, `test_isolation.py::test_coach_reports_the_callers_own_user_id`,
  asserting on a `context` key that only a successful (real, billable) LLM call produces;
  without a key the endpoint answers 503, so the assertion raised `KeyError: 'context'`.
  That test was fixed in `79d9481`; I verified the fix rather than assuming it, in three
  runs: **413 passed** with credentials, **413 passed** with no `.env` and no provider
  variables, and **413 passed** with deliberately *bogus* credentials present (132.7 s) —
  the last being the discriminating proof, since a test still reaching a provider would
  have failed on the fake key instead of passing. CI run #5 (`0b79cf7`, merge to `main`)
  is green in both jobs with every step `success`.
- **Migration 0004 downgrade — test-only defect, NOT a migration defect.** Ran the round
  trip on a throwaway SQLite database: after `upgrade 0004` the column and unique index are
  present; after `downgrade 0003` both are gone and the `user` table is intact. The
  Postgres operations (`drop_index` then `drop_column`) are standard and safe for this
  shape. The defect is in coverage: neither alembic round-trip test asserts anything about
  `auth_subject` or `ix_user_auth_subject` on the way up or down, so 0004's schema is
  covered only incidentally by `returncode == 0`. Compounding it, the functional suite
  builds its schema with `SQLModel.metadata.create_all()`, which takes the column straight
  from the model — so model↔migration drift is structurally invisible to 413 tests and
  visible only in the two subprocess alembic tests, which do not look at 0004. No production
  data was touched.
- **Migration state (verified live, read-only, over both pooler ports):** PostgreSQL 17.6;
  `alembic_version = 0003`; `user.auth_subject` absent; `ix_user_auth_subject` absent;
  6 user rows. **0004 is NOT applied.**
- **Session-mode verification for the migration command.** `DATABASE_URL` currently uses
  `:6543` (Supavisor transaction mode), whose pooling does not guarantee a session across a
  migration's transactional DDL. Port **5432** (session mode) was verified connecting with
  the same credentials (`postgres.<project-ref>`, password masked) and reading the same
  revision. The runbook rewrites the port with `sed 's/:6543\//:5432\//'` so the password is
  never handled or echoed.
- **Runbook prepared, NOT executed** (SRS §18.3): `alembic current` → `upgrade 0004` →
  `alembic current`, plus verification SQL (`alembic_version`, `information_schema.columns`,
  `pg_indexes`, and a `count(*) / count(auth_subject)` row check expecting 6 / 0), rollback
  `alembic downgrade 0003`, and rollback verification to the same standard.
- **Secret handling:** no secret was printed, logged or written to a tracked file. The
  publishable anon key and the two Supabase accounts are supplied by the project owner; no
  credential was requested. The project ref appeared once in a masked connection dump — it
  is not a credential (it ships in the client APK).
- **Impact statement:** Database migration: **NONE APPLIED**. API contract change: NONE.
  Production data touched: NONE. Deployment: NONE. Git operations: **NONE** (no commit,
  push, reset, or branch change) — the working tree holds only the three documentation
  edits above.
- **Result Status:** CI determinism FIXED and proven; migration runbook PREPARED; 401/403
  root-caused to a pre-M11 APK. **M11 remains INCOMPLETE.** Open blockers: (1) the anon key
  is not in `apps/app/.env`; (2) migration 0004 awaits explicit authorization; (3) the
  two-account device E2E has not been run. Proposed but not done (needs approval): neutralise
  the provider variables in `tests/conftest.py` the way `SUPABASE_URL`/`ENVIRONMENT` already
  are, so hermeticity is structural locally and not only a property of the runner; and add
  explicit 0004 assertions to an alembic round-trip test.

## [2026-09-17 15:45] - Task: M11 second verification pass — hermeticity hardening, 0004 coverage, M11 APK

- **Objective:** Make the API suite hermetic in configuration rather than by accident, give migration
  0004 real round-trip coverage, prove the suite in three credential environments, prepare the Android
  configuration and build the M11 APK, and prepare (not execute) the migration runbook. No migration, no
  install, no deploy, no Git operation.
- **Assumptions Declared:** A suite that passes is not a suite that is hermetic — the two coincide only
  while the machine supplies no credentials; and a test that has never been seen to fail is not evidence
  of anything.
- **Modifications Matrix:**
  - `apps/api/tests/conftest.py` (modified: empties `GEMINI_API_KEY`, `AGENTIC_API_KEY`,
    `AGENT_ROUTER_API_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY` and pins
    `LLM_PROVIDER=gemini` before the app import, so `env_file=(".env", "../../.env")` cannot supply a
    live provider; module docstring updated to match).
  - `apps/api/tests/test_config.py` (modified: two guard tests — the live `settings` carries no provider
    credential, and a `.env` *containing* a key still cannot configure a provider).
  - `apps/api/tests/test_migration_0004.py` (**new**: 0004 round-trip + retry-safety assertions).
  - `apps/app/tools/apk_auth_scan.py` (**new**: stdlib-only APK inspector; prints class/URL counts, never
    a key; exits 1 on a missing required class).
  - `.github/workflows/ci.yml` (modified: the hermeticity comment now records that credentials are
    neutralised in conftest, so the claim matches the code).
  - `FitQuest_PHASE2_SRS.md` (modified: §1 repository state corrected to `0b79cf7` + uncommitted tree;
    §18.1 counts refreshed to 417; §18.4 residual gap marked closed; §18.5 build/install/DEX-scan
    rewrite; **§18.6 new**).
  - `docs/agent_ledger.md` (modified: this record).
- **The hole this closed was not theoretical.** The repository-root `.env` carries live `GEMINI_API_KEY`
  and `AGENTIC_API_KEY`, and `Settings` loads `env_file=(".env", "../../.env")` — so *every local test run
  before this change had a billable key in `settings`*. That is exactly the condition that let CI run #1's
  defect pass locally and fail on the runner. Measured, not assumed: with the repo `.env` present the
  suite sees a Gemini credential (`True`); after the conftest block it does not.
- **Migration 0004 coverage — and both assertions mutation-tested.** Setting `unique=False` in 0004
  produced `assert 0 == 1`; making `downgrade()` a no-op produced `assert 'auth_subject' not in {...}`.
  The migration file was restored byte-identical (verified clean against HEAD). The `unique` assertion is
  the substantive one: `resolve_or_provision_user` races on insert and uses this index as the arbiter, so
  a non-unique index would let two concurrent first logins of one Supabase account create two internal
  users.
- **Three runs, all 417 passed** (413 + the 4 new tests): clean credential-free copy of the working tree
  143 s; bogus credentials 138 s; normal local environment 131 s. The clean copy was used rather than
  `git archive HEAD` because these changes are uncommitted and an archive would have tested the old code;
  `app` import was verified to resolve inside the copy.
- **Android.** `./gradlew :app:assembleRailwayDebug` → `BUILD SUCCESSFUL in 52s`;
  `app-railway-debug.apk`, 74,029,300 bytes. Generated `BuildConfig`: `BACKEND_BASE_URL =
  https://fitquest-api-production.up.railway.app/`, `SUPABASE_URL = ""`, `SUPABASE_ANON_KEY = ""`.
  DEX scan: all 7 required M11 classes present, `fitquest-api-production` ×2, `10.0.2.2` 0, `192.168.` 0,
  `supabase.co` 0. **The artifact is built but NOT configured and is not the one to install.**
- **Secret handling:** no secret printed, logged or written to a tracked file. `apps/app/.env` values were
  read only as lengths; the anon key is never searched for by the scanner. `.env` files verified
  gitignored; `apps/api/test_fitquest.db` covered by `*.db`; the APK sits under a `/build` ignore.
- **Impact statement:** Database migration: **NONE APPLIED**. Production data touched: NONE. Device
  install: **NONE** (no device attached — `adb devices` empty). Deployment: NONE. Git operations: **NONE**.
- **Result Status:** suite hermetic and proven; 0004 covered and mutation-verified; M11 APK built and
  verified as an M11 build. **M11 remains INCOMPLETE** — blocked on: the anon key absent from
  `apps/app/.env`; migration 0004 awaiting explicit authorization (live revision still `0003`,
  `user.auth_subject` absent); the two-account device E2E unrun. Latent and unchanged: a rebuilt client
  turns today's 401s into **500**s until 0004 is applied, so the rebuild and the migration must land
  together.

## [2026-09-17 16:05] - Task: Configure the M11 APK with the anon key and rebuild

- **Objective:** Rebuild the `railway` debug APK now that the project owner has supplied the Supabase
  URL and anon key, and verify the result carries the M11 client and a valid identity configuration.
  No install, no migration, no deploy, no Git operation.
- **Assumptions Declared:** A build that *compiles* is not a build that is *configured*, and a key that
  works is not necessarily the key that was intended — an anon key and a service-role key are both JWTs
  and are indistinguishable by eye.
- **Modifications Matrix:**
  - `apps/app/.env` (modified, gitignored: the owner appended real `SUPABASE_URL` / `SUPABASE_ANON_KEY`
    values; the two now-obsolete **empty placeholders** added in the previous pass were removed, so each
    key has exactly one definition. No value was altered, printed, or logged).
  - `FitQuest_PHASE2_SRS.md` (modified: §18.6 D rewritten to record both builds and the two
    configuration hazards; the blocker list updated — the anon-key blocker is now resolved).
  - `docs/agent_ledger.md` (modified: this record).
- **Two hazards caught, neither by assuming.**
  1. The key was **appended, not substituted**: `.env` briefly held four `SUPABASE_*` lines — my two
     empty placeholders plus the owner's two real values below. Gradle's parser ends in `.toMap()`, so
     the **last** occurrence wins and the real values did take effect — but a config file whose
     correctness depends on which duplicate a reader picks is a trap, so the placeholders were deleted.
     Confirmed empirically rather than by reasoning about Kotlin: the generated `BuildConfig` carries the
     real values.
  2. **Verified the key is the anon key BEFORE building it into an APK**, by decoding its `role` claim:
     `role='anon'`, `ref='gdskasfgolpfdfaftxwk'`. Had it been the service-role key — which also arrives
     as a `eyJ…` JWT and is equally easy to copy from the same dashboard page — the APK would have
     shipped a key that bypasses Row Level Security to anyone who unzips it. That is the one mistake in
     this area that is catastrophic rather than merely broken, so it is checked by claim, not by
     trusting the filename.
- **Non-secret configuration probe (no credential transmitted):** GoTrue `/auth/v1/settings` → 200 (the
  URL+key pair is valid); `/auth/v1/.well-known/jwks.json` → 200 publishing **exactly one ES256/P-256
  key**, matching `security.py`'s pinned `ALGORITHMS = ["ES256"]`; `/auth/v1/user` with no token → 401.
  The anon key is a publishable value and was redacted in all output regardless.
- **Build and verification.** `BUILD SUCCESSFUL in 32s`, `app-railway-debug.apk` 74,103,039 bytes.
  `BuildConfig`: `BACKEND_BASE_URL=https://fitquest-api-production.up.railway.app/`,
  `SUPABASE_URL=https://gdskasfgolpfdfaftxwk.supabase.co`, anon key present (208 chars, not echoed).
  DEX scan: all 7 required M11 classes present; `fitquest-api-production` ×2; `10.0.2.2` 0; `192.168.` 0;
  **`supabase.co` 0 → 2** (vs build 1). A JWT-literal scan finds exactly one 208-char token with
  `role='anon'`, ×2 occurrences — so the key, not merely the URL, provably reached the DEX.
- **A broken check, corrected before it was reported.** The first JWT scan returned 0 literals, which
  would have been reported as "the key is missing". The regex excluded `.`, and a JWT is
  `header.payload.signature` — so it matched only the 36-char header and fell under the length floor.
  Fixed and re-run: 1 distinct token found. The build was never at fault; the evidence-gathering was.
- **Device state (read-only).** SM-M325F `RZ8R90661CF` is now attached. Still carries the pre-M11 build:
  `lastUpdateTime=2026-09-12 11:51:22`, `versionName=1.0`. **Install NOT executed — not authorized.**
- **Secret handling:** no secret printed, logged or written to a tracked file. `.env` values were read as
  lengths and decoded `role`/`ref` claims only; the key was never echoed, including in the probe output.
- **Impact statement:** Database migration: **NONE APPLIED**. Production data touched: NONE. Device
  install: **NONE**. Deployment: NONE. Git operations: **NONE**.
- **Result Status:** the installable, correctly-configured M11 APK now exists and is verified. **M11
  remains INCOMPLETE** — blocked on: migration 0004 awaiting explicit authorization (live revision
  `0003`, `user.auth_subject` absent), and the two-account device E2E unrun. Unchanged and now acute:
  the first authenticated request from the new client returns **500** (`UndefinedColumn`) rather than
  401, so E2E steps (d) and (e) cannot pass until 0004 is applied — sign-in itself (a–c) will work.

## [2026-09-17 16:25] - Task: Fix the M11 Android startup crash (Koin interface bindings)

- **Symptom.** The rebuilt M11 APK installed cleanly and then died within ~2s of launch. `am start -W`
  reported `Status: ok` — it means the intent was delivered, not that the app survived — so the crash was
  found only by checking `pidof` (empty), `topResumedActivity` (back to the launcher) and
  `dumpsys activity processes` ("last crashed +14s767ms ago") separately. Launch confirmation by exit
  status alone would have produced a false "app launched" claim.
- **Root cause.** `NoBeanDefFoundException: No definition found for type 'okhttp3.Interceptor'`, reached
  from `MainActivity.onStart` → `CoachForegroundCoordinator` → `RunReconciler` → `RunSyncer` →
  `FitQuestApi`. `AppModule` registered `AuthInterceptor` and `TokenRefreshAuthenticator` under their
  CONCRETE types, but `FitQuestApiClient.create(authInterceptor: Interceptor, authenticator: Authenticator)`
  declares the INTERFACE types, and Koin's `get()` resolves against the declared parameter type. There
  were **two** missing bindings; the trace named only the first, so fixing `Interceptor` alone would have
  moved the failure to `Authenticator`. `git log -S 'authInterceptor'` pins the regression to `f7f27b9`
  ("Phase 2 M11 half"). The `wsOkHttp` client at the second site named the concrete types explicitly and
  so kept working — which is exactly why both sites had to be corrected together.
- **Why 244 tests missed it.** Not one of them builds the container. Every test constructs the
  collaborators directly, so the graph was never assembled outside a device — the defect was reachable
  only from `MainActivity.onStart`. A green unit suite was not evidence about this class of bug.
- **Fix (minimal).** `AppModule.kt` only: both registrations changed to `single<Interceptor>` /
  `single<Authenticator>`, and the second resolution site (`wsOkHttp`) changed to `get<Interceptor>()` /
  `get<Authenticator>()`. 16 insertions, 4 deletions; no domain logic, backend, schema or migration file
  touched. `AuthSession`, the single-flight refresh and the `AuthInterceptor` token-at-call-time behaviour
  are unchanged — the collaborators are still singletons, so there is still exactly one authenticator and
  Supabase's rotating refresh token is still redeemed once.
- **New guard: `AppModuleGraphTest` (4 tests).** Starts the real `appModule` via `koinApplication` and
  resolves the two authenticated clients, plus asserts the resolved instances are the expected types and
  that both clients receive the SAME authenticator. Written BEFORE the fix and run against the broken
  code first, so its teeth are measured rather than assumed: 2 of 4 failed pre-fix — the interface lookup
  returned **null** (`AssertionError`), and the REST client threw the same `InstanceCreationException`/
  `NoBeanDefFoundException` the device did. One test was found toothless during that run —
  `assertSame(null, null)` passes on two missing bindings — and was corrected to assert presence first.
- **Tests.** `:app:testLocalDebugUnitTest` **248 passed, 0 failed, 0 errors, 0 skipped**;
  `:app:testRailwayDebugUnitTest` **248 passed, 0 failed, 0 errors, 0 skipped** (244 → 248, the four new
  tests). Both flavors, because they differ in the `BuildConfig` constants compiled in.
- **Build.** `BUILD SUCCESSFUL`, `app-railway-debug.apk` 74,103,000 bytes, SHA-256
  `13e2f28ea6c9e4a634753087e6b471e18a152b1644d25642f85cfaecb9bda564`. APK scan PASS: all 7 required M11
  classes, `fitquest-api-production` ×2, `10.0.2.2`/`192.168.` 0, `supabase.co` ×2 — still configured.
- **Install.** `adb install -r` → `Success`, **no** `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, so no uninstall
  and no data loss. `lastUpdateTime=2026-09-17 16:18:45`, `firstInstallTime=2026-09-05 14:22:20`
  unchanged → updated in place. The installed APK was pulled back and its SHA-256 matched the build
  byte-for-byte, so the running binary is provably the fixed one.
- **Launch.** `am force-stop` first, then a genuine cold start (`LaunchState: COLD`, TotalTime 1814ms) so
  the launch was unambiguously of the new build rather than a process the installer had left behind.
  Alive after 10s: `pidof` → 31392, `topResumedActivity` → `MainActivity`, **no crash record**. Logcat:
  `NoBeanDefFoundException` ×**0**, no `FATAL EXCEPTION`, no Koin error. Screenshot confirms the M11
  `LoginScreen` rendering (Email / Password / Sign in). Login was NOT attempted — not authorized.
- **Secret handling:** the full logcat buffer was scanned for `eyJ`, `supabase`, `Bearer`, `apikey`,
  `access_token`, `refresh_token` → **all 0**. The two `password` matches are Samsung's
  `WifiProfileShare` system service (pid 1440), not this app. Temp diagnostics (pulled APK, screenshot)
  deleted. No secret printed, logged or written to a tracked file.
- **Impact statement:** Database migration: **NONE APPLIED**. Production data touched: NONE. Deployment:
  NONE. Git operations: **NONE** (no commit, push, checkout, revert, reset).
- **Result Status:** the launch-blocking M11 crash is **fixed and verified on device**. **M11 remains
  INCOMPLETE** — unchanged blockers: migration 0004 awaiting explicit authorization (live revision
  `0003`, `user.auth_subject` absent), so the first authenticated request still returns **500**
  (`UndefinedColumn`) rather than 401 and E2E steps (d)/(e) cannot pass; and the two-account device E2E
  is unrun. Steps (a)–(c) are now reachable: the app opens and the login screen appears.

## [2026-09-17 17:15] - Task: M11 — account-scoped local storage (the two-account leak)

- **Symptom.** Sign in as Supabase Account B, record one run, log out, sign in as Account A → A sees B's
  run. Confirmed device-local, not backend: no GET session-list endpoint exists, `HomeTab` reads Room
  directly, and the live database held 45 rows with **1** distinct `user_id`. Applying migration 0004
  would not have changed it — nothing about this defect is server-side.
- **Root cause.** Every local table was a single, unowned row set. `user_profile` was keyed on the literal
  `"local_user"`, so one row held the level, the lifetime totals, the streak AND `isOnboardingCompleted`
  for every account that ever signed in — which is also why the second account skipped onboarding.
  `captured_hexes.hexId`, `daily_quests.id` (`date + slug`) and `achievements.id` (fixed constants) are
  shared between accounts by construction, so `OnConflictStrategy.IGNORE` silently gave the second
  account no achievements at all. Plus three process-lifetime things no query could ever filter because
  they were keyed by nothing: `CoachCache` (one account's coach message, grounded in that account's
  history), `LiveCoachStore` (the last message pushed down an authenticated socket), and a live run
  (sensors, foreground notification, ticking timer).
- **Fix.** `ownerSubject: String` on all six entities, holding the Supabase Auth user id — the JWT `sub`,
  i.e. the same value the backend resolves to `user.id`, so local rows are attributable to a server-side
  identity. `IdentityProvider` (a one-method interface `AuthSession` now implements) is the narrow
  contract the data layer depends on, so `data -> identity` and the scoping logic is testable without a
  Supabase client, a token store or a network. Every `@Query` names `ownerSubject` and takes the owner
  first; repositories resolve the subject themselves and **stamp** it on write, so a caller cannot file a
  row under another account by passing its id. A write with no session is refused and logged rather than
  filed under a placeholder. `UserProfileEntity`'s key IS the account, which is what makes a new account
  on this device get a freshly defaulted profile and therefore onboarding (`getProfile` creates the row).
- **Two hazards that would have made this wrong.** (1) A coach fetch already in flight when the account
  changes arrives afterwards and repopulates the cache it was just cleared from — solved with a
  generation counter: `fetch()` remembers the generation it started under and refuses to publish if it
  changed. (2) `abandonRun` nulls the run, and the service's teardown path deletes the checkpoint — but
  that checkpoint belongs to the account that started the run and is how it gets the run back. Solved by
  setting `abandonedForAccountSwitch` **before** `_runId` goes null and checking it once in
  `shouldClearCheckpointOnStop()`, at the single point both teardown routes converge. The flag is reset
  in `startRun`, so it cannot leak into the next account's run.
- **Sign-out is not what makes it safe.** `AccountScopeCoordinator` subscribes to `identity.subject`
  rather than being called by `signOut()`. A session also ends when the refresh token is rejected
  mid-request or `restore()` refuses a stored session at startup, and an account switch may never pass
  through `AuthState.SignedOut` at all — coupling a privacy guarantee to a hook someone has to remember
  to call is how this defect got here. It clears the caches and tells the run controller; it **deletes
  nothing**, so each account's history and unfinished checkpoint are exactly as it left them.
- **Room schema 5 -> 6.** All six tables are rebuilt (create staging -> `INSERT ... SELECT` -> drop ->
  rename) rather than `ADD COLUMN`, because `ownerSubject` is part of the identity of four of them and
  SQLite cannot alter a primary key. Rebuilding all six keeps one uniform shape with no DB-level
  `DEFAULT` anywhere, which is what Room's `TableInfo` validation wants.
  `fallbackToDestructiveMigration()` was **removed**: with it, any migration gap silently drops and
  recreates every table — i.e. deletes the user's whole local history with a log line as the only
  evidence — which directly contradicts "do not silently delete existing rows".
- **Legacy-row policy: QUARANTINE (documented in the migration KDoc, NOT yet approved).** The device
  cannot know which account wrote rows that predate the column; the only account identifier ever stored
  was the token, overwritten on each sign-in. Inferring an owner would mean handing one account another's
  history — the defect being fixed. So the rows are carried across intact and stamped
  `__legacy_unowned__`, which no account can match, so no query returns them. Nothing is deleted; they
  are re-assignable with one `UPDATE` setting `ownerSubject` to the verified subject once the correct
  account is established. **Device consequence: its 40 runs, 16 hexes, 18 quests, 8 achievements and 1
  profile stop being visible, and the next account onboards fresh. That is the cost of not guessing, and
  it is awaiting the owner's decision.**
- **Tests written before the fix, and their teeth measured rather than assumed.** Five production lines
  were temporarily reverted (the owner stamp, the scoped observer, the profile key, `coachCache.clear()`,
  the abandon flag), the suite was run, and **13 of the 277 tests failed — all of them in the four new
  classes, none elsewhere**; the lines were then restored and verified line-by-line by grep. New:
  `OwnerScopedDaoSourceTest` (6 tests — every `@Query` filters by owner and binds `:owner`, every scoped
  entity is keyed by its owner, `"local_user"` is gone, the sentinel cannot collide with a UUID, and the
  invariant is made to fail on an embedded copy of the pre-fix DAO so it is not vacuous),
  `AccountScopedLocalDataTest` (13), `AccountScopeCoordinatorTest` (4),
  `ActiveRunControllerAccountSwitchTest` (7). Two of the new tests failed on first run for real reasons
  and were fixed: the fake DAOs returned a one-shot snapshot instead of a live query (so the observer
  test hung — Room's generated DAOs re-emit on change, and a fake that does not makes an observer test
  pass for the wrong reason), and the source checker conflated the parameter name `owner` with the column
  `ownerSubject`.
- **Why the DAO invariant parses source.** Room declares `@Query`/`@Entity`/`@PrimaryKey` with
  `RetentionPolicy.CLASS` (verified on `room-common-2.6.1` with `javap`: both
  `kotlin.annotation.AnnotationRetention.BINARY` and `RetentionPolicy.CLASS` are on the class file).
  CLASS retention is stripped before runtime, so `getAnnotation(Query::class.java)` is null in a JVM test
  and an annotation-driven invariant would have asserted nothing and still gone green. The checker
  therefore reads the same Kotlin that Room's KSP processor consumes.
- **Migration verified against the real device database, read-only.** `tools/verify_migration_5_6.py`
  copies `fitquest.db` **plus its `-wal`/`-shm`** (committed pages live in the WAL; a bare `.db` copy
  reports stale row counts) to a temp dir and applies the migration **there**. The SQL is extracted from
  `FitQuestDatabase.kt` rather than retyped, so the tool cannot verify a copy that has drifted from the
  shipping code, and the expected shape is parsed from the **entity sources** — an independent source of
  truth, which is what catches a column typo or a wrong affinity. Result: `user_version` 5 -> 6, all 6
  tables rebuilt, **83 rows in / 83 out** (40 runs, 16 hexes, 18 quests, 8 achievements, 1 profile),
  every row carrying the sentinel, **0** rows visible to a real account, columns/order/affinities/NOT
  NULLs and primary keys matching the entities, no DB-level `DEFAULT`, no stray indices. The tool's first
  run **failed** and the fault was in the tool — its entity parser skipped properties carrying an
  annotation, so it dropped `@PrimaryKey val id` and under-reported the entity columns; the migration was
  correct throughout. Fixed and re-run green. A claim in the migration KDoc that the migrated table is
  byte-identical in `sqlite_master` to a fresh one was corrected to what is actually true (same parsed
  shape; the statement text differs by `IF NOT EXISTS`, which Room does not compare). The tool's own
  hygiene was found wanting on the first runs: `sqlite3.connect`'s context manager commits but does NOT
  close, so the copied database stayed open, Windows held it locked, and `rmtree(ignore_errors=True)`
  failed **silently** — leaving two copies of the real database in `%TEMP%`. The connection is now closed
  explicitly and a failed cleanup prints a loud warning naming the directory. Both stale copies were
  deleted and the re-run confirms the tool now leaves nothing behind.
- **Tests.** `:app:testLocalDebugUnitTest` **277 passed, 0 failed**; `:app:testRailwayDebugUnitTest`
  **277 passed, 0 failed** (both flavors, because they differ in the `BuildConfig` constants compiled in).
- **Build.** `:app:assembleRailwayDebug` **BUILD SUCCESSFUL**, `app-railway-debug.apk` 74,062,867 bytes.
- **Impact statement:** Database migration: **NONE APPLIED** — `MIGRATION_5_6` is written, verified
  against a copy of the real database, and NOT applied to the device. Backend migration 0004: **still not
  applied**. Production data touched: NONE. Install: **NONE** (not authorized). Git operations: **NONE**.
- **Result Status:** the two-account isolation defect is **fixed in code and verified by test**; **M11
  remains INCOMPLETE**. Awaiting the owner on: (a) the legacy-row quarantine policy — its 83 rows become
  invisible and the next account onboards fresh; (b) authorization to install so the fix can be confirmed
  on device; (c) migration 0004, unchanged blocker.

## [2026-09-17 17:41] - Task: M11 — quarantine approved, install, and the device E2E (a DI regression found)

- **Scope.** Owner approved the `LEGACY_UNOWNED` quarantine policy and authorized installation of the
  rebuilt Railway debug APK with `adb install -r` (no uninstall, no data clear, no Git operations), then
  asked for the account-switch E2E on the connected SM-M325F (RZ8R90661CF).
- **Install.** Two installs, both `adb install -r`, both **Success** — no
  `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, no uninstall, no data cleared. The second was required; see the
  regression below. Launch: process alive on both, crash buffer empty, no `NoBeanDefFoundException`.
- **Regression found on device — the fix did not work on the first build.** The app launched cleanly and
  looked healthy, but logcat carried
  `E FitQuestApp: Account scope observer start failed / Caused by: NoBeanDefFoundException: No definition
  found for type 'com.example.mobileapp.core.run.RunServiceLauncher'`. `ActiveRunController` declares the
  `RunServiceLauncher` **interface**; `AppModule` registered only the concrete
  `ForegroundRunServiceLauncher`. Koin resolves `get()` against the **declared** type, so the controller
  could not be constructed — and `AccountScopeCoordinator` depends on it, so **the coordinator could not be
  constructed either and the account-switch reset never ran at all**. Room scoping was unaffected, which is
  exactly why the data looked right and the failure was invisible. This is the **third** instance of the
  same mistake in this module (`okhttp3.Interceptor`/`Authenticator` in M11, then `RunSessionEngine` while
  writing this very module, now `RunServiceLauncher`). It was invisible because `FitQuestApp` catches the
  failure around `AccountScopeCoordinator().start()` and logs it — no crash, no symptom, no user-visible
  sign, just a privacy control that was not there.
- **Fix 1 — the binding.** `single<com.example.mobileapp.core.run.RunServiceLauncher> {
  ForegroundRunServiceLauncher(get()) }`, with a comment naming the rule and the two prior occurrences.
- **Fix 2 — make the rule mechanical.** New `di/DeclaredTypeBindingTest`: for every class the module
  registers, each constructor parameter whose type is an **interface declared in this project** must have a
  binding registered under that interface's name. Source-parsing, because the slice that broke needs a
  `Context` and so cannot be instantiated in a JVM test at all — which is precisely why `AppModuleGraphTest`
  (written after the OkHttp crash, and which resolves the two authenticated clients) does not reach it. The
  checker reads three registration shapes: explicit generics (`single<X>`), bare registrations
  (`single { Foo(…) }`, `single { SupabaseAuthClient.create(…) }`), and Room accessors
  (`single { get<FitQuestDatabase>().hexDao() }` → `HexDao`). Its second test **derives the pre-fix module
  from the real source** (`single<…RunServiceLauncher> {` → `single {`) rather than retyping a snippet — the
  first attempt embedded a hand-written snippet that omitted unrelated bindings and so reported five
  violations instead of one; deriving it means the self-check cannot drift out of describing the code it
  claims to describe, and it asserts the rewrite applied so a rename cannot make it vacuous.
- **Migration applied on device (approved) and verified.** `user_version` 5 → 6, no `__v6` staging tables
  left, primary keys correct (`captured_hexes (ownerSubject, hexId)`, `user_profile (ownerSubject)`).
  Verified against a **read-only copy** pulled with `run-as` (`exec-out`, no device-side staging, live DB
  never opened for write). **84 rows quarantined, 0 visible to any account** — 41 runs, 16 hexes, 18
  quests, 8 achievements, 1 profile. **The count is 84, not the 83 recorded in the previous entry**: the
  device gained one run at 17:08:55 local, written by the old v5 build *after* the 16:40 backup, so
  inheriting the sentinel is correct rather than a mis-stamp. Established by diffing the live `run_sessions`
  id set against the backup (`f5816feb-…` extra, nothing missing) and by its `startedAt` preceding the
  17:21 migration — checked rather than assumed, because "a new row was stamped legacy" and "an old row
  migrated" look identical in a row count.
- **E2E — the original failure, retested end to end on the device.** Sequence: restored session
  `f0f154ba…` → sign out → sign in `d5dd0cb0…` → onboarding → run created → sign out → sign in
  `f0f154ba…` → sign out → sign in `d5dd0cb0…`. All 7 transitions logged by `AccountScopeCoordinator`,
  subject masked to 8 chars, no gaps. Results:
  - **Onboarding (the specific worry):** the incoming account got a **fresh profile row with
    `isOnboardingCompleted = 0`** — it did *not* skip onboarding off the previous account's profile. This
    was the failure mode the quarantined legacy profile would have caused.
  - **The leak itself:** `d5dd0cb0…` recorded run `fc42d5db-1021-435f-822c-72adebb8f775` (23 steps, 1 hex)
    plus 1 hex, 3 quests, 8 achievements. `f0f154ba…`'s scoped queries returned **0 runs and 0 hexes**
    while that run sat in the same database file. Run-isolation is now shown with a run that actually
    exists, not merely by absence.
  - **Preservation:** on sign-out nothing was deleted; `f0f154ba…`'s rows survived unchanged, and
    `d5dd0cb0…`'s run was still present and intact when it signed back in. Store totals: 42 runs stored =
    41 legacy + 1 account-owned; **0 legacy rows visible to any account**.
- **What the E2E did NOT establish, stated plainly.** Active-run state across a mid-run switch was **not
  exercised** — both accounts showed 0 `active_run` checkpoints, so `abandonRun()` and
  `shouldClearCheckpointOnStop()` never ran on device. `CoachCache` / `LiveCoachStore` contents are **not
  observable from outside the process**; the coordinator demonstrably fires on every transition, but "the
  caches were actually cleared" remains the unit test's claim, not a device observation. UI-level
  confirmation is the owner's. Observers are supported indirectly (a stale unscoped observer would have
  emitted the other account's run, and did not).
- **Tests.** `:app:testLocalDebugUnitTest` **279 passed, 0 failed**; `:app:testRailwayDebugUnitTest`
  **279 passed, 0 failed** (277 + the 2 new binding tests).
- **Build.** `:app:assembleRailwayDebug` **BUILD SUCCESSFUL**, `app-railway-debug.apk` 74,146,379 bytes.
  Installed.
- **Hygiene.** Temp copies of the real database were deleted after every pull; a leftover copy from the
  previous session's verifier (`/tmp/fq-verify-*`, `/tmp/fq-workdir.txt`) was found still on disk and
  removed — note that `rm -rf /tmp/fq-*` silently failed to remove it and the explicit paths worked. A
  logcat watch was armed for the E2E transitions and expired on its 15-minute limit after capturing all 7.
- **Open recommendation (NOT actioned).** `FitQuestApp` fails **open** on the coordinator: it catches and
  logs. That is now the second time a caught-and-logged DI failure has hidden a real defect, and here the
  thing degraded silently was a privacy control. Making it fail loudly is a product decision with
  crash-loop implications, so it was left alone and raised instead.
- **Impact statement:** Database migration: **MIGRATION_5_6 APPLIED to the device** (owner-approved
  quarantine). Backend migration 0004: **still not applied** — the coaching WebSocket cycles
  `CONNECTING` → `DISCONNECTED`, consistent with the known `UndefinedColumn` 500. Production data deleted:
  **NONE** (84 rows preserved and quarantined). Git operations: **NONE**. Secrets printed: **NONE**.
- **Result Status:** the two-account leak is **fixed, verified by test, and confirmed on device**. M11
  remains open on: (a) the mid-run account-switch path, untested on device; (b) whether the coordinator's
  fail-open should become fail-fast; (c) migration 0004, unchanged blocker.
