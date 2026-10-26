# Phase 4: pure Python game engine

The engine in `backend/app/game` accepts an immutable `RoomState` and one
player command or trusted server fact. It returns `TransitionAccepted` with a
new state and ordered domain events, or `TransitionRejected` with the original
state and a machine-readable reason. It performs no database, network, editor,
or Python-runner I/O. The future room coordinator must serialize operations
for one room before applying these functions or committing their results.

## Phase transitions

| From | Trigger | To | Main event |
| --- | --- | --- | --- |
| Lobby | Host starts with 4–5 connected, ready players | Category vote | `MatchStarted` |
| Category vote | All connected voters finish or deadline expires; coordinator supplies a valid winner and impostor | Role reveal | `CategorySelected`, private `PlayerRoleAssigned` |
| Role reveal | Reveal deadline expires; coordinator supplies a pinned challenge | Coding round 1 | `CodingRoundStarted` |
| Coding round | Eligible player calls an emergency meeting | Discussion | `MeetingStarted` |
| Discussion | Discussion deadline expires | Player vote | `PlayerVotingStarted` |
| Player vote | All connected living voters finish or deadline expires | Coding round, or game over if impostor ejected | `PlayerVoteResolved`, possibly `PlayerEliminated` and `MatchEnded` |
| Coding round | Trusted official result passes all required tests on the current revision | Coding round; candidate win | `OfficialTestResultAccepted` |
| Coding round | Connected living player finalizes that same current green revision before the deadline | Game over, civilians win | `MatchEnded` |
| Coding round | Trusted verifier completes every assigned objective in the current round | Game over, impostor wins | Private `SabotageObjectiveVerified`, `MatchEnded` |
| Coding round 1–3 | Round deadline expires | Round result | `RoundEnded` |
| Round result | Coordinator supplies the next pinned challenge | Next coding round | `CodingRoundStarted` |
| Coding round 4 | Final deadline expires with impostor alive | Game over, impostor wins | `RoundEnded`, `MatchEnded` |
| Game over | Every connected player requests a rematch, with at least four connected | Lobby with fresh readiness and no roles | `RematchRequested`, `RematchStarted` |

An explicit departure or an expired reconnect grace marks a player departed.
If the host departs, the earliest joined connected member takes over; an
unconnected member may take over if none is connected. If no members remain,
the room closes. If the impostor departs after role assignment, civilians win;
this can happen before round 1, in which case the result records round `0`.
If a departure leaves fewer than four members during category voting, the
unassigned match closes. `expire_room` closes the room at its absolute expiry
in any phase. A closed or expired room accepts no new player commands.

## Authority and ordering

- `apply_command` receives a player ID bound to an authenticated connection.
  The client must never choose another actor's ID, a role, a deadline, or a
  verdict. Phase 5 will enforce that boundary at HTTP/WebSocket entry points.
- `record_source_revision` accepts a committed editor revision from the trusted
  editor coordinator. It clears the prior official result. It does not apply
  text edits; collaborative editing belongs to a later phase.
- `record_official_test_result` and `record_verified_sabotage_objective` accept
  trusted runner/verifier facts. Both require the current revision and an open
  coding deadline. A complete official pass stays reversible until a living
  player finalizes that exact revision. The challenge content supplies objective
  definitions; the engine records the verifier's verdict and applies the win rule.
- At the exact deadline (`now == due_at`), the deadline wins. Commands and
  trusted results received then are too late. A stale deadline ID cannot
  advance another phase. Room expiry takes priority when its timestamp is due.
- Operations for a room must be committed in one serial order. If civilian
  victory or impostor victory commits first, the phase becomes `GAME_OVER` and
  the later competing result is rejected. Ejection can interrupt verified sabotage before the coding deadline.
- Player command retries use `(room_code, player_id, request_id)` with the
  policy in `idempotency.py`: default ten-minute retention and 10,000 cached
  entries. The current store is in memory. Phase 5 must place the store and
  room-state commit under one safe coordination policy; replayed outcomes must
  not overwrite newer room state.
- Random tie and role choices are supplied by the coordinator through
  `randomness.py`. Recording those choices with the resulting events makes a
  scenario reproducible.

## Reconnect and privacy

`mark_player_disconnected` stores a separate per-player grace deadline and
preserves identity, role, alive status, and existing ballots. The disconnected
player cannot issue commands. `restore_player_connection` accepts the same
player before the deadline after the transport layer verifies the reconnect
credential. At the exact deadline, `expire_reconnect_grace` wins and marks the
player departed. A missing ballot from a disconnected voter is abstention.

Engine state includes every player's secret role and private objective data.
It is **not** a client response model. `PlayerRoleAssigned` and
`SabotageObjectiveVerified` are private events for a single recipient. Phase 5
must build authorized snapshots and route private events only to that player.

## What the unit scenarios prove

The `backend/tests/game` suite drives the functions directly. Its lifecycle
scenario starts in the lobby, resolves category and roles, times out four
rounds, commits an impostor win, and resets into a fresh rematch lobby. Other
scenarios cover accidental regression, stale runner results, verified
sabotage, meeting and vote outcomes, deadline races, reconnect grace, room
expiry, and command retry behavior. These scenarios verify rule decisions;
they do not exercise FastAPI, WebSockets, Redis, the editor, or the runner.


## October 27 rules

Verification records private progress without ending the match. Three credits
per match, a 45-second cooldown and at least 30 seconds to respond are enforced.
Objectives verified on the same revision share a credit. Source updates clear
verification, preserving the budget. Coding deadlines award sabotage victory
only for all objectives verified on the unchanged revision with a failing
official result. Storage version 7 persists budget/cooldown fields and accepts
older stored rooms with defaults.
