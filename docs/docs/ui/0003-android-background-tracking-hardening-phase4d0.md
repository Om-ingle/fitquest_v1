# ADR 0003: Android Background Tracking Hardening & Recovery (Phase 4D.0)

Status: implemented and device-verified 2026-09-06. Adds a persistent
foreground service + run notification, a single-row Room checkpoint,
process-death recovery, and timestamp-authoritative elapsed time to the
FitQuest Android run tracker. Verified end-to-end on a physical device
(Samsung SM-M325F, Android 13 / API 33, serial RZ8R90661CF).

This phase did **not** touch RAG / AI-coach / WebSocket / backend /
Supabase. WebSocket/real-time coaching/TTS/AI remains a separate, later
phase per the SRS.

---

## 1. IMPLEMENTATION SUMMARY

Background and lock-screen tracking previously depended on a visible
Compose screen and an in-memory capture engine, so a Home press, lock, or
process kill could silently lose or mis-account a run. Phase 4D.0 makes
the active run **durable and recoverable**:

- A **foreground service** (`RunTrackingService`) keeps the process alive
  and foreground for the whole run, with a persistent low-importance
  "🏃 FitQuest Run Active" notification whose tap returns to the run screen.
- A **single-row Room checkpoint** (`active_run`) is written by the service
  every 5 s (never per sensor event) and on start/pause/resume/finish —
  without replacing the existing `RunSessionEntity` history path.
- **Process-death recovery**: if the process dies mid-run, the checkpoint
  survives; on relaunch the app routes to the run screen and surfaces a
  "Previous run found" banner with **Resume Run** / **Discard Run**. A
  completed run is never re-recovered.
- **Elapsed time is timestamp-derived** (`now − startedAt − pausedAccumulated`),
  so it survives process death, doze, and re-launch; the UI only ticks.
- All prior components are reused: `HexCaptureEngine`/`StepSensorManager`
  (live steps/hexes), `CaptureState`/`CaptureScreenModel`/`CurrentRunScreen`,
  Room/DAOs/repos, `RunSyncer`, `PermissionManager`, `AppModule`, and the
  manifest's existing service/permission wiring.

## 2. FILES CHANGED

Modified (9 files, `+524 −176`):

- `fitquest/src/main/AndroidManifest.xml` — POST_NOTIFICATIONS permission,
  `singleTop` on MainActivity, `android:foregroundServiceType=location`.
- `fitquest/src/main/java/com/example/mobileapp/MainActivity.kt` — cold-start
  routing (`resolveStartScreen`) + `onNewIntent` notification deep-link.
- `.../core/capture/HexCaptureEngine.kt` — `resumeTracking(...)` re-seed API.
- `.../core/data/local/FitQuestDatabase.kt` — version 4, `active_run` table,
  `MIGRATION_3_4`.
- `.../core/permissions/PermissionManager.kt` — POST_NOTIFICATIONS on 13+.
- `.../di/AppModule.kt` — DAO/repo/service/singletons.
- `.../features/capture/CaptureScreenModel.kt` — full lifecycle rewrite
  (start/resume/pause/finish/recovery).
- `.../features/capture/CaptureState.kt` — `pendingRecovery` field.
- `.../ui/capture/CurrentRunScreen.kt` — recovery overlay + buttons.

New:

- `.../core/data/local/ActiveRunEntity.kt`, `ActiveRunDao.kt`,
  `ActiveRunRepository.kt` — single-row checkpoint.
- `.../core/run/RunTiming.kt`, `RunMetrics.kt`, `HexStepsCodec.kt`,
  `ActiveRunStatus.kt`, `ActiveRunStatusResolver.kt`,
  `RunNotifications.kt`, `ActiveRunController.kt`, `RunTrackingService.kt`.
- `.../res/drawable/ic_stat_run.xml` — small notification icon.
- `src/test/java/com/example/mobileapp/core/run/RunTimingTest.kt`,
  `HexStepsCodecTest.kt`, `ActiveRunStatusResolverTest.kt`.

## 3. ROOM / RECOVERY DESIGN

- `active_run` is a **single-row** table (rowid 1). Saving uses a REPLACE
  insert keyed on the run id, so a stray duplicate write overwrites rather
  than duplicating — the primary duplicate guard for Room.
- Writes happen at most every 5 s (the service tick) plus explicit
  transitions (start, pause, resume, finish). Sensor events never write.
- `runId` + `startedAt` are persisted. `startedAt` is the source of truth;
  `pausedAccumulated` is persisted on every pause/resume so elapsed time
  survives process death.
- On relaunch after death, `MainActivity.resolveStartScreen` routes straight
  to `CurrentRunScreen` when an unrecovered checkpoint exists. The recovery
  banner shows steps/distance/elapsed from the checkpoint; **Resume Run**
  re-seeds the capture engine at the checkpoint and keeps the **same runId**
  (one run, not two); **Discard Run** clears the checkpoint.
- Finish clears the row inside a mutex after the periodic writer is joined
  (see §4), so a finished run can never be re-recovered — verified by a cold
  relaunch after finish landing on the hub with no banner.
