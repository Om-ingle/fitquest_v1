# FitQuest — Software Requirements Specification (SRS)

**Document purpose:** This file is the persistent source of truth for Claude Code and developers working on FitQuest.

**Primary implementation goal:** Turn the existing working Android single-player FitQuest application into a genuinely working, backend-connected, AI-enabled fitness game. The system should be functional and demonstrable end-to-end, with enough technical quality to support the project's research claims, but it is **not** intended to be enterprise/production-grade infrastructure.

**Important:** This document combines:
1. the actual current repository state,
2. the supplied FitQuest research paper/design,
3. the implementation plan agreed for the current build.

Where the research paper describes capabilities that are not currently implemented, this SRS distinguishes **current reality** from **target implementation**.

---

# 1. Project Identity

## 1.1 Project Name

**FitQuest**

## 1.2 Product Type

A territory-based, gamified fitness application for Android.

## 1.3 Core Idea

FitQuest turns physical movement into game progress.

The intended loop is:

```text
Walk / Run
    ↓
Activity + GPS data
    ↓
On-device H3 conversion
    ↓
Territory / game progress
    ↓
XP / quests / achievements / leaderboard
    ↓
Personalized AI coaching
    ↓
More motivation to continue
```

## 1.4 Central Product Differentiators

FitQuest combines:

- real-world fitness activity,
- H3-based geographic territory gameplay,
- gamification and progression,
- backend-backed shared game state,
- AI-assisted personalized recommendations/coaching,
- privacy-oriented handling of location data.

The **Web3/blockchain feature is not part of the current implementation scope**. A future integration point may remain, but it must not drive current engineering decisions.

---

# 2. Current State vs Target State

This distinction is critical.

## 2.1 Current Reality

The existing Android application is the strongest/most complete part of the repository.

The current app has a working offline/single-player flow involving:

- Kotlin
- Jetpack Compose
- Voyager navigation
- Room
- GPS/location tracking
- step sensing
- MapLibre
- Uber H3
- H3-based hex capture
- XP / levels / streaks
- daily quests
- achievements
- profile/dashboard

The current application is largely local-first.

## 2.2 Current Backend Reality

The FastAPI backend exists but is not integrated with the Android client.

Known current problems include:

- Android has an API interface but no actual Retrofit client setup/DI registration.
- The Android app does not currently perform network calls to the backend.
- Authentication is a hardcoded development stub.
- The map viewport query does not properly honor its bounding box.
- The backend uses SQLite in the current code rather than the desired hosted PostgreSQL architecture.
- Migrations are missing.
- Leaderboard endpoint is missing.
- Some backend tables/models are dead or incomplete.
- Backend tests are missing.

## 2.3 Current AI Reality

There is currently **no AI/ML/RAG implementation in the repository**.

There is no functioning:

- recommendation service,
- LLM integration,
- RAG pipeline,
- embeddings/vector search,
- Redis cache,
- WebSocket AI coaching pipeline.

These are build targets.

## 2.4 Target State

The immediate target is:

```text
Existing Android App
        +
Supabase PostgreSQL
        +
FastAPI backend
        +
Real Android ↔ backend integration
        +
Real shared H3 territory/game state
        +
Real leaderboard
        +
AI recommendation layer
        +
RAG
        +
Gemini/OpenRouter LLM
        +
Real-time coaching
```

---

# 3. Scope of This Build

## 3.1 In Scope

### A. Existing Android game

Preserve and improve the existing implementation:

- onboarding
- activity tracking
- GPS
- step tracking
- H3 indexing
- H3 hex capture
- map
- XP
- levels
- streaks
- quests
- achievements
- profile/dashboard

### B. Backend

Build/fix:

- FastAPI service
- PostgreSQL/Supabase connection
- database schema
- migrations
- users/dev-user support
- activity/run synchronization
- H3 territory persistence
- map viewport queries
- game-state synchronization
- leaderboard
- quests/data endpoints needed by the app
- consistent server-side game rules

### C. Android ↔ Backend

Implement actual:

- Retrofit
- OkHttp
- dependency injection/network registration
- configurable backend URL
- request/response DTOs
- run sync
- map data retrieval
- game-state synchronization
- error/retry handling appropriate for an MVP

### D. AI

Build:

- user/activity context construction
- recommendation logic
- RAG
- LLM provider abstraction
- Gemini and/or OpenRouter integration
- personalized coaching output

### E. Real-time coaching

Build:

- meaningful coaching triggers
- WebSocket delivery
- Android handling
- text-to-speech / voice presentation using a simple practical approach

### F. Validation

Perform genuine end-to-end testing on the working flows.

---

# 4. Explicitly Out of Scope

## 4.1 Web3 / Blockchain

Do NOT build, redesign, or spend current effort on:

- blockchain services
- smart contracts
- NFT minting
- wallet integration
- marketplace
- Base blockchain
- IPFS
- ERC-721
- ERC-2981

The research paper includes these concepts, but the current project plan intentionally postpones Web3.

Keep the architecture clean enough that it can be integrated later.

## 4.2 Authentication

Authentication is intentionally postponed.

For the initial build, use the existing development-user concept or an equivalent safe development mechanism.

Do not block backend/AI development on:

- signup UI
- login UI
- OAuth
- production JWT architecture
- password reset
- session management

Authentication will be a later phase.

## 4.3 Enterprise Infrastructure

Do not over-engineer the project with:

- Kubernetes
- complex service meshes
- unnecessary microservices
- Kafka for every event
- enterprise observability stacks
- complicated deployment pipelines
- distributed infrastructure that is not needed for the working MVP

A clean modular FastAPI backend is preferred.

## 4.4 Production-Scale ML Infrastructure

Do not build:

- large distributed training clusters
- complex feature stores
- elaborate MLOps systems
- unnecessary model-serving infrastructure

The AI needs to work reliably and be technically defensible.

---

# 5. Product Requirements

## 5.1 User Activity

The system shall support a user performing a walking/running activity.

The application should record the activity session locally and synchronize relevant information to the backend.

Relevant information can include:

- session identifier
- start/end time
- steps
- distance
- active minutes
- captured H3 cells
- XP/game result

Exact fields should be finalized from the existing models before changing the schema.

## 5.2 Location Privacy

Raw GPS coordinates should remain on-device whenever possible.

Preferred flow:

```text
GPS coordinate
      ↓
H3 conversion on Android
      ↓
H3 cell identifier
      ↓
Backend
```

Do not introduce unnecessary transmission/storage of raw latitude/longitude.

## 5.3 H3 Territory System

H3 is a real existing core of the Android application.

Known implementation detail:

- H3 resolution: **10**

The backend must treat H3 cell identifiers as the primary spatial game object.

Core requirements:

- persist ownership/state of H3 cells
- associate captures with users
- support territory lookup
- support map viewport retrieval
- support shared state between users
- support future capture/defend/steal logic if retained from current backend rules

## 5.4 Map

The Android application uses MapLibre.

The map should be able to display:

- current map area
- locally relevant H3 cells
- server-backed territory ownership where available
- the user's territory
- other users' territory where multiplayer data is available

The backend viewport endpoint must actually honor the requested geographic/viewport constraints.

## 5.5 Gamification

The system should maintain:

- XP
- levels
- streaks
- daily quests
- achievements

The backend should become authoritative for shared/competitive state once synchronization is implemented.

## 5.6 Leaderboard

The current hardcoded/fake leaderboard must be replaced with real backend data.

Initial implementation should be simple and stable.

Possible ranking dimensions:

- XP
- territory count
- steps

Use one clearly defined primary ranking metric initially.

The same metric must be used consistently by backend and frontend.

---

# 6. Backend Requirements

## 6.1 Backend Technology

**FastAPI + Python**

## 6.2 Database

**Supabase-hosted PostgreSQL**

Supabase is the hosted platform.

PostgreSQL is the actual relational database technology.

Use this as the central server-side source of truth.

## 6.3 Local Android Database

Keep:

**Room**

Room continues to support:

- offline/local persistence
- local activity state
- local game UI state
- temporary synchronization state

Conceptually:

```text
Android Room
   = local/offline state

Supabase PostgreSQL
   = central/server state
```

## 6.4 Backend Domain Structure

Recommended modular organization:

```text
apps/api/
├── app/
│   ├── api/
│   │   └── routers/
│   │       ├── users.py
│   │       ├── runs.py
│   │       ├── map.py
│   │       ├── quests.py
│   │       ├── leaderboard.py
│   │       └── coaching.py
│   │
│   ├── models/
│   ├── schemas/
│   ├── services/
│   │   ├── run_service.py
│   │   ├── territory_service.py
│   │   ├── leaderboard_service.py
│   │   ├── quest_service.py
│   │   └── coaching_service.py
│   │
│   ├── ai/
│   │   ├── context.py
│   │   ├── recommendation.py
│   │   ├── rag.py
│   │   └── llm.py
│   │
│   ├── db/
│   └── core/
│
├── migrations/
├── tests/
└── requirements.txt
```

This is a recommended organization, not a command to rewrite the repository blindly. Preserve existing conventions where they are clean.

---

# 7. Database Specification

## 7.1 Core Entities

The logical model should include some or all of:

```text
User
UserProfile
RunSession
CapturedHex
HexOwnership
Quest
UserQuest
Achievement
UserAchievement
```

AI-related entities can be added later:

```text
AIRecommendation
CoachingEvent
KnowledgeDocument
KnowledgeChunk
```

Exact table names should be decided after inspecting the current models.

## 7.2 Relationships

Conceptually:

```text
User
 ├── UserProfile
 ├── RunSession
 ├── UserQuest
 ├── UserAchievement
 ├── HexOwnership
 └── AIRecommendation
```

```text
RunSession
 └── captured H3 cells
```

```text
Quest
 └── UserQuest
```

```text
Achievement
 └── UserAchievement
```

## 7.3 Database Rules

- Use proper foreign keys.
- Use indexes for frequently queried fields.
- Add migrations.
- Do not depend on manually executing a seed script to make production-like tables exist.
- Avoid destructive schema migration behavior for persistent user data.
- Keep development seed data separate from production schema creation.

## 7.4 PostgreSQL / Supabase

The backend shall connect using environment variables.

Do not hardcode:

- database URLs
- passwords
- API keys
- LLM keys
- Supabase secrets

Recommended categories:

```text
DATABASE_URL
SUPABASE_URL
SUPABASE_KEY
GEMINI_API_KEY
OPENROUTER_API_KEY
AI configuration
```

Use only variables that are actually required by the implementation.

---

# 8. Data Synchronization

## 8.1 Core Sync Flow

```text
Android
  ↓
Complete Run
  ↓
Create sync payload
  ↓
FastAPI
  ↓
Validate
  ↓
Update PostgreSQL
  ↓
Calculate authoritative game result
  ↓
Return updated state
  ↓
Android Room/UI
```

## 8.2 Offline-Friendly Behavior

The Android application may complete a run without internet.

Recommended behavior:

```text
Run completed
    ↓
Store locally in Room
    ↓
Attempt sync
    ↓
Success → mark synchronized
    ↓
Failure → retain pending sync
    ↓
retry later
```

Do not make the entire activity-tracking experience dependent on continuous internet connectivity.

---

# 9. Game State Authority

Once backend sync is introduced:

```text
Android
   = local UI + temporary/offline state

FastAPI
   = business rules

Supabase PostgreSQL
   = persisted authoritative server state
```

For competitive features:

**Server state wins.**

This avoids client/server contradictions.

Current code has inconsistent XP rules between client and backend. The final implementation must use one clearly defined formula.

---

# 10. H3 / Territory Requirements

## 10.1 On-Device Processing

The preferred architecture is:

```text
Fused GPS
   ↓
Uber H3
   ↓
H3 Resolution 10
   ↓
hex_id
```

Only the H3 identifier and required activity metadata should leave the device.

## 10.2 Territory Ownership

Logical state:

```text
hex_id
owner_user_id
capture_time
game metrics
```

The implementation may retain additional fields already used by the repository.

## 10.3 Multiplayer Behavior

Target behavior:

