# Phase 14 deployment review (2026-10-25)

This is a release plan, not evidence of a deployed game. The local backend now
has a single-worker container image and public-environment startup checks.
Staging and production have not been provisioned or playtested.

## Proposed topology

Use a static React host with a custom domain such as `game.example.com` and
one Linux host for the stateful services. Cloudflare Pages is one possible
static host; it supports [custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/).
Use an HTTPS reverse proxy on the Linux host under `api.example.com`. Caddy is
one option; its [reverse proxy supports WebSocket upgrades](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
and [automatic HTTPS](https://caddyserver.com/docs/automatic-https). Hosting
provider and Linux kernel/container capabilities still need an actual choice
and test before deploying the runner.

| Public route | Private destination | Reason |
| --- | --- | --- |
| `https://game.example.com/` | static `frontend/dist/` | React assets only |
| `https://api.example.com/api/rooms/editor/ws/*` | editor-sync service | Yjs WebSocket and guest cookie |
| `https://api.example.com/api/rooms/editor/restore` | editor-sync service | authorized restore |
| `https://api.example.com/*` | one FastAPI worker | room HTTP, room WebSocket, editor authority, feedback |

The editor service must be reached through the **same `api.example.com`
hostname** as FastAPI. The guest cookie is HTTP-only, host-only, and scoped to
`/api/rooms`; a separate `editor.example.com` host would not receive it.
`game.example.com` and `api.example.com` are same-site subdomains, so the
current `SameSite=Lax` cookie can accompany credentialed browser requests.
The frontend build must set `VITE_API_BASE_URL=https://api.example.com`.
If the frontend and API are deployed on unrelated sites, revisit cookie
policy, CORS, and browser behavior before release.

On the Linux host, place Redis, FastAPI, editor-sync, and the runner on a
private container network. Expose only the reverse proxy publicly. Keep Redis
data on a persistent volume. Use **one FastAPI process and one editor-sync
process**: room locks, live sockets, and active Yjs documents are process-local.
Do not increase API workers or replicas until a distributed coordinator and
editor document ownership protocol exist. The local `infra/compose.yaml` is a
development file, not a production deployment definition.

## Configuration and secrets

Use independent staging and production domains, Redis data, and random
service keys. Inject secrets through the host's deployment secret mechanism;
never put them in Vite variables, Git, URLs, or logs.

| Setting | Public environment value |
| --- | --- |
| `CODEMAFIA_ENV` | `staging` or `production` |
| `CODEMAFIA_ALLOW_DRAFT_CONTENT` | `true` only for an explicit staging playtest; always `false` in production |
| `CODEMAFIA_ALLOWED_ORIGINS` | exact HTTPS frontend origin(s) |
| `CODEMAFIA_SECURE_COOKIE` | `true` |
| `CODEMAFIA_COOKIE_SAMESITE` | `lax` for the same-site subdomain topology |
| `CODEMAFIA_EDITOR_WS_URL` | `wss://api.example.com/api/rooms/editor/ws` |
| `CODEMAFIA_EDITOR_SERVICE_KEY` | same 32+ byte random value in API and editor-sync |
| `CODEMAFIA_RUNNER_RESULT_HMAC_KEY` | same 32+ byte random value in API and runner |
| `CODEMAFIA_METRICS_TOKEN` | independent 32+ byte random bearer token for `/ops/metrics` |
| `CODEMAFIA_API_INTERNAL_URL` | private API URL, for editor-sync only |
| `REDIS_URL` | private Redis URL, explicitly set |
| `CODEMAFIA_ACCEPT_NEW_MATCHES` | `true`; set `false` during an incident |

The API now rejects staging/production startup when HTTPS/WSS, secure cookie,
Redis URL, or service keys are missing. It does **not** validate that the host
actually enforces TLS or that the Linux runner jail works. Firewall, proxy
headers, process limits, backups, and telemetry need a host-level review.
In particular, room join limits key off the client IP: configure the proxy and
Uvicorn's trusted forwarded-header policy together so all players do not
appear to share the proxy's IP and untrusted clients cannot forge one.

## Staging sequence and acceptance

1. Build the API image from `backend/Dockerfile`; build the existing
   editor-sync and runner images on the target Linux host. Keep Redis private.
2. Run the runner's full nsjail tests inside the actual image. **No skipped
   isolation tests count as a pass.** Verify namespaces, memory, process,
   output, network, filesystem, and timeout behavior under host load. The
   current Windows workspace cannot verify this.
3. The Counter, Stack and Wallet challenges are still `draft`. Staging may explicitly set
   `CODEMAFIA_ALLOW_DRAFT_CONTENT=true` for a controlled playtest; production
   rejects that setting and cannot start a match until content is reviewed.
   Review public/hidden tests, reference solution, sabotage fairness,
   duration, and pinned digest before changing its review status.
4. Deploy the static build with the correct API base URL. Verify HTTP health,
   origin rules, guest cookie, both WebSockets, editor revision recovery, and
   official runner results from separate browsers and separate networks.
   Confirm the public build does not execute shared Python in a browser Worker.
5. Run the four-player browser journey, a human playthrough, refresh and
   reconnect, API/editor/runner restart, Redis outage, and rollback drills.
   Measure WebSocket idle and maximum connection lifetimes on the chosen host.
6. Run keyboard and screen-reader passes on the **live** screens. Record
   results in `docs/release-checklist.md` with date and environment.

The API `/health` checks Redis. The private `/ops/metrics` endpoint exports
fixed-label, process-local counters for room creation, match start/end,
reconnect, runner error and runner timeout, plus API/Redis health gauges.
Send `Authorization: Bearer <CODEMAFIA_METRICS_TOKEN>` from a private monitor.
Counters reset on API restart, and `runner_error_total` includes timeouts.
Editor `/health` only confirms its HTTP process; runner has no independent
readiness endpoint. An actual dashboard and alerts are still pending. Do not
export source code, roles, cookies, chat or request IDs.

## Incident, rollback and data expectations

Set `CODEMAFIA_ACCEPT_NEW_MATCHES=false` and restart the single API process to
stop new rooms and lobby match starts. Existing matches can continue, subject
to the restart reconnect grace period. A new build should be deployed first to
staging with compatible room serialization and the same pinned challenge
content. If a release fails, stop new matches, restore the previous API/editor
images and static build, then verify one existing room and one new room before
reopening. **Do not roll back across an incompatible stored-room format**;
expire or migrate active rooms first.

Rooms, credentials, editor revisions, and queues are deliberately short-lived
Redis data. Redis AOF and a persistent volume support ordinary host restarts;
they are not a promise of permanent match history. Decide whether to take a
volume snapshot before deployment, and test restoration on staging. If Redis
is lost, active matches expire and guests must create new rooms. No MongoDB
collection is part of the current game path.

## Open release blockers

- Production challenge catalog is empty until editorial approval. Staging
  playtests need the explicit draft-content setting.
- Full four-player online journey and runner isolation on the chosen deployment
  host are unverified. The local Docker Desktop jail checks passed on 2026-10-28.
- Actual hosting, proxy configuration, WebSocket lifetime, metrics dashboard,
  and rollback drill remain to be completed on the chosen host.
