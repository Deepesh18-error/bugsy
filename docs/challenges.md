# Challenge and Sabotage Content Contract

This document defines how CodeMafia challenges, tests, and impostor objectives are authored and versioned. It is the content contract for the backend challenge bank and future runner integration. It does not define the runner implementation or permit the FastAPI process to execute player code.

## 1. Design goals

Every authored challenge must be:

- **Deterministic:** the same challenge ID and version always resolve to the same starter code, tests, and objectives.
- **Versioned and immutable:** a released version is never edited in place. A content change creates a new version.
- **Measurable:** tests and sabotage objectives have stable IDs and machine-checkable outcomes.
- **Bounded:** tests have finite time, memory, process, and output limits enforced by the isolated runner.
- **Fair:** civilians can understand the repair goal and discover harmful changes, while the private objective does not reveal the impostor.
- **Private by default:** solutions, hidden test details, and impostor objectives stay on the trusted backend side.

## 2. Challenge identity and versioning

Each challenge version has a stable `id` and a separate `version`.

- `id` identifies the challenge across its lifetime, for example `oop.counter`.
- `version` identifies one immutable release of that challenge, for example `1.0.0`.
- A new prompt, starter program, test, expected behavior, or objective that could affect a match requires a new version.
- Never reuse an ID for a different challenge and never silently replace the content of an existing version.
- A match pins the complete `(id, version)` pair when its round begins. Reconnects and retries continue using that same pair.
- Content is loaded by explicit ID/version, never by filesystem order. Any challenge selection is performed by the game service and recorded in match state.
- A content digest should be recorded with the pinned pair when the bank is loaded, so accidental file changes can be detected.

The schema itself also has a `schema_version`. This version describes the shape and meaning of the content document; it is distinct from the challenge's own version.

## 3. Challenge document fields

Every challenge document must define the following information:

| Field | Meaning and rules |
| --- | --- |
| `schema_version` | Version of this document contract. |
| `id`, `version` | Stable challenge identity and immutable content version. |
| `category` | One of the supported category IDs: `data-structures-algorithms`, `object-oriented`, `security`, `front-end`, or `back-end`. |
| `title`, `prompt` | Short player-facing name and explanation of the task. The prompt describes the intended behavior without revealing private tests or the impostor objective. |
| `language`, `python_version` | Language and supported Python runtime version. The runtime version must be pinned by the runner deployment; a challenge cannot request an arbitrary interpreter. |
| `starter_code` | Exact initial source text for the round. It must be syntactically loadable, bounded in size, and safe to display as text. It is not trusted or executed by the API. |
| `functions` | Stable IDs and names for the relevant functions or methods, their purpose, and the TODOs they own. IDs are used to refer to code targets without relying on line numbers. |
| `todos` | Stable IDs, player-facing instructions, and target function IDs. They explain the intended repair without prescribing an implementation unnecessarily. |
| `tests` | Test definitions described in section 4. IDs are unique within the challenge version. |
| `runtime_policy` | Reference to a named, runner-enforced resource profile. Challenge content may not raise the deployment's hard limits. |
| `reference_solution` | Review-only correct implementation or solution fixture. It is private content and must never be included in a player-facing response. |
| `sabotage_objectives` | One or more private, verifiable objectives as described in section 5. |
| `authorship` | Author identifier or team, creation date, reviewer, and review status. Do not put secrets or personal contact details here. |

Text, starter code, descriptions, and metadata are untrusted content for rendering purposes: render them as text, never as HTML or executable frontend code.

## 4. Test contract

Each test has a stable `id`, a trusted `test_definition_id`, a visibility (`public` or `hidden`), a `required_for_civilian_win` flag, and an expected behavior defined in trusted challenge content. The definition ID is a key into the trusted runner test registry, not a Python import path or client-supplied code. Public tests also have a player-safe name, description, and failure message; hidden tests omit those player-facing detail fields. Tests should be small, focused, and report an understandable, bounded result.

### Visibility

- **Public tests** may expose their purpose and safe failure messages to every player. They are useful feedback, but the browser is not authoritative.
- **Hidden tests** do not expose their inputs, expected values, implementation, or detailed failure output to players. The server may return a generic failed-test count or safe summary.
- Test visibility controls what content is sent to clients; it does not change whether the test is run by the official runner.
- Private test code and expected values must not be bundled into frontend assets, public room snapshots, chat messages, or client error payloads.

### Pass and victory semantics

- A test result is attached to the exact immutable source revision that was tested.
- A result is **current** only while the authoritative shared document is still at that revision. Any subsequent edit makes it stale for victory decisions, even if the text change appears unrelated.
- All tests marked `required_for_civilian_win` must pass together on the same current, official runner result before the round deadline. This creates a candidate civilian win.
- A passing result is not a permanent lock. A connected living player must explicitly finalize that exact current revision before the deadline to commit victory. Any edit clears the candidate and calls for another official run.
- A result for an older revision can remain as historical feedback, but cannot decide the current winner.
- Local browser feedback, if added, is provisional and must be labeled as such. It never counts as an official pass or a win.

If the impostor is ejected, the existing civilian ejection win condition applies independently of test completion. Challenge tests do not override the match state machine or its event ordering rules.

### Test safety and output