```text
Player A captures H3 cell
       ↓
Supabase
       ↓
Player B requests viewport
       ↓
Player B sees A's territory
```

This is the minimum viable multiplayer territory experience.

## 10.4 Capture Logic

The project may retain the existing backend turf-war concepts:

- capture
- defend
- steal

Do not invent new game rules unless needed to make the existing game coherent.

---

# 11. AI System

## 11.1 Goal

AI is not a generic chatbot.

It must use real FitQuest data and context.

The system should answer questions such as:

- What challenge should this user attempt?
- What coaching message is appropriate right now?
- How can we encourage continued activity based on actual progress?

## 11.2 AI Inputs

Possible context:

```text
User profile
Today's activity
Recent activity
Steps
Distance
Active minutes
Current run state
XP
Level
Streak
Territory progress
Quest progress
Recent behavior
```

Only send the minimum useful context to the model.

## 11.3 AI Pipeline

Target:

```text
FitQuest activity data
        ↓
Context builder
        ↓
Recommendation
        ↓
RAG retrieval
        ↓
Prompt/context assembly
        ↓
LLM
        ↓
Coaching response
```

---

# 12. Recommendation Engine

## 12.1 MVP Stage

Start with a deterministic or score-based recommendation engine.

Example concept:

```text
Low recent activity
    → easier challenge

Consistent activity
    → medium challenge

Strong recent activity
    → harder challenge
```

This stage is intended to provide a useful working system before ML training data exists.

## 12.2 Research-Aligned ML Stage

The supplied research paper proposes XGBoost for challenge completion/recommendation.

If there is sufficient real or appropriately disclosed evaluation data, an XGBoost model can be added.

Do not fabricate a dataset or pretend an ML model was trained on real users when it was not.

The recommendation service should be designed so that a rule-based implementation can later be replaced by an ML model.

Example abstraction:

```text
RecommendationService
      │
      ├── RuleBasedRecommendation
      └── XGBoostRecommendation (later)
```

---

# 13. RAG System

## 13.1 Purpose

RAG should ground coaching in a curated fitness/coaching knowledge base and provide relevant contextual information to the LLM.

## 13.2 Target Pipeline

```text
Knowledge documents
       ↓
Chunking
       ↓
Embeddings
       ↓
pgvector
       ↓
Similarity search
       ↓
Relevant chunks
       ↓
Prompt + FitQuest context
       ↓
LLM
```

## 13.3 Database

Use the same Supabase PostgreSQL instance with pgvector where practical.

Do not create a second vector database unless there is a real need.

## 13.4 Important Accuracy Rule

Do not claim that RAG exists before the retrieval pipeline actually exists.

Do not call a plain LLM prompt “RAG”.

---

# 14. LLM Provider Layer

## 14.1 Provider Abstraction

Implement:

```text
LLMService
   │
   ├── GeminiProvider
   └── OpenRouterProvider
```

The rest of the application should not depend directly on one provider.

## 14.2 Provider Selection

Select the initial provider based on:

- current availability
- usable free/low-cost limits
- response quality
- latency
- reliability
- structured output capability
- ease of development

The initial target is a practical student/MVP setup, not an expensive enterprise LLM.

## 14.3 Fallback

If a primary provider is unavailable, use another configured provider where practical.

Do not build complicated routing until basic generation works.

---

# 15. Real-Time AI Coaching

## 15.1 Trigger-Based Architecture

```text
Activity event
    ↓
Trigger evaluation
    ↓
AI context
    ↓
Recommendation/RAG
    ↓
LLM
    ↓
WebSocket
    ↓
Android
```

## 15.2 Triggers

The research direction contains multiple trigger concepts.

For the MVP, implement a small, meaningful trigger set first.

Potential triggers:

- workout start
- activity milestone
- territory capture
- streak milestone
- quest progress milestone
- workout completion

Exact trigger definitions must be validated against the existing app/business logic before implementation.

## 15.3 Voice Output

Preferred MVP:

```text
AI response text
      ↓
Android TTS
      ↓
spoken coaching
```

The AI backend does not need to produce raw audio initially.

---

# 16. WebSocket Requirements

