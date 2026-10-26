# Bugsy implementation review — October 27, 2026

This review updates the existing working tree. Earlier production configuration,
metrics, API-container and accessibility changes were preserved. No deployment,
commit or push was performed.

## Implemented

### Sabotage integrity and counterplay

- A failed test alone no longer credits sabotage. Verification requires a
  retained passing official baseline and an uninterrupted impostor-authored
  edit chain after that baseline. Restores, mixed authorship, missing history
  and comment-only changes cannot establish credit.
- Python syntax trees must match outside the named target method bodies.
  Signatures, decorators and unrelated code cannot change. Official checks
  must show assertion failures confined to tests that exercise those methods;
  crashes, timeouts and simultaneous unrelated repairs are ineligible.
- Each newly credited revision spends one of three match credits and starts a
  45-second cooldown. Multiple objectives verified on the same revision share
  one credit. Budget/cooldown persist through reconnects and round progression.
- Verification needs at least 30 seconds left in the coding round. It records
  private progress without immediately ending the match. Sabotage wins only at
  the coding deadline if all objectives remain verified on the unchanged
  current revision with a failing official result. Ejection/finalization can
  still win first. Every new saved edit clears current verification, without
  refunding credits.
- The UI explains these rules and privately displays remaining credits and
  cooldown. Civilian snapshots contain no budget or cooldown value.

This is a conservative attribution policy, not perfect causal inference over
arbitrary collaborative edits. It intentionally denies credit when provenance
is ambiguous or pruned. The budget limits scoring; it does not prohibit normal
editing after credits are exhausted. Transport limits, revision history and
restore remain the editor's recovery mechanisms. Preventing all deliberate
griefing would require a different permission/submission model and playtesting.
The 3-credit/45-second/30-second values are initial tuning choices, not measured
balance claims. A harmless saved edit also clears verification; evaluate this
explicit rule during playtests before changing it to semantic persistence.

### Content and integration

- Added Stack and Wallet challenges, including starter defects, reference
  solutions, public/hidden checks, private objectives and trusted runner pins.
- Added Counter 1.1 with accurate test dependencies and objective wording;
  retained immutable Counter 1.0 for compatibility.
- OOP rounds prefer unused challenges before repeating. Back-end is selectable
  for Wallet. The browser uses the deployment-filtered catalog endpoint rather
  than hard-coding OOP as its only category.
- Extended the jailed operation protocol for the new authored classes, with
  allowlisted operations and bounded arguments. Official checks still execute
  outside the submitted-code jail; submitted source never runs in FastAPI.
- Added local content/reference checks and real-jail integration coverage.
  All selectable content remains **draft** until target-Linux execution and
  multiplayer review pass. Production eligibility is not bypassed.

### Efficiency and maintainability

- Cache validated challenge banks by file metadata, with bounded cache size,
  invalidation after changes and retained digest checks for active matches.
- Exclude the development Pyodide worker and its assets from production builds.
  Monaco remains a large, lazily loaded editor bundle.
- Add a browser acceptance scenario for repair, civilian regression,
  attributable sabotage, reconnect, recovery/finalization and rematch.
- Update rules/release documentation and remove the root README exclusion
  from `.gitignore`. The README is now available to include in a future commit.

## Verification

- Backend: 173 tests passed across game (55), realtime (52), API (19), editor
  (19), runner (22) and challenge-content (6) suites.
- Frontend: 7 component/contract tests and 1 browser-Python harness test passed.
- Editor sync: 3 tests passed; the socket test required local loopback network
  permission in this environment.
- Independent runner: 5 boundary tests passed; 8 Linux integration tests skipped
  on Windows. Skips are **not** sandbox validation.
- Production frontend build passed. Pyodide worker assets are absent.
- Playwright discovers 7 scenarios, including the new acceptance scenario.
  Discovery is **not** evidence that live scenarios passed.

## Remaining release work

1. Run the full stack on a compatible Linux host and pass all 8 jail tests with
   no skips. Verify the new operation protocol in the actual image.
2. Execute live browser journeys, including the new repair/recovery scenario,
   and the restart/network/Redis-outage exercises in `recovery.md`.
3. Playtest attribution, budget/cooldown, response timing, grief recovery and
   challenge difficulty. Review/approve versioned content only after its gates.
4. Complete live keyboard/screen-reader review and deployment/proxy/cookie,
   readiness, monitoring, backups and rollback checks in `release-checklist.md`.

Docker's daemon was unavailable during this review, and Docker Desktop was not
present at its standard installation path. Staging/production were not deployed.
CI publication remains deferred by the owner's existing choice.
