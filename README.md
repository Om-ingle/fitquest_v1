# FitQuest

A gamified fitness app where you capture hexagonal territories by walking through them.

## How It Works

1. The map is divided into hexagons using [Uber H3](https://h3geo.org/).
2. Walk inside a hexagon — your steps are counted via the device's step-counter sensor.
3. The user with the most steps in a hex becomes the "king" of that territory.

## Getting Started

### Prerequisites

- Android Studio (latest stable)
- Android device or emulator (API 24+)
- A [MapTiler](https://www.maptiler.com/) API key

### Setup

1. Copy `.env.example` to `.env` inside `apps/app/`:
   ```bash
   cp apps/app/.env.example apps/app/.env
   ```
2. Add your MapTiler API key to the `.env` file:
   ```
   MAPTILER_API_KEY=your_key_here
   ```
3. Open `apps/app/` in Android Studio and sync Gradle.

> Never commit a `.env` file containing real credentials — `.env` is gitignored.

### Backend (FastAPI + Supabase PostgreSQL)

The backend lives in `apps/api/` and connects to Supabase-hosted PostgreSQL
via `DATABASE_URL` (environment variable or `.env` — never committed). See
[`apps/api/README.md`](apps/api/README.md) for setup, migrations (Alembic),
and test instructions:

```bash
cd apps/api
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head      # create/update the database schema
uvicorn app.main:app --reload
```

> The Android app is backend-connected: completed runs sync to the FastAPI
> backend (server-authoritative XP/territory), the map fetches shared
> territory, the leaderboard and AI coach cards are server-backed, and live
> coaching arrives over WebSocket with native TTS. Backend integration is
> verified end-to-end; see `FitQuest_SRS.md` and `docs/` for details.

### H3 Native Libraries

The `h3-android` dependency requires native `.so` libraries. They are manually bundled in:
```
fitquest/src/main/jniLibs/
├── arm64-v8a/libh3-java.so
└── armeabi-v7a/libh3-java.so
```

> **Note:** If you need to support x86/x86_64 emulators, you'll need to extract and add the corresponding `.so` files from the H3 Android AAR.

## Emulator & Testing Notes

### Step Counter Sensor

Android emulators **do not** have a hardware step-counter sensor (`TYPE_STEP_COUNTER`),
and the old dev simulators (`DevLocationSimulator`/`DevStepSimulator`) are no
longer wired into the app. Use a **real device** to exercise the step-capture
flow — the full demo (run → H3 capture → sync → AI coach → TTS) is verified
on a physical Samsung device.

### Location on Emulator

Even without the dev location simulator, you can inject GPS coordinates into the emulator:
- **Android Studio:** Extended Controls (⋯) → Location → set lat/lng and click "Send"
- **ADB:** `adb emu geo fix <longitude> <latitude>`

### H3 Resolution

The H3 resolution is currently set to **10** (hex edge ≈ 65 m) for faster capture feedback during development.
This may be changed after field testing — see the `TODO(TESTING)` comment in `HexCaptureEngine.kt`.

### Grid Ring Size

The nearby hex grid shows **k=2** rings around the user (~19 hexes).
This can be tuned in `HexCaptureEngine.kt` — see the `TODO(TESTING)` comment.

## Architecture

```
com.example.mobileapp/
├── core/
│   ├── capture/          # HexCaptureEngine — combines location + steps → hex ownership
│   ├── data/local/       # Room database, DAO, repository for persisted hex data
│   ├── dev/              # Dev simulators (mock GPS, mock steps) — DEBUG only
│   ├── geo/              # H3 hex indexer, GeoJSON mapper
│   ├── model/            # Domain models (GeoPoint)
│   ├── permissions/      # Runtime permission helper
│   └── sensors/          # Location & step sensor managers
├── di/                   # Koin dependency injection module
├── features/capture/     # CaptureScreenModel (Orbit MVI), CaptureState
├── ui/
│   ├── capture/          # CurrentRunScreen (Compose + MapLibre)
│   └── theme/            # Material 3 theme
└── docs/                 # Detailed technical documentation
```

## Documentation

For a deeper dive into specific components, refer to the following guides:

- [Architecture](docs/architecture.md) — Patterns, DI, and data flow.
- [Hex System](docs/hex-system.md) — Uber H3, resolutions, and GeoJSON mapping.
- [Capture Engine](docs/capture-engine.md) — Tracking sessions and capture mechanics.
- [Sensors & Simulators](docs/sensors-and-simulators.md) — Hardware sensor management and dev tools.
- [Persistence](docs/persistence.md) — Room database and repository pattern.
- [Backend Schema](docs/backend-schema.md) — FastAPI + Supabase database tables & API contracts.

## Similar Apps & References

FitQuest draws inspiration from real-world GPS exer-gaming, territory conquest mechanics, and spatial indexing research:

### Commercial & Community Precedents
- **[Run An Empire](https://www.runanempire.com/)**: Pioneering location-based strategy running game where players claim and fortify territories by running through them, earning passive yields and competing against local players.
- **[Turf (Turfgame)](https://turfgame.com/)**: Swedish outdoor GPS zone control game where players take zones by visiting them, earn points per hour held, and compete in monthly reset rounds ("Bonanzas").
- **[INTVL](https://intvl.com/)**: GPS running and cycling app based on territory looping—closing a geometric loop claims all territory enclosed within the perimeter.
- **[Stride](https://stride.run/)**: Urban turf war runner rewarding consistency and segment defense across real neighborhood blocks.
- **[StepEarth](https://stepearth.app/)**: Gamified step-based map conquest focused on daily walking habits and district leaderboards.
- **[Strava Local Legends](https://support.strava.com/hc/en-us/articles/360044558231-Local-Legends)**: Rolling 90-day segment effort frequency crown, directly analogous to FitQuest's "King of the Hill" defense score.
- **[Niantic Ingress / Pokémon GO](https://ingress.com/)**: Global geospatial partition models (Google S2 cells), control fields, portals, and faction rivalry.

### Open-Source Implementations & Geospatial Tooling
- **[getout.space](https://github.com/kondulak10/getout.space)**: Open-source web app turning Strava GPX activities into captured Uber H3 hexagonal cells.
- **[TerraRun](https://github.com/manjunath5513/Dev-Challenge)**: Territory-capture running application using H3 spatial utilities and GPS loop polygon fill.
- **[Runiverse](https://runiverse.fit)**: Gamified running platform utilizing Uber H3 spatial indexing for live conquest.
- **[Uber H3 Core](https://github.com/uber/h3)**: Discrete global hexagonal hierarchical spatial index providing uniform adjacency distances.
- **[MapLibre Native Android](https://github.com/maplibre/maplibre-native)**: Open-source vector tile map rendering engine used for client visualization.

### High-Value Feature Roadmap (Derived from Precedents)
1. **Territory Decay & Seasons**: Periodic defense score depreciation (e.g., 5-10% weekly decay or monthly round resets) to prevent dormant kings from monopolizing zones permanently.
2. **Loop Enclosure Capture**: Allowing runners to capture entire interior hex clusters by closing a continuous boundary loop.
3. **Factions & Clubs (Turf Wars)**: Team-based territory control (e.g., Faction colors, neighborhood running clubs).
4. **Fog of War**: Darkened viewport that reveals conquered and visited hexes, encouraging exploration.
5. **Anti-Cheat & Anti-Spoofing**: Velocity threshold caps (>25 km/h) and step delta vs. displacement validation to protect against driving/cycling fraud.
6. **Outbox Pattern Offline Sync**: Queued Room database sync for runs completed without cellular connectivity.

## License

See [LICENSE](LICENSE).