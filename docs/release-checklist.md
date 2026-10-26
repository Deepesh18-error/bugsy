# Release checklist

Record a date, environment, and evidence for every completed item. A checked
source file or a mocked unit test is not evidence of a deployed multiplayer
journey. CI publication remains deferred by project choice.

## Local quality gates

- [x] All backend game, realtime, API, editor, and runner tests pass.
      2026-10-25: original 53 + 51 + 12 + 19 + 15 local tests passed;
      after the Phase 14 checks, API 19, realtime 52 and runner 15 passed.
- [x] Editor-sync Node tests pass, including authorization and stale-round
      socket checks. 2026-10-25: 3 tests passed on loopback.
- [x] Frontend unit/component checks and production build pass.
      2026-10-25: 1 Node test, 5 component tests, and Vite build passed.
- [ ] Browser accessibility check passes at desktop and narrow width on the
      **live** screens. Three preview checks passed on 2026-10-25; the live
      screens still need the running multiplayer services.
- [ ] A keyboard-only player can create/join, vote, use the accessible editor,
      chat, request tests, call a meeting, cast a ballot, and read results.
- [ ] A screen-reader pass confirms headings, control names, status messages,
      chat, and timer milestones on all live screens.

## Live multiplayer and recovery gates

- [ ] Four independent guest sessions create/join/ready/start and all see the
      same public phase and selected category.
- [ ] Exactly one guest receives the impostor role. No civilian socket or
      snapshot receives its objective or another player's ballot.
- [ ] Concurrent editor changes converge; stale document IDs and old-round
      writes are refused; restore creates a new revision.
- [ ] Official results come from the Linux runner for the current saved
      revision; old and duplicate results cannot decide the match.
- [ ] Meeting, discussion deadline, private ballot, ejection, and final result
      agree across all sessions.
- [ ] Refresh, tab reopen, temporary network loss, API restart, and Redis
      outage/recovery follow `docs/recovery.md` without contradictory winners.
- [ ] A four-player end-to-end acceptance playthrough is completed in Phase 14.

## Isolation and deployment gates

- [ ] Staging and production use exact HTTPS origins, a WSS editor endpoint,
      secure cookies, separate random service keys, and an explicitly set Redis
      URL. Startup validation rejects local development defaults.
- [ ] The static host, Linux host, and same-hostname editor/API reverse proxy
      are configured as in `docs/deployment.md` and tested from two networks.
- [ ] Incident mode blocks room creation and match start; rollback and Redis
      restore have been rehearsed on staging.
- [ ] A private dashboard scrapes `/ops/metrics` and alerts on API/Redis health,
      runner timeout/error and reconnect trends. Fixed-label API counters are
      implemented, but dashboard and editor/runner readiness are pending.
- [ ] The runner image builds on the target Linux host and its nsjail preflight
      passes without weakening namespace or filesystem restrictions.
- [ ] All sandbox integration tests pass **without skips**: timeout, output,
      malformed source, imports, filesystem/network, memory/process, cleanup,
      and signing-key absence.
- [ ] Secrets are supplied only through deployment configuration; cookie and
      editor/runner service keys never appear in URLs or normal logs.
- [ ] Production Origin, secure cookie, HTTPS, Redis persistence, room TTL,
      and worker settings are reviewed for the deployment environment.
- [ ] The authored challenge is reviewed/approved before production matching;
      the selectable Counter, Stack and Wallet versions are still marked `draft`. Controlled
      staging playtests may explicitly allow draft content.

## Current blockers

On the 2026-10-25 Windows workspace, Docker was not running, so Redis, the
editor/runner profiles, Linux jail checks, and live browser journeys could
not be exercised together. Complete those gates before claiming Phase 13's
full product exit criterion or shipping the game. The staging and production
environments and metrics dashboard are not deployed. The selectable authored
challenges are still drafts, so production match start is blocked; staging
requires an explicit draft-playtest setting.