Challenge tests and player code run only in the isolated runner introduced by a later phase, never inside FastAPI. The runner enforces wall-clock, CPU, memory, process-count, and output-size limits, disables network access, and returns a bounded structured result. Challenge-authored output is treated as untrusted and sanitized before display. Exact numeric limits belong to the runner's deployment policy and must be selected and validated before official execution is enabled.

## 5. Sabotage objective contract

An objective is private to the assigned impostor and the trusted server. Its content must never be sent to civilians or included in public challenge payloads.

Each objective defines:

| Field | Meaning and rules |
| --- | --- |
| `id` | Stable objective ID within the challenge version. |
| `private_description` | Instruction visible only to the assigned impostor. |
| `target_function_ids` and/or `target_test_ids` | Relevant stable challenge IDs; do not identify a target by source line number. |
| `verification` | A constrained, allow-listed predicate over official runner results and the pinned source revision. Never evaluate an arbitrary expression or code supplied by content or a client. |
| `progress_policy` | Content rule for how verification evidence is recorded. In the MVP, an objective is recorded once per revision when its verifier succeeds; a later revision resets current progress. The live state (not started, in progress, or verified), verified revision, and completion event belong to match state, not this immutable challenge document. The client may display server-provided progress but cannot set it. |
| `completion_effect` | Per-objective effect. In the MVP, a verified objective records completion against its verified revision; the game engine aggregates the assigned objectives and checks victory at the coding deadline if all objectives remain verified on the current revision and the 30-second response window was available. |
| `fairness_notes` | Reviewer explanation of how civilians can notice and recover from the behavior without being told the secret objective. |

Objective completion is verified by the server using pinned challenge definitions and official runner output, never by a client claim. Once an objective is verified, record the verified revision and completion event. The private event records historical verification. Every saved edit clears live verification while preserving the spent match credits and cooldown.

The objective should produce observable evidence through code changes, public test behavior, or other already-authorized game feedback. Avoid objectives that require arbitrary disruption, hidden access to another player's client, or information that civilians cannot reasonably discover. If objective completion ends the match, the transition must follow the match's serialized event ordering rules so a previously committed ejection is not overwritten.

## 6. Runtime policy and bounded content

Every challenge references a named runtime profile that the runner recognizes. The profile must constrain at least:

- Python interpreter version.
- Wall-clock and CPU time.
- Memory and process count.
- Maximum source, input, and output sizes.
- Network access (disabled for challenge execution).

The runner deployment owns the hard maximums. Challenge content may choose only an approved profile and cannot request a higher limit. A challenge is not eligible for production play until its tests and reference solution finish within the approved profile with margin for normal host load.

## 7. Authoring and review checklist

Before a challenge version is accepted, reviewers verify:

1. The challenge ID, version, category, schema version, and authorship fields are present and valid.
2. The starter program loads deterministically and the TODOs match the prompt and target function IDs.
3. The reference solution passes every required test under the pinned Python/runtime policy.
4. At least one plausible sabotage path exists and its objective can be verified from official results without arbitrary code evaluation.
5. Public tests provide useful clues; hidden tests protect meaningful behavior without making the task impossible to reason about.
6. Test IDs and objective IDs are unique and stable within the version; output is bounded and player-safe.
7. Civilians can identify and recover from a harmful change, including an accidental edit, without a permanent test lock.
8. The challenge and objective difficulty are appropriate for the round duration and the intended player count.
9. Private fields are excluded from every payload intended for a player who is not authorized to see them.
10. A new version is created for any gameplay-affecting edit; released content is not silently mutated.

## 8. Initial challenge bank scope

Start with the Counter challenge as the schema example. It should include a known correct solution, focused tests for its intended behavior, and at least one subtle sabotage objective that can be detected and repaired. Once that complete example has been reviewed, add a small authored set across the five supported categories. Do not add a user-generated content editor in this phase.

The initial bank is accepted only when every included challenge can be selected by its explicit ID/version, has bounded official tests, has a known correct solution, and supports at least one reviewed sabotage objective.

The selectable development/staging bank contains `oop.counter` 1.1.0,
`oop.stack` 1.0.0 and `backend.wallet` 1.0.0. Counter 1.0.0 remains pinned for
compatibility. The first OOP round uses Counter, then prefers unused Stack;
content repeats only after the category bank is exhausted. The catalog endpoint
filters by the deployment's draft-content policy. All selectable versions
remain draft until real nsjail checks and multiplayer review are complete.


## 9. Phase boundary

This contract describes challenge data and review requirements. It does not implement challenge loading APIs, collaborative editing, test execution, sandboxing, objective assignment, or match-state transitions. Those features consume this contract in later phases. The current frontend challenge data remains preview-only until it is deliberately adapted to the approved bank and public/private payload boundary.


## Current attribution policy

A passing official baseline must remain in both bounded result history and
editor history. Every revision after it must come from the impostor after that
result, without restores or civilian edits. AST comparison preserves everything
outside target method bodies, including signatures/decorators. Syntax errors,
runtime failures and timeouts never earn credit. Only tests declared to exercise
the target functions may newly fail; simultaneous repairs are rejected. Missing
or pruned provenance fails closed instead of guessing authorship.

One newly verified revision costs one of three match credits, with a 45-second
cooldown. Verification closes 30 seconds before the round deadline. Victory is
checked at the deadline; every subsequent edit/restore clears verification.