- `active_run` never replaces `RunSessionEntity`; finished runs still flow
  through the existing Room → `RunSyncer` path into history/backend.

## 4. FOREGROUND SERVICE DESIGN

`RunTrackingService` (`android:foregroundServiceType="location"`):

- Started via `ContextCompat.startForegroundService` **from the foreground**
  (the Start button), so no `ACCESS_BACKGROUND_LOCATION` is required.
  `START_STICKY`: if the system re-creates it while a run is active it
  re-goes-foreground; if no run is active it stops cleanly.
- Is the **sole** periodic (5 s) checkpoint writer and notification owner.
  The capture engine is deliberately *not* started by the service — the
  ScreenModel owns engine lifecycle; the service reads the singleton
  `ActiveRunController` (runId + `RunTiming`) and `HexCaptureEngine` (live
  steps/hexes) each tick, so it keeps working after the screen is disposed.
- A worker coroutine plus a `Mutex` serialise every Room write with the final
  clear, so a finish can never be re-ordered after a stray periodic write.
  Teardown runs on its own `shutdownScope` (survives `onDestroy`) and
  `join()`s the worker before `stopForeground(REMOVE)` + `cancel`, closing the
  window where an in-flight `notify()` could re-post the ongoing notification
  after it was removed (a real leak seen during testing; fixed and re-verified).
- Stops only via an explicit `ACTION_STOP` delivered with `startService`
  (`stopService` alone does not deliver `onStartCommand`).

## 5. NOTIFICATION BEHAVIOR

- Channel `fitquest_run_active` (`IMPORTANCE_LOW`, silent, ongoing) created on
  service start.
- Notification id `1001`, small icon `ic_stat_run`, title "🏃 FitQuest Run
  Active", content "`N` steps • `X.XX` km", refreshed each 5 s tick.
- `POST_NOTIFICATIONS` (API 33+) is requested in the normal permission flow.
  If the user denies it, `notify()` no-ops but the foreground service still
  runs — steps/elapsed/checkpoint are unaffected, only the visible card.
- Tap → `PendingIntent` to `MainActivity` with
  `ACTION_OPEN_RUN` + `SINGLE_TOP|CLEAR_TOP`. Warm: `onNewIntent` pushes the
  run screen if the user navigated away. Cold: `resolveStartScreen` routes to
  the run screen. Both return to the active run, not the hub.
- Removed on finish (verified: gone from the live notification list after
  Stop & Finish).

## 6. ELAPSED-TIME DESIGN

- **Timestamps are the source of truth, not an accumulating counter**:
  `elapsed = now − startedAt − pausedAccumulated`; while paused, `elapsed` is
  frozen at `now − pausedSince − pausedAccumulated`.
- Persisted `startedAt` and `pausedAccumulated` make elapsed correct across
  process death, doze, and re-launch; the UI may tick at 1 s but the service
  re-derives from timestamps on every checkpoint.
- Verified on-device: a 25 s pause froze elapsed then excluded the paused
  window on resume (`pausedAccumulated = 64 974 ms`), and a lock-screen run's
  elapsed (413 s) equaled the full wall-clock delta.

## 7. TEST RESULTS

Focused JVM unit tests (all new logic):

| Suite | Tests |
|---|---|
| `RunTimingTest` (elapsed, pause/resume freeze) | 10 |
| `HexStepsCodecTest` (checkpoint round-trip) | 6 |
| `ActiveRunStatusResolverTest` (recovery decision matrix) | 4 |
| pre-existing suites (regression) | 41 |
| **Total** | **61** |

0 failures, 0 errors, 0 skipped.

## 8. REAL DEVICE RESULTS

Device: Samsung SM-M325F, Android 13 (API 33), RZ8R90661CF. Every row below
is a real, observed outcome on the physical device.

