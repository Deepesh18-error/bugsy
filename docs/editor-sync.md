# Live editor setup

The coding arena uses Monaco and Yjs in the browser. `services/editor-sync` speaks the y-websocket protocol. FastAPI remains authoritative for room phase, membership, the pinned challenge, source revision, and deadlines. Redis stores the room and Yjs document with the room's expiry.

## Local run

1. Start Redis as usual: `docker compose -f infra/compose.yaml up -d redis`.
2. Set the same long random `CODEMAFIA_EDITOR_SERVICE_KEY` in the PowerShell windows that run FastAPI and the editor service. The backend example variables are in `backend/.env.example`; the service example is in `services/editor-sync/.env.example`. Do not commit the real key.
3. Start FastAPI on `127.0.0.1:8000`.
4. In `services/editor-sync`, run `npm ci` and `npm start`.
5. Run Vite on `127.0.0.1:5173`. Use `127.0.0.1` consistently so the HTTP-only room cookie reaches both services.

The editor service also has an opt-in Compose profile: `docker compose -f infra/compose.yaml --profile editor up --build`. When using that profile, the FastAPI process must be reachable from the container at the configured `CODEMAFIA_API_INTERNAL_URL`; on Docker Desktop this usually means `http://host.docker.internal:8000` and a FastAPI host binding reachable from Docker. The local host process is the simpler development path.

The one authored Counter challenge is currently a **draft**. Development can run a live pilot with that category; production refuses to start a match until approved challenge content is available. Other categories remain unavailable to live voting.

## Save and recovery boundaries

- Each document ID includes room code, match ID, and round number. Both the editor session endpoint and every sync service commit verify that scope against the current room.
- The editor service saves the starter Yjs state before opening a connection. Every later update is merged into a candidate document, checked for size, and committed together with the room's source revision before it is broadcast.
- The sync process is one writer. Multiple API instances or multiple editor service replicas need a distributed coordination design before they can be used safely.
- Up to 30 recent code snapshots are kept with author and time. Restore creates a new revision; it does not rewrite the past.
- A sync status means the browser and provider have exchanged Yjs state. The current server revision shown in the arena is the durable save indicator. Official Python execution remains a later phase.
