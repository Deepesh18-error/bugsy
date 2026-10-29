# Bugsy (CodeMafia) — implementation and release guide

> Planning document and local setup guide. The React preview and the FastAPI,
> Redis, Yjs, and runner integrations are implemented through Phase 13. The
> The four-player lobby, readiness and chat were manually exercised locally;
> the full live match remains to be validated by players. The local Docker
> runner passes its Python and C++ isolation checks.
> Production match start is blocked until the authored
> challenge bank has passed its release review. See [quality](docs/quality.md),
> [release checklist](docs/release-checklist.md), and
> [deployment review](docs/deployment.md).

## Current local setup

The workspace uses `frontend/` for React + JavaScript + Vite, `backend/` for
Python + FastAPI, `services/editor-sync/` for Yjs, `services/runner/` for the
Linux code judge, and `infra/` for local Redis and service profiles.

### Start Redis

From the repository root in PowerShell:

```powershell
docker compose -f infra/compose.yaml up -d redis
```

### Start the FastAPI backend

In a PowerShell window:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

If creating the virtual environment reports that `ensurepip` failed, bootstrap pip using the system Python and then install into the project environment:

```powershell
deactivate
python -m pip --python .venv\Scripts\python.exe install pip
python -m pip --python .venv\Scripts\python.exe install -r requirements-lock.txt
```

The API has a `/health` endpoint at `http://127.0.0.1:8000/health` that checks Redis, room endpoints under `/api/rooms`, and interactive schemas at `/docs`. See [HTTP rooms and guest identity](docs/http-api.md). The example backend variables are in `backend/.env.example`; set them in the shell or pass `--env-file .env` to Uvicorn if you create a local `backend/.env`.

### Start the React frontend

In another PowerShell window:

```powershell
cd frontend
npm ci
npm run dev
```

Vite prints the local URL after startup. A separate local match preview is
available from the welcome screen. A live room needs Redis, FastAPI, and the
editor service; official Python and C++ tests also need the isolated runner and a
shared signing key. See [quality](docs/quality.md) for service and test commands.
`frontend/.env.example` records the API base URL; use the same hostname for
Vite and FastAPI during local development so the guest cookie works.

### Test a C++ match locally

With `infra/.env` configured for development and draft content, rebuild and
start the runner from the repository root:

```powershell
docker compose -f infra/compose.yaml --env-file infra/.env --profile editor --profile runner up -d --build
```

Keep the backend and frontend running, open four separate browser sessions,
and have each player vote for **C++**. The shared `challenge.cpp` asks players
to repair `subtract_score` and `reset_score`. Use **Run official tests** to
check the saved revision; C++ has no browser-side Python check. A repaired
revision can be finalized by a civilian. The impostor can test a regression
inside `subtract_score` after a passing baseline and try to keep that revision
until the round deadline. C++ compilation and execution happen in separate
bounded, networkless runner jails; neither requires a C++ compiler on Windows.

### Dependency maintenance

- Frontend direct dependencies are declared in `frontend/package.json`; `frontend/package-lock.json` records the resolved dependency tree.
- Backend direct dependencies are declared in `backend/requirements.txt`; `backend/requirements-lock.txt` records the installed, pinned dependency set. Update the lock after changing backend dependencies.
- `.gitignore` excludes local environments, secrets, generated output, and Redis data. The root README remains trackable.

## 1. Project goal

Build a polished browser game for small groups of developers. Players join a private room and work together on a timed Python challenge. Civilians try to repair the program and pass its tests. One hidden impostor tries to sabotage the code without being identified. Players can chat, call a meeting, and vote to eject a suspect.

The project should be a strong interview portfolio piece, so it should show more than a themed UI: clear domain modeling, authoritative multiplayer state, concurrency design, recovery from disconnects, secure code execution, accessibility, and a well-explained deployment architecture.

### Reference evidence