| Check | Result | Evidence |
|---|---|---|
| Foreground tracking (normal run) | **PASS** | FGS + notification live; checkpoint written; finish cleaned up |
| Notification (persistent card) | **PASS** | Live in notification list during all background/lock phases; gone after finish |
| Notification tap → run screen | **PASS (intent-level)** | App backgrounded mid-run → fired the notification's `ACTION_OPEN_RUN` PendingIntent → returned to `CurrentRunScreen` showing **ACTIVE RUN** with live elapsed (05:18), not the hub. `setContentIntent` wiring is statically confirmed; a literal finger-tap on the shade card was not performed because uiautomator could not dump Samsung's shade (see §12) |
| Background tracking (Home) | **PASS** | 3-min poll from launcher: `isForeground` stayed true, notification present, checkpoint elapsed advanced with wall clock (25→115→211 s), steps 90→131 captured while app was on launcher; finish synced 131 steps / 10:19 |
| Screen-lock / doze tracking | **PASS** | Run tracked through screen-off/doze: elapsed 413 s = full wall delta; steps 0→92 and 2 hexes captured while dark; finish synced 92 steps / 2 hexes / +60 XP. Mid-lock adb sampling unavailable (USB dropouts) — continuity proven by end state |
| Process-death recovery | **PASS** | `am force-stop` killed the process (FGS/notification gone); Room checkpoint survived (48 steps, runId `d043bb7b`). Relaunch → full "Previous run found" banner (48 steps / 0.04 km / 02:53), NOT a fresh run. Resume re-seeded at 48 steps, elapsed continued (→03:53), FGS restarted with the **same runId** — no duplicate |
| Elapsed-time correctness | **PASS** | TEST 1: 25 s pause froze then excluded paused window (active 05:34 = 334 s vs 399 s wall); TEST 3: elapsed = wall delta across doze; TEST 4: elapsed continued across process death |
| Room persistence | **PASS** | `active_run` row survived force-stop; post-finish `active_run` = 0 rows; three-file SQLite snapshots confirmed each state |
| Normal run completion | **PASS** | Finish produced exactly one synced session; cold relaunch after finish → hub, no banner (completed-run-not-recovered) |
| Backend sync | **PASS** | Each finished test run appeared in **Recent Expeditions** on relaunch (TEST 3: 92 st / +2 hexes / +60 XP; TEST 4: 48 st / +1 hex / +10 XP; deep-link run: 0 st, `isSynced=1`) |
| Duplicate tracking / listeners / writes / completion | **PASS** | No duplicate FGS (monitor start guarded), no duplicate Room rows (single-row REPLACE + mutex), ONE session per run across force-stop and resume (same runId, original `startedAt` preserved), no duplicate listeners after re-entry |

Final cleanup run: `Stop & Finish` cleared the notification (live list),
stopped the service, cleared `active_run` (0 rows), advanced `run_sessions`
14 → 15 with the **original** `startedAt` preserved and `isSynced = 1`.

## 9. BUILD RESULT

`./gradlew :app:assembleDebug` — **BUILD SUCCESSFUL** (fresh re-run after the
final service-teardown fix; APK built and installed to the device for all
verification). 46 tasks, up-to-date on the confirmation run.

## 10. TEST RESULT

`./gradlew :app:testDebugUnitTest` — **BUILD SUCCESSFUL**.
**12 suites, 61 tests, 0 failures, 0 errors, 0 skipped.** 20 of the tests are
new (Phase 4D.0 logic); 41 are pre-existing regression suites, all green.

## 11. GIT STATUS / DIFF SUMMARY

Working tree contains exactly this phase's changes (no stray files):

```
 M apps/app/fitquest/src/main/AndroidManifest.xml
 M apps/app/fitquest/src/main/java/com/example/mobileapp/MainActivity.kt
 M apps/app/fitquest/src/main/java/com/example/mobileapp/core/capture/HexCaptureEngine.kt
 M apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/FitQuestDatabase.kt
 M apps/app/fitquest/src/main/java/com/example/mobileapp/core/permissions/PermissionManager.kt
 M apps/app/fitquest/src/main/java/com/example/mobileapp/di/AppModule.kt
 M apps/app/fitquest/src/main/java/com/example/mobileapp/features/capture/CaptureScreenModel.kt
 M apps/app/fitquest/src/main/java/com/example/mobileapp/features/capture/CaptureState.kt
 M apps/app/fitquest/src/main/java/com/example/mobileapp/ui/capture/CurrentRunScreen.kt
?? apps/app/fitquest/src/main/java/com/example/mobileapp/core/data/local/ActiveRun{Dao,Entity,Repository}.kt
?? apps/app/fitquest/src/main/java/com/example/mobileapp/core/run/           (8 files)
?? apps/app/fitquest/src/main/res/drawable/ic_stat_run.xml
?? apps/app/fitquest/src/test/java/com/example/mobileapp/core/run/          (3 test files)
?? docs/docs/ui/evidence-4d0/                                               (device screenshots)
```

`git diff --stat`: **9 files changed, +524 / −176**. No RAG/AI-coach/
WebSocket/backend/Supabase files are touched by this phase.

## 12. REMAINING LIMITATIONS

- **Notification shade tap verified at the intent level, not a literal tap.**
  The notification's `setContentIntent` is wired to the same
  `ACTION_OPEN_RUN` intent that was exercised and shown to return to the run
  screen, but uiautomator could not dump Samsung's notification shade
  (persistent "could not get idle state"), so the physical shade tap was not
  automated. A manual finger-tap of the live card is the one remaining
  confirmation.
- **Screen-off adb sampling is unreliable** (Samsung doze drops the USB
  connection to "unauthorized"). Lock-screen continuity was therefore proven
  by end state, not by mid-lock checkpoints.
- **No run yields XP when 0 steps/0 distance** (deep-link run finished with 0
  steps — correct, since nobody walked; not a defect).
- Notification is shown only while the run is active; if the user revokes
  notification permission mid-run the card disappears but tracking continues
  (documented Android behavior, intended).
- Time between "elapsed shown on screen" and actual finish can drift if the
  screen is briefly unreachable mid-teardown; final duration is always the
  timestamp-derived value persisted in the session row.
