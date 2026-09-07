# FitQuest — Demo Day Checklist

Practical steps only. Backend is local (laptop) — the phone must be able to
reach it. Never claim something worked if it did not.

## BEFORE DEMO

1. Start the backend from `apps/api` with the project venv:
   `apps/api/.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. Verify `GET http://localhost:8000/health` → `{"status":"ok"}`.
3. Verify `GET http://localhost:8000/api/v1/coach` → HTTP 200 with a coaching message (takes up to ~30 s; a 502/503 means the AI provider/key is broken — see CONTINGENCY).
4. Confirm the phone and the laptop are on the same network and the phone can reach the backend (`BACKEND_BASE_URL` in `apps/app/.env` points at the laptop's LAN IP, e.g. `http://192.168.x.x:8000/`).
5. Confirm MapTiler: `MAPTILER_API_KEY` present in `apps/app/.env`; if the key is dead the map silently falls back to keyless OpenFreeMap (still works — do not claim MapTiler tiles if you see the fallback).
6. Confirm AI provider config WITHOUT printing keys: `.env` at repo root must contain `GEMINI_API_KEY`; if `LLM_PROVIDER=agentrouter`, also `AGENTIC_API_KEY` + `AGENTROUTER_BASE_URL`. Run step 3 as the live check.
7. Install/launch the APK on the Samsung demo phone (already installed: `com.example.mobileapp`).
8. Verify runtime permissions are granted (location, activity recognition, notifications). If not: Home → Start Run → "Grant Permissions".
9. Phone charged above ~30%, screen brightness up, media volume up (TTS speaks via media volume).

## DEMO FLOW

1. Cold-launch the app → Home ("Welcome" header, level/streak, Today's Activity, Daily Operations).
2. Scroll: Territory card (hexes controlled), Daily Quests, Recent Expeditions (activity history).
3. Tap **Start Run** → map screen (hex grid, STANDBY).
4. Tap **Start Capture** → "ACTIVE RUN", FGS notification appears ("FitQuest" notification, id 1001).
5. Walk outside until the phone has a GPS fix — hexes highlight, steps count, HUD updates (Current Hex stops saying "Scanning...").
6. Tap **Stop & Finish** → "🎉 Run Completed!" summary with "✓ Synced with server".
7. Tap **View Hub & Stats** → Home: new session row in Recent Expeditions; scroll to the coach card.
8. Point out the **"⚡ Live coaching"** card — the fresh message generated from this run's sync (grounded-chip = RAG).
9. **Rank tab** → server leaderboard, "YOU" on devuser.
10. TTS: the live coaching message is spoken automatically when it arrives (media volume). If it was already spoken during step 7, that is the demonstration — it speaks once per new message.
11. Profile / Trophies tabs: level, XP, streaks, achievements.

## CONTINGENCY

- **Backend down** → restart uvicorn (BEFORE DEMO step 1), then tap Retry on any error card. The run flow itself still works offline (summary will say "Saved offline — provisional XP").
- **AI provider unavailable / quota (429→502)** → the coach cards show a graceful "unavailable" state with Retry; do not fake coaching text. Tell the audience the fallback is intentional. The rest of the demo (run, sync, map, leaderboard) is unaffected.
- **Live push does not arrive** → show the pull-based coach card ("✨ Personal advice") and say it is the same pipeline, pulled instead of pushed. Do not pretend a push arrived.
- **No GPS fix indoors** → demo the UI live (HUD, map, FGS), then show the pre-existing session history and leaderboard as the evidence of real captures. Never claim a capture that didn't happen on screen.
- **Map tiles blank** → that is the OpenFreeMap fallback (or no network): say the map degrades gracefully; hex overlays still render.
