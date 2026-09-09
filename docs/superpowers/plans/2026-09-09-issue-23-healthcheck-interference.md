# Issue #23 Health-Check Interference Investigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-publishing same-runner A/B investigation that measures the existing recurring API-container healthcheck policy against bounded external readiness without changing official benchmark behavior.

**Architecture:** Keep `DockerEnvironment` default behavior exactly compatible with the current `container-healthcheck` path. Put health-policy parsing, deterministic Compose override generation, readiness validation, Docker event parsing, and descriptive comparison helpers in a focused `benchmark/healthcheck.py`; keep the existing process validator in `benchmark/environment.py` with one backward-compatible keyword; add `benchmark/healthcheck_investigation.py` as the only orchestration entry point that runs both policies and writes a diagnostic-only artifact. A temporary PR-only CI job gathers full-profile evidence and is removed before merge.

**Tech Stack:** Python 3.10+, Docker Engine/Compose, existing `benchmark.contract_test` HTTP/JSON validation, existing registry/profile/oha parser, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-09-issue-23-healthcheck-interference-design.md`

## Global Constraints

- Default benchmark and official benchmark behavior remain `container-healthcheck` until a separately approved methodology change.
- `results/latest.json`, `results/history/`, generated README result blocks, and Pages inputs are never written by the investigation.
- Both A/B policies run sequentially on the same runner and source commit with the existing 1 CPU / 512 MiB, 50 connections, 5-second warm-up, 30-second duration, 3 runs, and `/json`, `/db/42`, `/cpu` profile.
- PostgreSQL Docker healthcheck remains enabled in both policies.
- Controlled mode disables only the selected API healthcheck and performs bounded host-side exact `/health` validation before measurement; no readiness polling continues during warm-up or measurement.
- Restart/OOM/container identity/process-count checks, shared contracts, deadlines, memory observation, and scoped cleanup remain mandatory.
- Docker event output is bounded and retrieved immediately after each interval because Docker retains only the most recent event history.
- Diagnostic output is `official: false`, `publishable: false`, `mode: healthcheck-investigation`; it is never an official publication input.
- No statistical-significance claim, p-value, confidence interval, overhead subtraction, or composite score.

---

### Task 1: Health policy and process contract

**Files:** Create `benchmark/healthcheck.py`; modify `benchmark/environment.py`; create `tests/test_benchmark_healthcheck.py`.

**Interfaces:**
- `benchmark.healthcheck.CONTAINER_HEALTHCHECK = "container-healthcheck"`.
- `benchmark.healthcheck.EXTERNAL_READINESS = "external-readiness"`.
- `benchmark.healthcheck.validate_policy(value: str) -> str` rejects every other value with `BenchmarkFailure`.
- `benchmark.healthcheck.override_text(implementation_id: str) -> str` validates the registry ID and emits only that service with `healthcheck.disable: true`.
- `benchmark.environment.validate_processes(state, output, *, allow_health_probe: bool = True)` keeps current behavior by default; `False` requires exactly the server process.
- `DockerEnvironment(..., health_policy: str = CONTAINER_HEALTHCHECK)` stores the validated policy.

TDD cycle: add `tests/test_benchmark_healthcheck.py`; verify it fails because the module/signatures do not exist; implement only these interfaces; run `make test-benchmark`; commit.

### Task 2: Bounded external readiness

**Files:** Modify `benchmark/healthcheck.py`, `benchmark/environment.py`, `tests/test_benchmark_healthcheck.py`, and focused environment tests.

**Interfaces:**
- `wait_external_readiness(base_url, implementation_id, check_state, *, timeout_seconds=60.0, request_timeout=2.0, clock=time.monotonic, sleep=time.sleep, reader=read_response)` returns `{"attempts": int, "duration_seconds": float}`.
- It reuses the documented `/health` `Case`, `read_response`, and `assert_response`; transport failures retry only until the absolute deadline, while wrong status/content-type/payload fails immediately.
- Controlled `DockerEnvironment.start()` starts PostgreSQL with `--detach --wait --wait-timeout 60`, starts the selected API detached without `--wait`, captures/validates identity, performs external readiness, and then calls `validate_processes(..., allow_health_probe=False)`.
- Baseline `start()` remains the current single `up --detach --wait --wait-timeout 60 <implementation>` path.

TDD cycle: command-capture and deterministic fake-clock readiness tests Red; minimal implementation; `make test-benchmark` Green; commit.

### Task 3: Interval-scoped Docker probe event audit

**Files:** Modify `benchmark/healthcheck.py`, `benchmark/environment.py`, `tests/test_benchmark_healthcheck.py`.

**Interfaces:**
- `parse_exec_events(raw: bytes, *, container_id: str, probe_command: list[str], max_events: int = 128) -> dict` parses bounded Docker JSONL and validates complete health-probe exec lifecycles.
- `require_no_probe_activity(summary: dict) -> None` fails controlled mode on probe activity.
- `DockerEnvironment.probe_events(started_at, completed_at)` uses container/type/time filters and retrieves history immediately after each interval; it never runs a collector concurrently with `oha`.
- `measure()` attaches probe-event diagnostics only when investigation auditing is enabled; normal benchmark result fields stay unchanged.

TDD cycle: malformed/wrong-container/overflow/lifecycle/controlled-activity tests Red; implement; `make test-benchmark` Green; commit.

### Task 4: Diagnostic-only A/B runner and descriptive analysis

**Files:** Create `benchmark/healthcheck_investigation.py`, `tests/test_benchmark_healthcheck_investigation.py`; modify `Makefile`; add publication-safety regression tests using `benchmark.report.validate_report`.

**Interfaces:**
- `analyze_pair(baseline, controlled) -> dict` reports selected absolute/percentage differences, each three-run min/max, and paired direction counts for throughput, mean latency, and peak memory; zero denominators produce `null` percentage rather than division failure.
- CLI: `python -m benchmark.healthcheck_investigation --output .cache/healthcheck-investigation/result.json`.
- `make healthcheck-investigation` invokes only that diagnostic CLI.
- Orchestration alternates policy order by registry index, creates a fresh environment per policy, uses the unchanged full `PROFILE`, fails without writing partial output, and only permits output under `.cache/healthcheck-investigation/`.
- Diagnostic root fields include `schema_version`, `official: false`, `publishable: false`, `mode: "healthcheck-investigation"`, source/provenance/benchmark identity, policy order, full conditions, implementation observations, and analysis.
- Normal official report validation must reject diagnostic artifacts.

TDD cycle: analysis/orchestration/path/publication tests Red; implement; `make test-benchmark && make test-workflows` Green; commit.

### Task 5: Temporary PR full-profile evidence, decision record, and final cleanup

**Files:** Temporarily modify `.github/workflows/ci.yml` and workflow tests; create `docs/investigations/2026-09-healthcheck-interference.md`; update `docs/METHODOLOGY.md` only after evidence; remove the temporary CI job before merge.

Temporary job contract:
- name `healthcheck-investigation`;
- PR-only and branch-specific;
- `ubuntu-24.04`, read-only repository permissions, pinned actions, finite timeout no greater than 90 minutes;
- runs `make healthcheck-investigation` and uploads only `.cache/healthcheck-investigation/` diagnostic/raw evidence;
- no official/publish/Pages command or write credential;
- scoped cleanup under `if: always()`.

Evidence gate:
- download the artifact and verify source SHA/cohort/full conditions, baseline probe-event presence, controlled probe-event absence, selected deltas, and three-run spreads;
- record exact workflow run/job/artifact identity and digest;
- if effects are small/inconsistent relative to spread, retain the current official policy and disclose included probe overhead in methodology;
- if effects are consistent/practically relevant, stop and obtain explicit owner methodology approval before any official behavior change.

Finalization:
- remove the temporary job and its temporary-positive workflow assertion;
- final CI topology returns to `plan/shared/implementation/smoke/required`;
- run normal split CI, self-review, verify `.github/workflows/benchmark.yml` remains sequential and results/history blobs are unchanged;
- squash merge only when final head is Green; post-merge verify exact-main CI and Pages; do not dispatch an official benchmark without separate approval.
