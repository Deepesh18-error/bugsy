# Trusted runner boundary

## Flow

1. FastAPI validates an official-test request and queues an immutable job with the current saved source revision.
2. The runner independently validates the queue schema and the allowlisted challenge ID, version, digest, and complete test list.
3. Each trusted Counter test starts a fresh nsjail process containing only the submitted source and a small operation server. The test itself stays in the runner supervisor and checks observable `Counter` behavior over a bounded JSON protocol.
4. The runner builds the verdict, signs it with `CODEMAFIA_RUNNER_RESULT_HMAC_KEY`, and publishes it once per run ID. The job is acknowledged only after publication.
5. FastAPI verifies the signature, registered job, content pin, test set, room, round, deadline, and source revision before its game engine may accept the result.

The submitted source cannot directly write an official result document. It can control its own observable behavior and can make an operation fail, hang, or send malformed replies; those become failed or unavailable results. As with any programming challenge, hidden tests reduce test-specific hardcoding but cannot prove general correctness for every possible input.

## Limits and isolation

- The worker image runs as UID/GID 10001. The Compose service drops capabilities, keeps Docker's default seccomp filter, uses a read-only filesystem, and gives only `/runs` a bounded writable tmpfs.
- nsjail creates a fresh user, mount, PID, IPC, UTS, and network namespace per test. Only Python runtime files, the operation server, and that run's source file are mounted. The source directory is read-only.
- The jail has a 4-second wall limit, 2-second CPU limit, 384 MiB address-space limit, 1 MiB file limit, a 32-descriptor limit, and an 8 MiB temporary filesystem. The supervisor limits each operation transcript to 4 KiB.
- The worker handles at most two jobs concurrently by default, with a configurable maximum of four. Each job executes its tests sequentially in separate jails.
- The jail does not inherit Redis credentials or the signing key, and it has no network namespace interface. The runner supervisor retains Redis access so it can consume jobs and publish results.

The worker runs an isolation preflight before it reads jobs. If the host or container runtime blocks the required namespace operations, startup fails and no submitted source runs. Docker's default seccomp filter may block this on some hosts. Deployment requires a compatible Linux host and a successful preflight; it must not silently remove namespace isolation.

## Local configuration

1. Use the same randomly generated signing key of at least 32 bytes for FastAPI and the runner. Both `.env.example` files intentionally leave it empty.
2. Start Redis, then start the runner with the `runner` Compose profile, and start FastAPI with its Redis URL and signing key set.
3. A current live match can use only the pinned `oop.counter` version `1.0.0` with the digest in `services/runner/challenges/registry.py`. Editing that authored JSON changes the digest and requires intentional registry review.

The Counter challenge is still marked `draft` in the authored bank. The development match policy may offer it; production match setup requires reviewed content. This registry pin approves the executable test mapping for the current content digest and does not change its editorial review status.

## Recovery and limits of validation

Redis Streams may deliver a job more than once after a crash. The runner publishes at most one result per run ID; FastAPI also rejects duplicate or stale official results. Jobs with malformed envelopes are acknowledged without execution. Redis outages leave valid jobs pending for later recovery.

The official runner needs a compatible Linux kernel and container runtime. Compose syntax and Python contract checks can be validated on other hosts, but a Linux sandbox smoke run is required before this can be called production-ready.

## Phase 9 verification

- On a development machine, run the permanent backend runner checks with `PYTHONPATH=backend python -m unittest discover -s backend/tests/runner -v` and the independent runner checks with `PYTHONPATH=services/runner python -m unittest discover -s services/runner/tests -v`. On PowerShell, set `$env:PYTHONPATH` before each command.
- On the target Linux Docker host, build the runner and run `docker compose -f infra/compose.yaml --profile runner run --rm --no-deps runner python -m unittest discover -s tests -v`. The tests exercise the real nsjail preflight, correct solution, infinite loop, oversized output, malformed Python, filesystem/network access, memory/process limits, and signing-key absence. Any skipped or failed jail test means the isolation exit gate has not passed.
- Then run a complete local match with Redis, FastAPI, editor sync, runner, and two browser sessions. Verify an official failing result, a saved edit, a second official run, an edit while a job is pending, reconnect with the public result restored, and a winning result. The runner must not be considered deployable from contract tests alone.
- The optional Pyodide check runs shared code in a same-origin browser Worker. Worker termination bounds a hung check and keeps the UI responsive; it is not a security boundary against hostile code. A player must opt in to running it. Production use with untrusted strangers needs a separate uncredentialed origin or equivalent isolation. Official outcomes use only the Linux runner.