- The supplied images show a pixel-art lobby with five slots, ready indicators and a host crown; category voting; private civilian/impostor reveals; a four-round coding arena with a timer, shared editor, tests, chat and emergency meeting; and discussion/voting with a skip option.
- The [creator page](https://buymeacoffee.com/codemafia_game) describes the premise as four to five developers working together with an impostor among them.
- The original team's [Devpost submission](https://devpost.com/software/codemafia) describes three to five players, Python TODO challenges, civilians winning by passing all tests or voting out the impostor, and the impostor winning through sabotage objectives or by surviving until time expires. It names React, TypeScript, Vite, Zustand, Framer Motion, PartyKit, Monaco and Pyodide as the hackathon implementation stack.
- The selected stack for our project is **React for the frontend and Python for the main backend**. We will use FastAPI for HTTP and WebSockets. Supporting infrastructure may include Redis, Docker Compose, a Yjs sync service, and an isolated code runner. Those support the core stack; they do not replace it.

The creator page and Devpost differ on the minimum player count. The screenshots indicate four rounds, but do not fully specify how those rounds relate to match victory. The rules below are proposed defaults and must be confirmed in Phase 0 before the game engine is written.

## 2. Design rules for the difficult situations

These are core gameplay and system behaviors, not edge cases to postpone.

### 2.1 A civilian makes a harmful edit by mistake

The server should judge code behavior, not guess a player's intent. A failed test says the current shared code has a problem; it does **not** prove that the last editor is an impostor. Any player may make a mistake, and the impostor may make a change that looks reasonable.

The arena should make recovery ordinary and low-cost:

- Show test results against the exact code revision they ran. Mark a result stale as soon as the shared document changes.
- Keep a recent, server-stored change history with player attribution and timestamps. Provide undo/restore to a known good revision, while retaining later edits so the group can recover without losing unrelated work.
- Show visible collaborator cursors/presence and a concise activity feed. These are evidence for discussion, not an accusation score.
- Let tests fail and pass repeatedly. A previously passing test is not permanently locked; otherwise an impostor can be prevented from sabotaging repaired code and the team loses a useful way to see regressions.
- Keep the test harness and expected results immutable to clients. A player's browser can show friendly local feedback, but only an authoritative result can settle a match.

### 2.2 Two civilians edit at the same time

Use **Monaco + Yjs** for the shared document once we reach the editor phase. Yjs is a CRDT: concurrent document updates can converge across clients. This solves text synchronization and dropped/reordered update concerns; it does not guarantee that simultaneous edits express sensible program logic. Two edits to the same expression can still produce a surprising or broken result. [Yjs describes its shared types and concurrent update behavior](https://docs.yjs.dev/).

For usability, show each person's cursor/name and a soft “editing this function” presence marker. Do not globally freeze the editor or lock an entire file because one test passed. If playtesting shows same-function collisions are common, add an optional short lease for that function, with automatic expiry and an override path. The impostor must be able to edit code under the same rules as everyone else.

Do not make game state itself a Yjs document. The Python backend remains the one authority for roles, phase, timer, vote totals, meeting eligibility, tests accepted as official, and win conditions. A Yjs sync service may be a small Node service because the standard Yjs WebSocket provider is Node-oriented; this remains an editor transport, while FastAPI remains the game backend. Every editor document must be authorized for a member of the corresponding room and scoped to that room and round. [Yjs y-websocket provider](https://docs.yjs.dev/ecosystem/connection-provider/y-websocket).

### 2.3 The impostor needs a fair way to sabotage

Do not disable code after it passes. “Green once” is a reversible candidate result. Civilian victory requires **all required tests passing together on the current authoritative code revision**, followed by a connected living player finalizing that exact revision before the round deadline. Any edit clears the candidate and requires a new official run.

Give the impostor a private, measurable objective tied to the challenge, such as making a specific method return an incorrect result or causing a named test to fail. The server checks objective completion against the actual shared code/test result; the client cannot claim completion. Objectives should reward a subtle, valid-looking change, not arbitrary editor interference. An objective can be recorded as completed at a verified revision, while the current test state can still recover. If objective completion itself ends the game, make that rule explicit and give civilians a clearly communicated chance to notice and vote before completion.

### 2.4 Two changes arrive at nearly the same time

Yjs merges editor document updates. The backend processes game commands one at a time per room (single writer / serialized event loop) and validates each command against the latest phase and player state. Test jobs run on immutable source snapshots with revision IDs. If revision 42 is being tested while the editor advances to revision 43, the result for 42 may be displayed as historical feedback but cannot decide the winner for 43.

All commands have a request ID for retry deduplication. The server uses monotonic event sequence numbers and absolute UTC deadlines. A duplicate ready, vote, meeting request, or timer callback cannot apply twice. Redis Pub/Sub may later fan out events across processes, but it is at-most-once; clients recover from missed notifications by requesting a fresh authorized room snapshot. [Redis delivery semantics](https://redis.io/docs/latest/develop/use-cases/pub-sub/).

## 3. Proposed MVP rules baseline

These defaults make the rules implementable. Lock them in or edit them during Phase 0.

1. **Players:** 4–5 per room; exactly one impostor. Start only with four or five connected/eligible players.
2. **Match:** up to four rounds as suggested by the screenshots. Each round has a fresh editor document and coding deadline; choose a category once at match start. Until the reviewed bank expands, a version-pinned challenge may be reused with a clean starter document in later rounds. Keep the same roles through the match. The fourth round is the final deadline.
3. **Civilian victory:** either the impostor is ejected, or a living player finalizes a current revision whose official run passed all required tests before the round deadline.
4. **Impostor victory:** all assigned objectives remain verified on the unchanged current revision at a round deadline, with at least 30 seconds to respond after verification; alternatively the impostor survives through the final deadline of round four. A failed challenge advances to the next round rather than ending the match after round one. If an objective and ejection resolve at nearly the same instant, server event ordering decides which committed transition wins; recommended rule is that a completed ejection wins if it commits first.
5. **Category vote:** everyone gets one vote. A tie or no votes falls back to a deterministic category (for example, a seeded/random choice among tied categories) and the server announces the result. No client chooses the winner.
6. **Meetings:** one emergency meeting per player per match, usable only while alive and in a coding round, plus a short server-side global cooldown. Meeting pauses the coding deadline. Discussion and voting have separate deadlines.
7. **Player vote:** one vote per eligible living player; allow skip. A tie or all-skip/no-vote yields no ejection. Do not reveal individual ballots before the vote closes. Show only the result needed for deduction after resolution.
8. **Disconnects:** retain a disconnected player for a short reconnect grace window. They cannot issue actions while offline. At the deadline, their missing vote counts as abstention. After grace, mark them departed and remove meeting/ready eligibility. On reconnect, restore their own role privately and send the current public snapshot.
9. **Host:** host can start when requirements are met and can end the room. If host leaves, transfer host to the oldest connected player. A room with no active players expires.
10. **Content:** Live development/staging offers Python object-oriented and back-end challenges plus a C++ score challenge. Other categories remain preview-only until authored. No accounts, ranked matchmaking, public room browser, voice chat, or user-generated challenge builder in the first release.

## 4. Architecture and boundaries

```text
React + JavaScript + Vite
  ├── Screens, lobby, editor, chat, accessibility, connection UI
  ├── Monaco + Yjs client for shared code and cursors ───────┐
  └── Optional Pyodide Web Worker for local feedback         │
             │ HTTPS / WebSocket                             │ WebSocket
             ▼                                               ▼
FastAPI + Uvicorn (authoritative game service)      Optional Yjs sync service (Node)
  ├── Guest identity, rooms, game state machine       document updates and cursors only
  ├── Phases, roles, deadlines, votes, chat policy
  ├── Versioned room protocol and authorized snapshots
  └── Runner orchestration; never executes player code
       │                   │
       ▼                   ▼
Redis (room lookup/TTL, later coordination)   Isolated code runner
       └── optional multi-instance pub/sub     (separate sandbox/queue)
```

The Yjs sync service in the diagram is independent of the Python game service. It handles collaborative document synchronization, not game rules. We will add it only when the editor phase needs it. The code runner is also a separate trust boundary: do not start arbitrary player Python inside FastAPI or in an ordinary application container.

### Technology decisions

- **Frontend:** React + JavaScript + Vite; Monaco for the IDE in a later phase. The server snapshot is authoritative.
- **Backend:** Python + FastAPI + Uvicorn; HTTP for create/join/reconnect and WebSocket for live room commands/snapshots.
- **Collaborative editor:** Yjs + Monaco binding and an authorization-gated WebSocket provider. Do a small feasibility spike before selecting the hosting/deployment shape. Yjs prevents text divergence, not logic errors.
- **Redis:** room code index, expiring room data if persistence across a process restart is required, reconnect/session records, and future cross-instance messaging. Start with one API instance and one writer per room. Do not depend on Pub/Sub for durable history.
- **Code feedback:** Pyodide in a Web Worker may run a local preview, with a visible “local feedback” label. Web Workers keep synchronous Python work off the browser UI thread. [Pyodide worker docs](https://pyodide.org/en/latest/usage/webworker.html).
- **Official results:** a separate runner receives a bounded challenge version and immutable code snapshot, then returns structured results. Apply CPU, memory, time, PID and output limits; run non-root, disable network, expose no secrets, and queue/limit concurrent jobs. Docker Compose organizes local services; it does not make hostile code safe by itself. Docker documents container security/resource boundaries and gVisor adds another sandbox layer for supported Linux hosts. [Docker Compose](https://docs.docker.com/compose/intro/compose-application-model/) · [Docker security](https://docs.docker.com/engine/security/) · [gVisor production guide](https://gvisor.dev/docs/user_guide/production/).
- **Persistence:** no PostgreSQL for the first guest MVP. Add a relational database only when we need long-term match history, accounts, moderation records, or durable content management.
- **Deployment:** static frontend hosting plus a Linux container host that supports long-lived WebSockets; managed Redis if needed; separate Yjs and runner services as added. Verify connection timeouts and WebSocket behavior on the chosen host before launch.

### Authoritative vs. client state

| Server is authoritative for | Client may cache/display |
|---|---|
| Player identity and reconnect credential validity | Display name draft and local preferences |
| Room membership, host, ready state, alive/departed state | Temporary modal, selected tab, editor scroll position |
| Phase, deadline, role, category winner | Countdown rendering derived from server deadline |
| Votes, meeting eligibility, ejection and match result | Optimistic button state pending acknowledgement |
| Official test result and sabotage objective completion | Local Pyodide feedback clearly marked provisional |
| Room/document access permission | Cursor location and awareness/presence |

Private role/objective data must never be included in a public room snapshot. The server sends only the connected player’s own private role payload.

## 5. State model and message model

### Game phases

Use an explicit state machine. Recommended phases:

`LOBBY → CATEGORY_VOTE → ROLE_REVEAL → CODING_ROUND → MEETING_DISCUSSION → PLAYER_VOTE → ROUND_RESULT → (CATEGORY_VOTE or GAME_OVER)`

Every transition has a server-owned entry time and deadline where applicable. A phase transition is atomic and idempotent. Timers are computed from an absolute server timestamp, not decremented on clients. Invalid commands in the wrong phase are rejected without changing state.

### Main entities

- **Room:** short code, host player ID, phase, capacity, created/expiry time, current round, public settings.
- **Player:** stable random ID, normalized display name, ready/alive/connected status, joined time, reconnect credential hash/expiry, meeting uses.
- **Private role:** role and, for impostor, assigned objective/progress. Only deliver to that player.
- **Round:** category/challenge version, phase deadlines, editor document identity, current document revision, official test result revision, sabotage objective status.
- **Vote:** voter ID, target or skip, accepted request ID, closed/resolved time. Keep ballot privacy policy explicit.
- **Chat message:** server timestamp, player ID, bounded plain text. Render as text, never HTML.
- **Room event:** sequence number, protocol version, event type, public payload and optional player-specific private payload.

### WebSocket protocol rules

Clients send commands, never state claims. A command includes protocol version, request ID and command type/payload. Examples: `player.ready`, `category.cast_vote`, `editor.request_access`, `meeting.call`, `vote.cast`, `chat.send`, `room.request_snapshot`.

The server derives the player from the authenticated connection; it does not trust a client-supplied player ID, role, deadline, vote count, test result, or objective result. Each command is validated by schema, message size, rate, room phase, player eligibility, and idempotency. Server events include a monotonically increasing room sequence and enough data for clients to reconcile; reconnect always gets a full authorized snapshot before incremental events.

## 6. Detailed phase-by-phase implementation methodology

We will execute these phases in order. Each phase has an objective, work sequence, concrete outputs and an exit gate. We should not build a later phase on top of an unresolved earlier rule or an unstable interface. Small technical spikes are allowed when they answer a defined risk; they should end with a decision and be removed or incorporated cleanly.

### Phase 0 — Product decisions and game rules

**Objective:** turn the reference concept into a ruleset that can be implemented without guesswork.

**Work sequence:**

1. Confirm player range, one-impostor policy, host rights and whether eliminated players remain in chat or can spectate.
2. Confirm four-round structure, when category voting occurs, whether roles persist, what resets at each round, and whether passing tests ends the match immediately.
3. Write exact win conditions and precedence: civilian test win, civilian ejection win, impostor objective win, round timeout and final-match timeout.
4. Specify test semantics: current-revision results, all tests required together, pass regressions, stale results and when an official result commits.
5. Specify impostor permissions/objectives: code edit access, objective count, objective validation, progress visibility, and how a completed objective interacts with a pending vote.
6. Specify category ties, meeting limits/cooldowns, meeting timer behavior, discussion and vote deadlines, skip, tied votes, no votes, disconnected voters and simultaneous deadline/action order.
7. Specify room capacity, duplicate names, host departure, reconnect grace, room expiry and late reconnect behavior.
8. Draw example timelines for an accidental harmful edit, a sabotage, simultaneous edits, tests passing then regressing, reconnect during each phase, and a vote/deadline race.

**Deliverables:** a short rules specification, phase transition table, decisions/assumptions log, challenge data contract and sample match timelines.

**Exit gate:** every possible match ending and phase transition has one unambiguous outcome. The developer approves the proposed defaults in Section 3 or edits them. No implementation starts until this gate is complete.

### Phase 1 — Repository and local developer foundation

**Objective:** make a clean, understandable project that can be run and checked by another developer.

**Work sequence:**

1. The owner initializes Git; the root `.gitignore` is ready for that step.
2. Keep the initial layout to `frontend` for React/Vite, `backend` for FastAPI, and `infra` for local Redis. Add challenge, contract, and service folders when their implementation phases begin.
3. Select supported runtime versions and package managers; commit lockfiles. Set up Python virtual environment/dependency management and Node package management.
4. Add formatting, linting and static type checks for each language. Separate development configuration from production secrets and provide `.env.example` only.
5. Add a Compose file for local Redis. Run Vite and FastAPI with hot reload on the host for easier development; keep Docker for services and later containerized runner work.
6. Defer CI until the project needs automated checks.
7. Write setup, environment variable and troubleshooting instructions.

**Deliverables:** initial folder structure, local start instructions, lockfiles, example config, CI checks, architecture diagram and decision log.

**Exit gate:** a clean clone can start frontend, API and Redis using documented steps; CI runs the same static/build checks; no real secret is stored in the repository.

### Phase 2 — Game UX and visual prototype

**Objective:** validate the entire interaction flow before multiplayer work.

**Work sequence:**

1. Establish reusable visual tokens: pixel font, colors, spacing, borders/shadows, panels, buttons, status indicators and responsive breakpoints. Use original assets/art.
2. Implement welcome/name entry and create/join room forms with validation and error states.
3. Implement lobby with room code, host marker, capacity, player colors/names, ready state and start affordance.
4. Implement category vote, role reveal, coding arena, meeting/discussion/vote, round/match results and rematch flow using mocked data.
5. Add reconnecting, disconnected, room full, invalid/expired code, loading, empty chat and server error states.
6. Ensure narrow screens can still join, vote and read status; editor layout may adapt to a stacked/mobile view.
7. Add keyboard navigation, focus rings, semantic labels, contrast, reduced motion and text/icon companions for color.

**Deliverables:** clickable mock match and a small visual style guide.

**Exit gate:** a new person can follow the fake match without explanation; key states render at desktop and narrow widths; every action has a visible pending/success/error result.

### Phase 3 — Challenge and sabotage content design

**Objective:** ensure the game is fun and measurable before connecting it to multiplayer code.

**Work sequence:**

1. Define a versioned challenge schema: ID/version, category, title/prompt, starter code, methods/functions, visible TODOs, public instructions, test definitions, runtime limits and authored-by metadata.
2. Define tests with stable IDs and clear output. Decide which tests are visible to all, which are hidden from players, and what counts toward civilian victory.
3. Define sabotage objective schema: private description, target function/test, verification predicate, objective progress, completion effect and fairness notes.
4. Author one small example challenge first, with both intentional solution and plausible sabotage paths. Then add a small number across the five reference categories.
5. Review difficulty, Python version compatibility, execution cost and whether each objective is observable without revealing the impostor.

**Deliverables:** schema documentation and a compact, reviewed starter challenge bank; no user-generated content editor.

**Exit gate:** every challenge can be loaded deterministically, has bounded tests, has a known correct solution, and supports at least one fair sabotage objective.

### Phase 4 — Pure Python game engine

**Objective:** implement and reason about game rules independently of networking and UI.

**Work sequence:**

1. Define domain types for room, player, phase, round, vote, objective, deadline and result.
2. Define one transition function per command and phase event. Functions accept current state plus command/time and return either a rejected action or a new state plus emitted domain events.
3. Keep game rules deterministic. Inject random selection/role assignment so scenarios can be replayed.
4. Add server-time deadline evaluation and explicit ordering for action-at-deadline races.
5. Make action application idempotent by request ID; define which request IDs are remembered and for how long.
6. Cover all approved rules as unit scenarios, including duplicate/invalid votes, tie/skip, wrong phase, eliminated/disconnected players, repeated timeout callbacks, role secrecy boundaries, and win precedence.

**Deliverables:** isolated Python domain package, transition documentation and rule-level test suite.

**Exit gate:** the full match can be simulated without FastAPI, Redis, or React; all Phase 0 examples produce the expected state and events.

### Phase 5 — HTTP APIs, guest identity and room persistence

**Objective:** create/join rooms and restore the same guest securely.

**Work sequence:**

1. Define create-room, join-room, resume-player and leave-room HTTP operations with validated request/response schemas.
2. Generate high-entropy player IDs and reconnect credentials; store a hash of the credential and expiry, and rotate/revoke it when appropriate.
3. Generate room codes with sufficient entropy, unique allocation, normalized name handling and rate-limited join attempts.
4. Define full/invalid/expired room responses without leaking extra room data.
5. Store room code lookup and active-room snapshots with TTL in Redis. Start with one API instance as the room writer. Do not claim multi-instance safety yet.
6. Define persistence recovery: what state survives API restart, what happens if Redis is unavailable, and whether an active room can resume or ends cleanly.
7. Add API contract documentation and client types derived from or checked against the backend schema.

**Deliverables:** guest identity model, HTTP API contract, room repository and Redis-backed room lookup/state policy.

**Exit gate:** separate sessions create/join, invalid/full rooms behave clearly, and refresh reconnects the same guest without exposing credentials in URL or logs.

### Phase 6 — WebSocket protocol and authoritative multiplayer

**Objective:** synchronize game state while keeping the server in control.

**Work sequence:**

1. Define protocol version, command envelope, event envelope, request ID, room event sequence, error shape and snapshot shape in `contracts`.
2. Authenticate WebSocket handshake using the reconnect credential through a safe mechanism; validate allowed origins.
3. Route each command to the Python domain engine. Serialize state-changing commands per room and persist accepted state before acknowledging it.
4. Send public events to the room and private payloads only to the intended player. Never broadcast an entire private server object.
5. Add heartbeat, disconnect detection, bounded message size, schema validation, message rate limits and duplicate request handling.
6. On connect/reconnect, send a full authorized snapshot first. Use event sequence gaps to request another snapshot.
7. Add multi-session checks for late, duplicate, malformed, unauthorized and out-of-order messages.

**Deliverables:** versioned protocol, WebSocket gateway, server snapshot/event builder and connection lifecycle handling.

**Exit gate:** multiple sessions stay in the same public phase; a client cannot spoof identity, role, vote totals, test outcomes or deadlines; each player only sees their own secret.

### Phase 7 — Lobby lifecycle and match setup

**Objective:** let a real group form a valid match.

**Work sequence:**

1. Connect the mock lobby UI to create/join APIs and WebSocket snapshots.
2. Implement ready/unready and server-authorized host start; validate minimum player count and required player readiness.
3. Implement host transfer, host end-room, capacity enforcement, duplicate-name policy and abandoned-room TTL.
4. Add category vote, server tally, tie/no-vote fallback and vote deadline.
5. Assign roles after the category vote and deliver per-player private role reveal.
6. Make refresh/reconnect restore lobby readiness and role reveal correctly according to the approved rule.

**Deliverables:** playable online lobby and secure match-start flow.

**Exit gate:** friends on separate browser sessions can create/join/ready/start and receive correct category and private role without state disagreement or role leakage.

### Phase 8 — Collaborative editor and revision recovery

**Objective:** allow the group and impostor to edit the shared challenge at the same time without losing updates.

**Work sequence:**

1. Integrate Monaco with Python syntax highlighting and challenge starter code.
2. Run a small Yjs + Monaco binding spike; decide whether to host the provider as a separate Node service or another compatible provider. Keep game authority in FastAPI.
3. Implement editor room authorization and scope each document to a unique room + match + round. Prevent stale-round connections from modifying the current document.
4. Add names/cursors/awareness and connection/sync status. Awareness never authorizes actions or carries secrets.
5. Track current revision and code snapshots in the game service. Store bounded history with author/time attribution and recovery/restore action.
6. Add revision IDs to test requests/results; stale results cannot affect current win evaluation.
7. Verify same-region and different-region concurrent edits, network interruption, late join and reconnect. Consider optional expiring function-level leases only if UX evidence supports them.

**Deliverables:** collaborative editor, room-round document access control, revision history and restore flow.

**Exit gate:** all clients converge after concurrent edits and reconnect; no edit is silently lost; test results are tied to the tested revision; code remains editable after a test passes.

### Phase 9 — Code feedback and isolated official runner

**Objective:** give fast feedback while ensuring official outcomes cannot be forged or weaponized.

**Work sequence:**

1. Build the runner interface: challenge ID/version, immutable source snapshot, round ID and revision ID in; structured bounded result out.
2. Add a queue and concurrency cap; deduplicate repeated jobs and discard stale results for winner decisions.
3. Run Pyodide in a browser Worker for optional immediate feedback. Label it provisional and keep its code/test payload separate from the trusted server result.
4. Implement the separate Linux runner container. Never execute untrusted code within the FastAPI process or use shell interpolation for player code.
5. Apply hard execution time, CPU, memory, PID, output and filesystem limits; non-root user; read-only minimal filesystem; no network; no secrets; per-run cleanup.
6. Test runaway loops, huge output, malformed Python, import attempts, filesystem access attempts and parallel-job overload.
7. Check whether the selected hosting platform supports the required isolation. Add gVisor or stronger isolation if available and appropriate; document the threat boundary honestly.

**Deliverables:** local fast feedback, runner API/queue, isolated runtime configuration and threat model.

**Exit gate:** official outcomes come only from the runner for the matching revision; malicious or hung submissions return a bounded result without blocking the API or match; the runner cannot reach internal secrets/services.

### Phase 10 — Test lifecycle, sabotage objectives and round progression

**Objective:** make fixing and sabotage a balanced, understandable gameplay loop.

**Work sequence:**

1. Add manual/automatic test-run trigger, debounce/coalescing and status display (queued/running/pass/fail/error/stale).
2. Keep test pass status reversible. Require all required tests to pass together on one current official revision for a civilian test win.
3. Implement objective assignment and private progress. Verify completion against pinned challenge/test definitions and runner output, not client claims.
4. Distinguish test failure feedback from player intent; show attributable edit history without automated accusations.
5. Add restore/undo for accidental or malicious changes. Restore itself is a new revision, so re-run tests.
6. Implement round result and next round: select challenge, reset document, preserve match roles/meeting usage as defined, and set a new server deadline.
7. Resolve objective completion, ejection and final timeout in the approved deterministic order.

**Deliverables:** complete coding-round loop, result panel, sabotage progress and round transition.

**Exit gate:** accidental regression and intentional sabotage both remain recoverable; impostor can still edit after green tests; all winning results are based on server-verified current state.

### Phase 11 — Chat, emergency meetings and votes

**Objective:** complete the social deduction loop.

**Work sequence:**

1. Add bounded plain-text room chat with server timestamps, rate limits, safe rendering and defined delivery during each phase.
2. Implement meeting call eligibility, per-player use count and shared cooldown.
3. Pause/resume coding deadline using server timestamps; ensure repeated meeting transitions cannot pause time twice.
4. Add discussion countdown and ballot UI; server accepts one vote per eligible player, including skip.
5. Keep ballots private until resolution; compute ties/no votes deterministically; eject only once.
6. Define eliminated and disconnected player behavior, then display the result and resume or end the match.

**Deliverables:** chat, meeting, vote and result flow connected to the server state machine.

**Exit gate:** no duplicate vote/ejection; ties and skips follow the rules; timers resume correctly; every client sees the same result.

### Phase 12 — Reconnects, persistence and failure recovery

**Objective:** make a game survive ordinary browser/network failures.

**Work sequence:**

1. Test refresh, tab close/reopen, temporary network loss, expired credentials, host loss and reconnect after grace period.
2. On reconnect, authenticate, rejoin, fetch a fresh authorized snapshot, sync current editor document, then resume incremental events.
3. Persist active room state and deadlines in Redis with TTL; define restart recovery and cleanup semantics. Keep a single active room writer in this release.
4. If using Redis Pub/Sub, assume missed messages are gone; snapshot recovery remains mandatory. Add Redis Streams only if durable event replay is an explicit need.
5. Make timers/jobs safe under duplicate callbacks and process restart; ensure no double round end, vote resolution or runner reward.
6. Add operational behavior for Redis outage and runner outage: clear UI state, bounded retry and safe match pause/forfeit policy from Phase 0.

**Deliverables:** reconnect policy, persisted active-room representation, recovery behavior and operational failure messages.

**Exit gate:** a returning player has the correct phase, deadline, code and own role; server restart/outage follows a defined path without contradictory winners or leaked secrets.

### Phase 13 — Security, accessibility and end-to-end quality

**Objective:** verify the whole game as a real multiplayer product, not just a local happy path.

**Work sequence:**

1. Add backend domain/API tests and frontend component/interaction tests as implementation proceeds; add browser automation for two or more independent players.
2. Cover complete paths: create, join, ready, role assignment, concurrent edit, test, sabotage, meeting, vote, disconnect, reconnect and final result.
3. Cover abuse: invalid schema, forged IDs/roles/results, replayed commands, room-code brute force, message floods, huge chat/code, unauthorized Origin, private payload inspection and runner resource abuse.
4. Review access control for both FastAPI room channels and Yjs editor documents.
5. Check keyboard-only use, focus order, contrast, screen-reader labels, timer announcements, reduced motion and narrow layouts.
6. Review logs for credentials, role data, chat and source code; keep only operational events required for debugging.

**Deliverables:** repeatable quality suite, security review notes, accessibility fixes and release checklist.

**Exit gate:** the complete multi-browser journey passes repeatedly; critical security/accessibility findings are fixed or documented with a release decision.

### Phase 14 — Staging, production deployment and observability

**Objective:** make the game reachable outside the developer's computer and safe to operate.

**Work sequence:**

1. Choose a static host for React and Linux container hosting that explicitly supports long-lived WebSockets.
2. Deploy API, Redis, Yjs provider and runner as separate deployable units only when those services are in use.
3. Configure environment-specific domains/origins, HTTPS/WSS, secrets, resource limits, health checks and room TTL cleanup.
4. Validate WebSocket idle timeout, maximum connection duration, deployment restart behavior and reconnect on the selected host.
5. Add minimal privacy-respecting metrics: room creation, match start/end, reconnect, runner timeout/error and service health. Avoid storing code/chat by default.
6. Document deployment, rollback, backup/restore expectations and how to disable new matches during an incident.

**Deliverables:** staging and production environments, deployment notes, health/metrics dashboard and rollback procedure.

**Exit gate:** players on separate networks finish a match over HTTPS/WSS; deploy/restart and rollback behavior has been verified; no development secret/config is used in production.

### Phase 15 — Closed beta and game balance

**Objective:** learn whether the game is understandable and fun for people who did not build it.

**Work sequence:**

1. Invite a small group and let them play without explaining the UI.
2. Observe time-to-join, time-to-first-edit, confusion around failures/sabotage, meeting usage, challenge completion and disconnect friction.
3. Ask short post-match questions about clarity, fairness and fun. Do not collect source/chat unless there is a clear need and notice.
4. Fix the largest onboarding, balance, challenge-quality and reliability problems; repeat with another group.
5. Update portfolio screenshots, architecture diagram, demo account/room instructions, short gameplay video and technical write-up after the product is stable.

**Deliverables:** beta findings, prioritized follow-up list and interview-ready portfolio presentation.

**Exit gate:** first-time players can complete a match; core metrics and feedback show no blocking reliability or comprehension problem; the project has a clear demo story for interviews.

### Phase 16 — Future expansion (only after beta)

Possible additions: accounts/profiles, persistent match history, more programming languages, ranked matchmaking, public room discovery, voice chat, more roles, custom challenge authoring, moderation tools and multi-instance scaling. Each addition requires its own product/design/security phase; do not add these to the MVP just because the architecture could support them.

### How we will work phase by phase

At the start of each phase, state the goal, scope, dependencies and acceptance gate. Implement only that phase, run its relevant checks, review the changed files and update this plan if evidence changes a decision. Fix gate failures before moving on. A later-phase feature discovered early goes into the backlog unless it blocks the current gate. This keeps progress measurable and makes each stage reviewable.

## 7. Risk and scenario register

| Scenario | Product behavior | Engineering response |
|---|---|---|
| Civilian accidentally breaks a function | Show failing tests and recent edit attribution without accusing anyone | Keep revisions, test the latest revision, support restore/undo |
| Impostor breaks a function after a test passed | Test status regresses; code remains editable; play continues | Never lock passed code; verify the impostor objective on server |
| Two players edit different functions | Both edits appear in the shared document | Yjs sync plus cursors and revisioned test snapshots |
| Two players edit the same lines | Document converges; the result may still be bad code | Show attribution/presence; allow recovery; optional expiring soft lease if needed |
| Test result arrives after newer edits | Mark result stale, do not use for winner | Bind run ID to immutable source revision |
| Impostor claims a sabotage objective in UI | Ignore client claim | Verify objective using server runner and pinned challenge data |
| Client sends a forged role, vote count or test result | Reject it | Server derives identity from authenticated socket; validate every command |
| Player disconnects during edit | Others retain current synced state; lease/presence expires | Reconnect snapshot; preserve server document; do not trust stale local document as source of truth |
| Player disconnects during vote | Keep player for grace period; missing ballot abstains at deadline | Server deadline and explicit eligible-voter snapshot |
| Two vote outcomes tie or everyone skips | No ejection; return to round/result per rules | Resolve atomically with deterministic tie rule |
| Deadline and action happen nearly together | Server event ordering decides one outcome consistently | Use absolute deadlines, one room writer, idempotent transitions |
| FastAPI restarts | Active rooms recover only if authoritative room state was persisted | Define restart behavior; Redis snapshots or end active rooms cleanly in early MVP |
| Redis Pub/Sub subscriber disconnects | Events may be lost | Use Pub/Sub only for live fan-out; read full state after reconnect |
| Player submits a malicious/infinite Python program | Bounded error/timeout; match continues | Separate runner, resource limits, no network/secrets, queue, sandbox hardening |

## 8. Quality and security requirements

- **Identity:** random player IDs and high-entropy reconnect secrets; store credential hashes; rotate/revoke on room expiry; do not rely on a display name as authentication.
- **Room access:** short codes should have sufficient entropy, attempts should be rate-limited, and join errors should not leak room details to guessers.
- **Private information:** role and objective are per-player payloads; public state never contains an impostor ID. Restrict logs and debug snapshots.
- **WebSockets:** allowlist origins; authenticate at handshake; authorize every message; validate schemas; cap bytes and rates; close malformed/abusive connections; expire stale credentials.
- **Chat:** plain text with safe rendering, max length, rate limit; no executable HTML and no unnecessary persistence.
- **Code runner:** do not mount source/secrets/host paths; no network; low-privilege user; resource and output limits; enforce job queue/concurrency; apply a stronger sandbox such as gVisor if supported by target Linux host. Docker isolation needs careful configuration and is not a guarantee against all hostile code.
- **Fairness:** display editor presence/activity to everyone consistently; do not expose roles in shared collaboration metadata; ensure the impostor's restrictions are the same as civilians' unless a rule explicitly says otherwise.
- **Accessibility:** color plus name/icon, keyboard operability, focus state, contrast, screen-readable timers/status, reduced motion and clear text for pixel-themed controls.

## 9. What we are intentionally postponing

Accounts/profiles, ranked matchmaking, public lobby discovery, voice chat, multiple programming languages, user-generated challenge authoring, long-term statistics, moderation tooling and multi-region/multi-instance scaling. These are future directions only after a reliable match loop and closed-beta feedback.

## 10. First vertical slice

The first complete playable milestone should prove the hardest parts with two or more separate browser sessions:

1. Create and join a room; ready and start.
2. Vote a category and privately receive roles.
3. Collaboratively edit the same Python challenge while observing player presence.
4. Run tests against revisioned code and see current vs stale results.
5. Allow a civilian mistake, recover it, and allow an impostor sabotage without locking the file.
6. Call a meeting, chat, vote or skip, and resolve the result once.
7. Disconnect/reconnect and restore the correct role, room phase and code.
8. End with the same authoritative result on every client.

This vertical slice should be prioritized over disconnected polish because it demonstrates the central technical challenge and makes the game testable by real groups.

## 11. External technical references

- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) — WebSocket endpoints and handling connections.
- [Yjs](https://docs.yjs.dev/) and [y-websocket](https://docs.yjs.dev/ecosystem/connection-provider/y-websocket) — collaborative document updates and provider options.
- [Pyodide in a Web Worker](https://pyodide.org/en/latest/usage/webworker.html) — run Python feedback outside the browser UI thread.
- [Redis Pub/Sub](https://redis.io/docs/latest/develop/use-cases/pub-sub/) — live broadcast and its at-most-once delivery limitation.
- [Docker Compose model](https://docs.docker.com/compose/intro/compose-application-model/) and [Docker security](https://docs.docker.com/engine/security/) — local multi-service setup and container security boundaries.
- [gVisor production guide](https://gvisor.dev/docs/user_guide/production/) — an additional sandbox layer for supported Linux deployments.
- [OWASP WebSocket Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html) — origin checks, authorization, limits and validation.

## Current workspace status

The implementation has advanced beyond the original scaffold described in
this historical plan. Git is initialized. Domain rules, room HTTP and
WebSockets, shared editing, official runner integration, chat, votes, reconnect
logic, and automated checks exist. Three selectable draft challenges (Counter 1.1, Stack and Wallet) are authored;
production mode deliberately offers no category until content review. The
four-player live flow, Linux sandbox, and public deployment gates remain open.
The owner has deferred CI/CD. [Deployment review](docs/deployment.md) records
the remaining Phase 14 work and a rollback path.



## October 27 review

See [implementation review](docs/final-review.md) for changes and remaining
release evidence. Sabotage requires a retained passing baseline, an
uninterrupted impostor author chain, target-method-only syntax changes and
bounded assertion failures. The server enforces three credited revisions per
match, a 45-second credit cooldown and a 30-second minimum response window.
Verification never ends a match immediately. Any saved edit clears current
objective verification; spent credits are not refunded.

The shared editor remains freely collaborative. This economy controls
sabotage credit, not all destructive editing. Live playtesting remains needed.