WebSocket is only necessary for the real-time coaching portion.

Do not replace all REST APIs with WebSockets.

Use:

```text
REST
→ normal application data

WebSocket
→ real-time coaching events
```

The system should handle:

- connect
- send coaching event
- receive response
- disconnect
- simple reconnect/failure handling

---

# 17. Redis

Redis is optional for the first functional milestone.

Add it only where it creates a measurable benefit, such as:

- short-lived coaching cache
- repeated response caching
- trigger/session state
- rate limiting

Do not introduce Redis solely because the research paper mentioned it.

---

# 18. API Design

The exact existing routes should be preserved/reused where appropriate.

Known logical routes include:

```text
GET  /health

POST /api/v1/users
GET  /api/v1/users
GET  /api/v1/users/{id}
PATCH /api/v1/users/{id}

POST /api/v1/runs/sync

GET  /api/v1/map/viewport
GET  /api/v1/map/{hex_id}
GET  /api/v1/map/user/{user_id}

POST /api/v1/map
PATCH /api/v1/map/{hex_id}

POST /api/v1/quests
GET  /api/v1/quests
GET  /api/v1/quests/{id}

GET /api/v1/leaderboard

AI/coaching routes to be added during AI implementation.
```

These are based on the current backend structure; exact request/response models should be derived from the repository.

Do not add endpoints merely for theoretical completeness.

---

# 19. Android Networking

Implement actual networking around the existing app.

Target:

```text
Retrofit
  +
OkHttp
  +
DI
  +
configurable base URL
```

The existing `FitQuestApi` should be evaluated and reused rather than recreated unnecessarily.

Required first network flows:

1. run sync
2. map/territory fetch
3. leaderboard fetch
4. profile/progress synchronization

AI/WebSocket is added later.

---

# 20. UI Integration

Do not redesign the entire Android UI.

Prioritize:

### Home
Display server-backed progress where appropriate.

### Run
Continue the current tracking experience.

### Map
Show synchronized territory state.

### Leaderboard
Replace fake rivals with backend results.

### AI
Add a minimal, natural coaching presentation without disrupting the current experience.

### Profile
Sync relevant server state.

---

# 21. Error Handling

## Backend

Return clear errors for:

- invalid payloads
- unknown users
- invalid H3 IDs
- database failure
- AI provider failure
- unavailable services

## Android

Handle:

- backend unreachable
- timeout
- network loss
- sync failure
- stale data
- WebSocket disconnect

The user should still be able to track an activity locally even when network access is unavailable.

---

# 22. Security Baseline

Even though authentication is deferred, do basic safe engineering:

- secrets in `.env`
- never hardcode API keys
- do not commit `.env`
- validate incoming payloads
- parameterized/ORM database queries
- do not expose stack traces to users
- avoid logging sensitive location data
- minimize raw location handling

This is **basic application security**, not an enterprise identity system.

---

# 23. Testing Strategy

## 23.1 Unit Tests

Add tests for important business logic:

- XP calculation
- territory logic
- recommendation logic
- trigger evaluation
- data validation
- RAG retrieval
- AI response formatting

## 23.2 API Tests

At minimum:

- health
- user operations
- run sync
- map viewport
- territory lookup
- leaderboard
- AI endpoint(s)

## 23.3 End-to-End Test

This is the most important test.

```text
Android phone
    ↓
Start run
    ↓
GPS / steps
    ↓
H3 capture
    ↓
Finish run
    ↓
API sync
    ↓
Supabase update
    ↓
updated XP/territory
    ↓
leaderboard update
    ↓
Android UI
```

## 23.4 AI End-to-End Test

```text
Real user activity
    ↓
Backend context
    ↓
Recommendation
    ↓
RAG retrieval
    ↓
LLM
    ↓
Response
    ↓
Android
    ↓
TTS/display
```

A feature is not considered complete merely because an endpoint returns HTTP 200.

---

# 24. Definition of Done

A feature is **DONE** only when:

1. code exists,
2. backend/client integration exists where required,
3. data flows correctly,
4. errors are handled reasonably,
5. the feature can be demonstrated,
6. important paths are tested,
7. documentation/claims match actual behavior.

