# Collaborative editor: authority, storage, and recovery

The coding arena uses Monaco for editing and Yjs for concurrent text changes. The Node `editor-sync` service holds the live Yjs document. FastAPI owns membership, round phase, deadlines, challenge pinning, and revision commits. Redis stores the active room and a separate editor document. Node has no direct Redis credential: its private FastAPI requests use `CODEMAFIA_EDITOR_SERVICE_KEY` plus the guest's HTTP-only cookie.

## Local run

1. Start Redis: `docker compose -f infra/compose.yaml up -d redis`.
2. Set the same long random `CODEMAFIA_EDITOR_SERVICE_KEY` for FastAPI and the editor service. See `backend/.env.example` and `services/editor-sync/.env.example`; never commit the real key.
3. Start FastAPI on `127.0.0.1:8000`, run `npm ci` and `npm start` from `services/editor-sync`, then start Vite on `127.0.0.1:5173`.
4. Alternatively run `docker compose -f infra/compose.yaml --profile editor up --build`. The container uses `CODEMAFIA_API_INTERNAL_URL`, defaulting to `http://host.docker.internal:8000`. FastAPI must bind to an address reachable from Docker. The editor port is published only on loopback.

Use `127.0.0.1` consistently in the browser so the room cookie reaches the authorized endpoints. The Counter challenge is still a **draft**: a development pilot may use it; production requires approved content before match start.

## Document identity and authorization

The document ID is `<room-code>:<match-id>:<round-number>`. A rematch or later round gets a new document. FastAPI recomputes this ID from the trusted room, not from the browser's claims. The browser requests `/api/rooms/editor/session` with its room cookie. FastAPI returns player-safe challenge fields and the current document ID. Node checks the browser Origin and asks FastAPI `/internal/authorize` for that guest and document. Every commit repeats the current-round and player checks. Awareness names and cursors never authorize an edit or carry roles or objectives.

## Revision ordering and durable commit

The round's `current_source_revision_id` is the authoritative pointer. The separate Redis document holds the same revision ID, source, encoded Yjs state, and history. Initialization compare-and-sets the starter document only while the room snapshot still matches and no document exists.

For an edit, Node merges an update into a candidate, then sends its source and Yjs state with the previous revision ID to FastAPI. The coordinator checks player, document, phase, deadline, and revision. The game transition advances the revision and clears any official test result for the prior revision. One Redis Lua operation compares both the prior room bytes and document revision, then writes both values with the room's absolute expiry. Only after the write succeeds is a room event sent. A failed write is never broadcast as a durable edit.

Both values expire with the room. Source is capped at 65,536 UTF-8 bytes, decoded Yjs state at 262,144 bytes, history at 30 snapshots and 1,048,576 total UTF-8 source bytes, and the serialized editor value at 1,572,864 bytes. The oldest snapshots are removed first; the current source and Yjs state remain. Reader code accepts the old unversioned document format and trims its oversized history. New writes use storage version 1. Unknown or corrupt values are rejected.

## Recovery, reconnect, and restore

After an editor-service restart, the first authorized connection reloads persisted Yjs state through FastAPI. FastAPI rejects recovery when the room and editor revision IDs disagree. Node checks that decoded Yjs text matches the stored source. A missing document is initialized from pinned starter code only while the room still has its seed revision. A stale match or round ID cannot edit the current document.

Restore selects a snapshot still in bounded history. Node applies its source to the current Yjs document and commits a **new** revision. The coordinator verifies that the requested origin ID and source match history. The history entry records the restoring player and origin revision. Public events expose only revision IDs and the restoring player's ID, never source text or private roles. A stale test result still refers to its prior revision and cannot win on the restored one.

This setup assumes one API writer and one editor-sync process. Multiple writers or editor replicas require distributed coordination. Redis expiry is the active-room recovery boundary; this is not indefinite source archival. A browser's sync status means it exchanged Yjs state with Node; the current server revision is the durable save indicator. Official Python execution remains a later phase.

## Permanent checks

`backend/tests/editor/` checks storage format and bounds, the complete API/coordinator/repository flow, atomic room/document updates, restore provenance, and safe public revision metadata. Run it from `backend/` with `python -m unittest discover -s tests/editor -p "test_*.py"`. The Node service check exercises the same document-state functions used by the WebSocket service: two concurrent Yjs clients, persistence/reload, restore convergence, and corrupt recovery data. Run it from `services/editor-sync/` with `npm test`.
