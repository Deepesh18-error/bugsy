# Phase 5 HTTP rooms and guest identity

The FastAPI service owns room identity and membership. React sends ordinary
JSON requests; Redis stores expiring room snapshots and guest session records.
The browser never receives a reconnect secret in a JSON body or URL. The server
sets an `HttpOnly` cookie named `codemafia_guest`, scoped to `/api/rooms`.

## Operations

All routes are under `/api/rooms`. The interactive, generated contract is at
`/docs` and the machine-readable OpenAPI contract is at `/openapi.json`.

| Method/path | JSON request | Success | Meaning |
| --- | --- | --- | --- |
| `POST /api/rooms` | `{"display_name":"Ada","capacity":5}` (`capacity` may be 4 or 5 and defaults to 5) | `201` with `RoomResponse` | Allocates a cryptographically random eight-character code and makes this guest the host. |
| `POST /api/rooms/join` | `{"room_code":"ABCDEFG2","display_name":"Grace"}` | `200` with `RoomResponse` | Joins a room that is still in the lobby. |
| `POST /api/rooms/resume` | No body; guest cookie required | `200` with `RoomResponse` and rotated cookie | Restores the same player ID after refresh or API restart. |
| `POST /api/rooms/leave` | No body; guest cookie required | `204`, cleared cookie | Applies the game engine's leave transition and revokes this credential. |

`RoomResponse` has one top-level `room` object. The public snapshot includes
`room_code`, `phase`, `capacity`, `expires_at`, `phase_deadline_at`,
`self_player_id`, `selected_category_id`, `round_number`, `challenge_id`,
`challenge_version`, and `players`. Each player has `player_id`,
`display_name`, `connection`, `is_ready`, `is_alive`, and `is_host`.
`own_role` and `own_objectives` refer **only to the authenticated guest**.
Other players' roles and impostor objectives never appear in the response.

The frontend checks the lobby fields at runtime in
`frontend/src/api/rooms.js` and translates snake case to the existing screen
view model there. The Pydantic schema in `backend/app/api/schemas.py` is the
source of truth. Keep that check in sync with the generated OpenAPI contract
when the schema changes.

## Input and errors

Names are normalized with Unicode NFKC, interior whitespace is collapsed, and
the result must have 2–24 characters without control or invisible characters.
Names are unique within the active room after case folding. Room codes are
eight characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`; input is trimmed
and uppercased. The service limits join attempts to 30 per client address per
60 seconds by default. It does not put names, codes, or credentials in query
strings.

Service errors use `{"error":{"code":"...","message":"..."}}`:

| HTTP | Typical code | Meaning |
| --- | --- | --- |
| `401` | `SESSION_INVALID` | Missing, revoked, or expired reconnect credential. |
| `401` | `RECONNECT_GRACE_EXPIRED` | The guest returned after their reconnect window. |
| `404` | `ROOM_UNAVAILABLE` | Invalid, missing, expired, or closed code share this response. |
| `409` | `ROOM_FULL`, `NAME_TAKEN`, `ROOM_NOT_JOINABLE`, `ROOM_BUSY` | A valid room cannot accept this join or concurrent updates require retry. |
| `422` | FastAPI validation detail | Invalid JSON, name, or capacity. |
| `429` | `RATE_LIMITED` | Too many join attempts from the client address. |
| `503` | `STORAGE_UNAVAILABLE`, `ROOM_ALLOCATION_FAILED` | Redis is unavailable or room allocation failed. |

The API rejects browser requests with an unapproved `Origin`. Production must
use HTTPS and a `Secure` cookie. The default `SameSite=Lax` configuration
requires the frontend and API to share a site; different ports on **the same
hostname** work locally. Use `127.0.0.1` for both services, as in the example
environment files. If hosting across sites, configure `SameSite=None`,
`Secure=true`, explicit CORS origins, HTTPS and an appropriate CSRF strategy
before release.

## Storage and recovery policy

- The Redis key `codemafia:v1:room:<code>` contains a versioned serialized
  `RoomState`. `codemafia:v1:guest:<sha256-credential>` contains the room/player
  mapping. Raw credentials exist only in the cookie and request processing.
- Room and credential records expire after one hour by default; a credential
  never outlives its room. Redis compares the complete prior room snapshot in
  a Lua script and atomically writes room plus session changes. Concurrent joins
  cannot take the same final seat or the same player name.
- A successful resume rotates the credential and revokes its predecessor in
  the same atomic update. Leave revokes it. The browser must send cookies with
  `credentials: 'include'` and must not persist credential values in JavaScript.
- Redis Compose enables append-only persistence. If Uvicorn restarts while
  Redis remains available, refresh resumes the same guest and the same room.
  If Redis data is lost, the room and session are gone; the player must create
  or join again. If Redis is unavailable, room requests return `503`; the UI
  keeps the current room visible and offers another attempt.
- This release has one API process as the room writer. Redis compare-and-swap
  prevents lost room writes, and the deadline worker rebuilds its index on
  startup. Reconnect and outage policy is specified in `docs/recovery.md`.

The live lobby receives WebSocket snapshots and server-authorized ready/start
actions. The separate local match preview remains simulated.

## Local run

From the repository root, start Redis with
`docker compose -f infra/compose.yaml up -d redis`. Start FastAPI from
`backend/` with `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`.
Start Vite from `frontend/` with `npm run dev -- --host 127.0.0.1`.
Copy `frontend/.env.example` to `frontend/.env` only when changing the API
base URL; the default in the client is already `http://127.0.0.1:8000`.
Use another browser profile or private window for the second guest.