Example:

### AI is NOT DONE

```text
POST /ai → "Good job!"
```

### AI IS DONE

```text
Real FitQuest activity
→ real context
→ recommendation
→ retrieval
→ actual LLM
→ useful FitQuest-specific response
→ Android
→ user sees/hears it
```

---

# 25. Research Paper Alignment

The supplied paper describes a broader architecture involving:

- Android application
- H3 privacy-preserving location abstraction
- blockchain/NFT territory ownership
- microservice backend
- Kafka
- XGBoost
- RAG
- AI coaching
- PostgreSQL
- Redis

The paper is the **research/design reference**, not a command to implement every technology immediately.

For the current build:

| Research concept | Current plan |
|---|---|
| Android app | Keep / improve |
| H3 | Core + retain |
| Territory gameplay | Core |
| Backend | Build/integrate |
| PostgreSQL | Use Supabase |
| RAG | Build |
| AI coaching | Build |
| LLM | Gemini/OpenRouter |
| XGBoost | Optional research-aligned stage |
| Redis | Optional when useful |
| Kafka | Not required for MVP |
| Blockchain | Deferred |
| NFT marketplace | Deferred |
| IPFS | Deferred |

The paper's architecture therefore becomes:

**research target/reference → practical MVP implementation**

rather than:

**implement every paper technology regardless of need**.

---

# 26. Paper Claims vs Implementation Claims

The project must never make claims stronger than the implementation.

Examples:

### Correct

> “The system implements H3-based spatial abstraction on the Android device.”

when this is actually implemented.

### Incorrect

> “The system has privacy-preserving decentralized blockchain ownership”

if Web3 is not included in the current build.

### Correct

> “The prototype includes an AI-assisted recommendation and RAG-based coaching pipeline.”

only after those components actually exist.

### Incorrect

> “The model achieved X% accuracy”

without an actual documented evaluation.

---

# 27. Architecture Overview

## 27.1 Target Practical Architecture

```text
                         ┌──────────────────────┐
                         │     Android App      │
                         │ Kotlin / Compose     │
                         │ H3 / MapLibre / Room │
                         └──────────┬───────────┘
                                    │
                              REST / WebSocket
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       FastAPI        │
                         │                      │
                         │ Users                │
                         │ Runs                 │
                         │ Territory            │
                         │ Gamification         │
                         │ Leaderboard          │
                         │ AI Orchestration     │
                         └───────┬───────┬──────┘
                                 │       │
                          ┌──────┘       └──────────┐
                          ▼                          ▼
                ┌──────────────────┐       ┌──────────────────┐
                │ Supabase         │       │ AI Layer         │
                │ PostgreSQL       │       │ Recommendation   │
                │                  │       │ RAG              │
                │ Game data        │       │ LLM Provider     │
                │ User data        │       └───────┬──────────┘
                │ H3 ownership     │               │
                │ pgvector         │               ▼
                └──────────────────┘        Gemini/OpenRouter
```

## 27.2 Local + Server Data

```text
                  ANDROID
                     │
          ┌──────────┴───────────┐
          ▼                      ▼
       Room DB              FastAPI API
   local/offline                 │
                                ▼
                         Supabase PostgreSQL
```

---

# 28. Detailed AI Architecture

```text
                FitQuest Event
                     │
                     ▼
              Context Builder
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
 User/activity state        Recent behavior
        │                         │
        └────────────┬────────────┘
                     ▼
            Recommendation Engine
                     │
                     ▼
              Recommended Goal
                     │
                     ▼
               RAG Retriever
                     │
                     ▼
              Relevant Knowledge
                     │
                     ▼
          Prompt / Context Assembly
                     │
                     ▼
                  LLM
            ┌────────┴────────┐
            ▼                 ▼
          Gemini         OpenRouter
            │                 │
            └────────┬────────┘
                     ▼
             Coaching Response
                     │
              REST / WebSocket
                     │
                     ▼
                 Android
                     │
                     ▼
                    TTS
```

---

# 29. Data Flow — Complete User Scenario

