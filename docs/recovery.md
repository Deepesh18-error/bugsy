# Room recovery policy

This release has one FastAPI room writer. Redis is the authority for the room,
guest sessions, command receipts, editor documents, and deadline index. Browser
memory and WebSocket events are hints; neither is used to reconstruct a match.

## Returning player

1. A room WebSocket authenticates the HTTP-only guest cookie. The credential is
   never placed in the URL, a message, or a log.
2. Closing the final WebSocket for one player records `disconnected` and a
   server-time reconnect deadline. Closing one of several tabs does not start
   grace while another tab remains connected. Explicit Leave is a departure.
3. A valid guest can return before the exact deadline. The room is restored
   before the new socket receives its first authorized snapshot. Events are
   withheld from that socket until its first snapshot is sent. Sequence gaps
   request another snapshot; there is no event replay requirement.
4. At the deadline, a durable callback departs the player once. A late
   reconnect is rejected. Session expiry can end access sooner than grace.
   HTTP resume rotates the cookie; WebSocket reconnect authenticates the
   current cookie without rotating it.
5. The editor provider starts only after the current room snapshot arrives.
   Its document ID contains room, match, and round. FastAPI checks membership,
   phase, and revision before a document edit is committed.

The default reconnect grace is 60 seconds. It can be set with
`CODEMAFIA_RECONNECT_GRACE_SECONDS`; it cannot extend beyond room expiry.
Only the player's own role, objectives, and ballot are included in their
snapshot. Other players see connection status, not private values.

## Restart and duplicate work

On API startup, connected players left by the previous API process enter a
fresh reconnect grace. The API rebuilds the deadline index from room snapshots
before accepting traffic. Phase and player-grace deadlines share a durable
index. A callback checks its deadline ID against the current room, then saves
the transition with Redis compare-and-swap before broadcasting. A callback
replayed after a crash is stale and cannot end a round or eject twice.

The editor service reloads the stored Yjs document. The room's revision must
match the document's revision; a stale round cannot overwrite the current
document. Official runner results also check match, round, deadline, and
revision IDs. A timed-out run is saved as `error` after 45 seconds by default;
its deduplication key can be released for a new attempt. A late result for a
run already marked `error` is discarded. `CODEMAFIA_RUNNER_RESULT_TIMEOUT_SECONDS`
sets the timeout. Runner jobs and results use Redis Streams; rooms and browser
events do not rely on Redis Pub/Sub replay.

## Outage policy

Redis failure is fail-closed: HTTP mutations return `503`; the WebSocket
reports storage unavailable and closes with a retryable code; room actions,
deadlines, and runner verdicts are not acknowledged without a durable save.
The browser hides live controls, retries with bounded backoff, and offers a
manual retry after the limit. The room remains stored until its absolute TTL
if Redis data survives. Redis AOF is enabled in the local Compose service.

For this release, **server-time game deadlines continue during an outage**.
Overdue callbacks run after Redis returns. No team is awarded a special
infrastructure forfeit and no provisional browser test can become an official
win. If Redis loses its data, a room cannot be recovered and the guest must
create or join a new one. The policy deliberately does not claim to pause an
unrecordable interval while Redis itself is unavailable.

If the runner is unavailable, a queued run becomes a visible error after the
configured timeout and players may submit the still-current revision again.
The coding timer continues; runner failure does not itself award either team
a win. A result that arrives after timeout cannot affect the match.

## Operating checks

- Restart FastAPI with Redis still running: all current sockets reconnect,
  recover their own snapshot and editor document, and old deadlines resolve
  at most once.
- Stop Redis: commands fail closed and clients show recovery. Restart Redis:
  clients reauthenticate and fetch fresh snapshots.
- Stop the runner: queued runs become retryable errors; restart it and submit
  the current revision again.
- The `/health` endpoint returns `503` when Redis is unavailable. It is not a
  runner or editor-service health check.

The full four-player playthrough remains the Phase 14 acceptance exercise.
