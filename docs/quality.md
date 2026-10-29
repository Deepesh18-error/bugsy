# Quality and security verification

Phase 13 uses permanent tests at the layer that owns each rule. Passing a
mocked rule test is useful, but it does not establish that Redis, the editor
service, the Linux jail, and four browsers work together.

## Test matrix

| Boundary | Checks | Where |
| --- | --- | --- |
| Game rules | voting, deadlines, replayed commands, win precedence, role privacy | `backend/tests/game/` |
| Room WebSocket | authenticated identity, Origin, strict schema, frame/rate limits, reconnect and private delivery | `backend/tests/api/`, `backend/tests/realtime/` |
| Editor | current room/match/round, guessed IDs, departed or eliminated players, stale writes, Yjs convergence | `backend/tests/editor/`, `services/editor-sync/tests/` |
| Runner | pinned tests, signed/current results, queue pressure, malformed results, job coalescing | `backend/tests/runner/`, `services/runner/tests/test_contract_and_parser.py` |
| Linux isolation | infinite loop, output, filesystem/network/import attempts, memory/process limits, scratch cleanup | `services/runner/tests/test_sandbox_integration.py` mounted into the runner container |
| Frontend decisions | form validation, readiness controls, private ballot, stale official result, public-build browser-check removal | `frontend/tests/screens.test.jsx` |
| Browser interaction | four separate player sessions through result; refresh and tab reopen | `frontend/e2e/match-flow.spec.js`, `reconnect.spec.js` |
| Browser privacy | each socket receives only its own role and objectives | `frontend/e2e/privacy.spec.js` |
| Accessibility | all preview screens, keyboard focus, and narrow-screen overflow | `frontend/e2e/accessibility.spec.js` |

## Local commands

From `backend/`, use the virtual environment's Python. Run each test directory
separately because its local fixtures are imported by name:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/game -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/realtime -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/api -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/editor -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/runner -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/challenges -v
```

From `services/editor-sync/`, run `npm test`. This includes a loopback
WebSocket check with a small fake authority server. From `frontend/`, run
`npm test`, `npm run test:components`, and `npm run build`.

`npx playwright test accessibility.spec.js` needs Chromium and the Vite server,
which Playwright starts. The live specs also need Redis, FastAPI, editor sync,
and a runner configured with the same result-signing key as FastAPI. Their
preflight checks fail clearly when a required service is unavailable. Use
`npm run test:e2e` from `frontend/` after starting those services. Four browser
contexts are separate guest sessions; no session cookie or role is copied
between them. The default URLs are 127.0.0.1 ports 5173, 8000, and 1234.
The optional `CODEMAFIA_E2E_API_URL`, `CODEMAFIA_E2E_EDITOR_URL`, and
`CODEMAFIA_E2E_WEB_URL` values configure the browser suite. The API's allowed
origins must include the chosen web URL.

The Linux jail check must run against the actual runner image on a compatible
host. The production image does not contain test files, so mount them read-only
from the repository root in PowerShell:

```powershell
$repoRoot = (Get-Location).Path
docker compose -f infra/compose.yaml --env-file infra/.env --profile runner run --rm --no-deps -v "${repoRoot}\services\runner\tests:/opt/runner/tests:ro" --entrypoint python runner -m unittest discover -s /opt/runner/tests -p test_sandbox_integration.py -v
```

**Skipped jail tests do not count as a pass.** The Windows import check only
shows that the test module loads; it does not validate namespaces or resource
limits. The full Redis restart/outage exercise from `docs/recovery.md` also
needs a running Docker daemon.

## Security review notes

- FastAPI room WebSockets require an allowed Origin and the current HTTP-only
  guest cookie. Client commands have no accepted `player_id`, `role`, or
  official-result field. Redis-backed command receipts prevent retries from
  applying an action twice.
- Editor authorization checks the authenticated guest and exact current
  room/match/round document. An old round cannot commit a revision. The sync
  service now rechecks authorization for read and awareness requests; writes
  are checked by FastAPI before they become shared state. The restore HTTP
  response uses a fixed public error rather than reflecting internal details.
- Official results must match a pinned challenge and saved revision and have
  a valid runner signature. Same-origin browser Pyodide execution is limited
  to local development builds because a Worker cannot isolate hostile shared
  Python from the browser's network access.
- Routine logs use static operational messages, exception class names, and
  run IDs. They do not intentionally record cookies, player roles, chat text,
  or submitted source. Tracebacks from untrusted or storage failures are not
  emitted by the reviewed workers. Access to operational logs still needs
  normal deployment controls.
- The editor, runner, and Redis share one development host in this release.
  The room coordinator assumes one FastAPI writer; no multi-instance safety
  claim is made.

## Accessibility review notes

- Screen changes move focus to the new main heading. Interactive controls
  retain visible focus indicators, including the accessible text editor.
- Coding, meeting, and voting timers have milestone announcements rather
  than announcing every second. Chat messages use a labelled log.
- Automated checks cover all preview screens with WCAG A/AA axe rules, keyboard
  focus, and narrow viewport overflow. Live role, editor, meeting, vote, and
  result screens still require a running multiplayer system and human
  screen-reader review.

## Current validation status

As of 2026-10-28, Redis and editor-sync are healthy in local Docker Desktop,
the runner remains up after its nsjail preflight, and all eight real-jail
integration checks pass without skips. The 2026-10-25 unit-test runs recorded
53 game, 52 realtime, 19 API, 19 editor, and 15 backend runner passes, along
with five frontend component checks, a production build, editor loopback tests,
and three browser preview accessibility checks. The live four-player browser
journey, Redis restart/outage exercise, API container build, and target-host
runner validation remain open. See `docs/release-checklist.md` before
describing the product as fully validated.


## October 27 additions

- Runner attribution tests cover civilian regressions, mixed-author changes,
  restore/last-author laundering, target-only damage, syntax/runtime failure,
  private budgets, persistence and duplicate results.
- Challenge tests check digests, references/starters, plausible sabotage, copy
  aliasing, category eligibility, unused challenge selection and cache invalidation.
- `frontend/e2e/repair-and-recovery.spec.js` covers four-player repair, civilian
  regression, attributable sabotage without instant victory, mid-round reload,
  repair/finalization and rematch. It requires the complete live stack.
- Linux isolation tests now exercise all authored reference solutions through
  the actual jail protocol. Skipped tests remain unverified.
- Public frontend builds exclude the Pyodide worker and its emitted assets.