## Scenario: User Goes for a Run

```text
1. User starts activity.
2. Android requests/uses allowed location and sensor data.
3. GPS position is converted to H3 resolution-10 cell.
4. H3 cell is used for local territory logic.
5. Activity session is stored in Room.
6. User finishes run.
7. App attempts synchronization.
8. FastAPI validates the run.
9. Backend updates PostgreSQL.
10. Territory ownership/game state is updated.
11. XP/quest/achievement state is updated.
12. Updated state is returned to Android.
13. Leaderboard state reflects the new server state.
14. AI context builder receives the updated user/activity state.
15. Recommendation layer selects an appropriate challenge/guidance.
16. RAG retrieves relevant coaching information.
17. LLM generates a contextual coaching message.
18. Message is returned/delivered.
19. Android displays or speaks the message.
```

---

# 30. Recommended Development Order

## Milestone 1 — Database

- create Supabase project
- configure environment
- connect FastAPI
- create schema
- add migrations
- seed test data
- verify CRUD

**Exit condition:** backend can reliably read/write real Supabase data.

## Milestone 2 — Backend Core

- clean current FastAPI
- run sync
- H3 ownership
- map viewport
- leaderboard
- game-state consistency

**Exit condition:** backend logic works independently.

## Milestone 3 — Android Integration

- Retrofit
- OkHttp
- DI
- base URL
- run sync
- map sync
- leaderboard sync

**Exit condition:** phone → backend → Supabase → phone works.

## Milestone 4 — Multiplayer Core

- shared territory state
- real leaderboard
- server-authoritative XP/game rules

**Exit condition:** one user's changes can be observed through server-backed state.

## Milestone 5 — AI Context

- activity history query
- user context builder
- recommendation interface

**Exit condition:** AI receives actual FitQuest data.

## Milestone 6 — LLM

- provider abstraction
- Gemini/OpenRouter
- structured response
- error/fallback handling

**Exit condition:** real contextual AI response generated.

## Milestone 7 — RAG

- knowledge base
- chunks
- embeddings
- pgvector
- retrieval
- grounded prompt

**Exit condition:** response actually uses retrieved knowledge.

## Milestone 8 — Real-Time Coaching

- trigger engine
- WebSocket
- Android event handling
- TTS

**Exit condition:** activity event can produce real coaching during the user experience.

## Milestone 9 — Quality Pass

- tests
- error handling
- sync failures
- offline behavior
- AI reliability
- UI polish
- documentation

## Milestone 10 — Research Alignment

Compare final implementation against the paper.

Mark:

```text
IMPLEMENTED
PARTIAL
DEFERRED
NOT IMPLEMENTED
```

Update claims accordingly.

---

# 31. Existing Known Issues to Address

The existing repository audit identified several important issues.

## Critical

- Android/backend disconnected.
- Backend requirements contain dependency issues.
- Authentication is a development stub.
- Leaderboard is fake.

## Important

- map viewport ignores its own bounds
- client/server XP differs
- fresh backend does not reliably initialize schema
- migrations are missing
- run/hex backend models have incomplete usage
- backend tests are missing

## Android Quality

- pause currently does not fully stop tracking
- emulator sensor support is incomplete
- today's steps calculation can undercount
- local Room migration strategy is destructive

These should be fixed where they affect the current build's success.

---

# 32. Development Rules for Claude Code

Claude Code MUST follow these rules.

## Rule 1 — Read Before Changing

Before implementing a subsystem:

- inspect the existing code,
- identify existing models/services/interfaces,
- reuse what is sound,
- avoid duplicate implementations.

## Rule 2 — Do Not Rewrite the Android App

The Android app is already the strongest part.

Prefer incremental integration.

## Rule 3 — Do Not Invent APIs

Use the existing routes/models when practical.

Add new routes only when required by an actual feature.

## Rule 4 — Do Not Invent Data

Do not fabricate:

- users
- activity history
- ML metrics
- AI evaluation numbers
- leaderboard performance
- research results

Development seed data is acceptable only when clearly labeled as test data.

## Rule 5 — Test Important Paths

After implementation, actually exercise the affected flow where the environment allows it.

## Rule 6 — Keep Scope Tight

Do not implement Web3.

Do not implement production authentication yet.

Do not build Kafka or complex microservices unless a concrete requirement later appears.

## Rule 7 — Keep Architecture Modular

Even though this is an MVP, code should be separated sensibly:

- API
- services
- database
- AI
- integration

## Rule 8 — Protect Secrets

Never commit secrets.

## Rule 9 — Preserve Existing Working Behavior

A backend/AI feature must not casually break the local Android game.

## Rule 10 — Document Actual State

When something is incomplete, state it explicitly.

---

# 33. Definition of Project Success

The project is successful when a reviewer can perform a realistic demonstration:

```text
Open FitQuest
     ↓
Start run
     ↓
Move / generate activity
     ↓
H3 hexes are captured
     ↓
Finish activity
     ↓
Data syncs to backend
     ↓
Supabase contains the run/game state
     ↓
Map reflects shared/server territory
     ↓
Leaderboard shows real server-backed data
     ↓
Backend builds context from actual user history
     ↓
AI generates a personalized recommendation
     ↓
RAG contributes relevant knowledge
     ↓
LLM response reaches Android
     ↓
User sees/hears useful coaching
```

That is the target demo.

---

# 34. Final Product Positioning

FitQuest should be presented as:

> A privacy-aware, H3-based, territory-oriented gamified fitness application with a real backend and AI-assisted personalized coaching.

For the current project version:

- H3 is real and central.
- Android gameplay is real.
- Backend is being integrated.
- AI is being built.
- RAG is being built.
- LLM is being integrated.
- Web3 is deferred.
- Authentication is deferred.
- The system is MVP/research-prototype quality rather than enterprise production infrastructure.

---

# 35. Final Source-of-Truth Rule

When there is a conflict:

### Priority 1
**Actual repository implementation**

### Priority 2
**This SRS and current project decisions**

### Priority 3
**Research paper as intended/research architecture**

The research paper must not override actual implementation reality.

The SRS must not be used to justify claiming something that does not work.

If repository evidence and this document disagree, investigate and update the document or implementation rather than silently assuming.

---

# 36. One-Page Claude Code Context

## WHAT ARE WE BUILDING?

FitQuest is an Android gamified fitness app. The Android app already works locally with Kotlin/Compose, Room, GPS, steps, MapLibre, and Uber H3 resolution-10 territory capture. It also has XP, levels, streaks, quests, achievements, and a dashboard.

## WHAT IS MISSING?

The Android app is not actually connected to the FastAPI backend. The backend is incomplete. There is no AI/RAG/LLM implementation.

## WHAT ARE WE BUILDING NOW?

1. Supabase-hosted PostgreSQL backend.
2. FastAPI backend cleanup and schema.
3. Android ↔ FastAPI integration.
4. Real run/H3 territory synchronization.
5. Real leaderboard.
6. Server-authoritative game state.
7. AI recommendation system.
8. RAG.
9. Gemini/OpenRouter LLM integration.
10. Real-time WebSocket coaching.
11. Android TTS/display.
12. End-to-end testing.

## WHAT ARE WE NOT BUILDING NOW?

- Web3
- NFT
- blockchain
- marketplace
- IPFS
- Kafka
- enterprise microservices
- production authentication
- complicated MLOps

## WHAT IS THE DATABASE?

```text
Android Room
       ↓ sync
FastAPI
       ↓
Supabase PostgreSQL
       │
       └── pgvector for RAG
```

## WHAT IS THE CORE ARCHITECTURE?

```text
Android
  ↓
FastAPI
  ↓
Supabase PostgreSQL

FastAPI
  ↓
AI Context
  ↓
Recommendation
  ↓
RAG
  ↓
Gemini/OpenRouter
  ↓
WebSocket
  ↓
Android
```

## WHAT DOES "DONE" MEAN?

Not merely “the code compiles”.

A feature is done when it works end-to-end and can be demonstrated with real data.

## MOST IMPORTANT PRINCIPLE

**Build what we can actually verify and demonstrate. Do not over-engineer and do not overclaim.**
