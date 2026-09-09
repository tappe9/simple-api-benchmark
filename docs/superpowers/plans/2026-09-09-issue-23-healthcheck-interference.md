# Issue #23 Health-Check Interference Investigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-publishing same-runner A/B investigation that measures the existing recurring API-container healthcheck policy against bounded external readiness without changing official benchmark behavior.

**Architecture:** Keep `DockerEnvironment` default behavior exactly compatible with the current `container-healthcheck` path. Put health-policy parsing, deterministic Compose override generation, readiness validation, Docker event parsing, and descriptive comparison helpers in a focused `benchmark/healthcheck.py`; add `benchmark/healthcheck_investigation.py` as the only orchestration entry point that runs both policies and writes a diagnostic-only artifact. A temporary PR-only CI job gathers full-profile evidence and is removed before merge.

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

**Files:**
- Create: `benchmark/healthcheck.py`
- Modify: `benchmark/environment.py`
- Modify: `tests/test_benchmark_environment.py`
- Create: `tests/test_benchmark_healthcheck.py`

**Interfaces:**
- Produces: `CONTAINER_HEALTHCHECK`, `EXTERNAL_READINESS`, `validate_policy(value: str) -> str`, `override_text(implementation_id: str) -> str`.
- Changes: `validate_processes(state: dict, output: str, *, allow_health_probe: bool = True) -> None` while preserving the current default.
- Changes: `DockerEnvironment(..., health_policy: str = CONTAINER_HEALTHCHECK)`.

- [ ] **Step 1: Write failing policy/override/process tests**

```python
class PolicyTests(unittest.TestCase):
    def test_default_policy_is_current_container_healthcheck(self):
        env = environment.DockerEnvironment(Path('/fake/oha'), Path(self.directory))
        self.assertEqual(env.health_policy, healthcheck.CONTAINER_HEALTHCHECK)

    def test_external_override_disables_only_registered_api_health(self):
        text = healthcheck.override_text('go-gin')
        self.assertIn('go-gin:', text)
        self.assertIn('disable: true', text)
        self.assertNotIn('postgres:', text)

    def test_controlled_process_contract_requires_exactly_one_server(self):
        value = process_state_with_healthcheck()
        one = 'PID COMMAND\n123 /go-gin serve\n'
        healthcheck.validate_processes(value, one, allow_health_probe=False)
        with self.assertRaises(BenchmarkFailure):
            healthcheck.validate_processes(value, one + '124 /go-gin healthcheck\n', allow_health_probe=False)
```

- [ ] **Step 2: Run focused tests and verify Red**

Run: `python -m unittest tests.test_benchmark_healthcheck tests.test_benchmark_environment -v`
Expected: FAIL because `benchmark.healthcheck` and policy-aware signatures do not exist.

- [ ] **Step 3: Implement minimal policy support**

```python
CONTAINER_HEALTHCHECK = 'container-healthcheck'
EXTERNAL_READINESS = 'external-readiness'
_POLICIES = (CONTAINER_HEALTHCHECK, EXTERNAL_READINESS)

def validate_policy(value: str) -> str:
    require(value in _POLICIES, 'unsupported API health policy')
    return value

def override_text(implementation_id: str) -> str:
    implementation(implementation_id)
    return f'services:\n  {implementation_id}:\n    healthcheck:\n      disable: true\n'
```

Move or delegate process validation so `allow_health_probe=False` accepts exactly the server command and rejects all additional container processes. Keep `allow_health_probe=True` byte-for-byte equivalent in behavior to the current rule.

- [ ] **Step 4: Run focused tests and verify Green**

Run: `python -m unittest tests.test_benchmark_healthcheck tests.test_benchmark_environment -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark/healthcheck.py benchmark/environment.py tests/test_benchmark_healthcheck.py tests/test_benchmark_environment.py
git commit -m 'test: define benchmark health policies'
```

### Task 2: Bounded external readiness

**Files:**
- Modify: `benchmark/healthcheck.py`
- Modify: `benchmark/environment.py`
- Modify: `tests/test_benchmark_healthcheck.py`
- Modify: `tests/test_benchmark_environment.py`

**Interfaces:**
- Produces: `wait_external_readiness(base_url: str, implementation_id: str, check_state: Callable[[], None], *, timeout_seconds: float = 60.0, request_timeout: float = 2.0, clock=time.monotonic, sleep=time.sleep, reader=read_response) -> dict` returning `{"attempts": int, "duration_seconds": float}`.
- `DockerEnvironment.start()` uses current `up --detach --wait --wait-timeout 60` only for baseline. Controlled mode starts PostgreSQL with `--wait`, starts the API detached without `--wait`, captures/validates identity, runs external readiness, then enforces `allow_health_probe=False`.

- [ ] **Step 1: Write failing readiness tests**

```python
def test_external_readiness_requires_exact_health_contract_and_deadline(self):
    responses = iter([ContractFailure('transport: refused'), Response(200, 'application/json', b'{"status":"ok"}')])
    result = healthcheck.wait_external_readiness(..., reader=lambda *_a, **_k: next(responses), clock=fake_clock, sleep=fake_sleep)
    self.assertEqual(result['attempts'], 2)

for bad in (Response(200, 'text/plain', b'{"status":"ok"}'), Response(200, 'application/json', b'{"status":"bad"}')):
    with self.assertRaises(...): ...
```

Add an environment command-capture test proving controlled mode starts `postgres` with `--wait` but does not pass `--wait` when starting the API.

- [ ] **Step 2: Verify Red**

Run: `python -m unittest tests.test_benchmark_healthcheck tests.test_benchmark_environment -v`
Expected: FAIL because external readiness/start path is absent.

- [ ] **Step 3: Implement bounded readiness**

Reuse `contract_test.Case`, `Response`, `assert_response`, `read_response`, and the `/health` case loaded from `load_cases()` rather than duplicating response semantics. Call `check_state()` before each attempt and after success. Convert timeout/transport failures into bounded retries until the absolute deadline; contract-shape/status errors fail immediately.

- [ ] **Step 4: Verify Green and existing runner tests**

Run: `make test-benchmark`
Expected: PASS, including existing `DockerEnvironment` process/oha parser contracts.

- [ ] **Step 5: Commit**

```bash
git add benchmark/healthcheck.py benchmark/environment.py tests/test_benchmark_healthcheck.py tests/test_benchmark_environment.py
git commit -m 'feat: add bounded external API readiness'
```

### Task 3: Interval-scoped Docker probe event audit

**Files:**
- Modify: `benchmark/healthcheck.py`
- Modify: `benchmark/environment.py`
- Modify: `tests/test_benchmark_healthcheck.py`

**Interfaces:**
- Produces: `parse_exec_events(raw: bytes, *, container_id: str, probe_command: list[str], max_events: int = 128) -> dict`.
- Produces: `DockerEnvironment.probe_events(started_at: datetime, completed_at: datetime) -> dict` that executes `docker events --since ... --until ... --filter type=container --filter container=<id> --format '{{json .}}'`, with bounded output and no long-lived collector.
- `measure()` records interval start/end and, only when investigation event auditing is enabled, attaches `probe_events` to the diagnostic summary. Normal benchmark summaries remain unchanged.

- [ ] **Step 1: Write failing parser/audit tests**

```python
def test_event_parser_counts_only_matching_owned_health_execs(self):
    raw = b'...exec_create...exec_start...exec_die...'
    result = healthcheck.parse_exec_events(raw, container_id='a'*64, probe_command=['/go-gin','healthcheck'])
    self.assertEqual(result['probe_execs'], 1)


def test_controlled_mode_rejects_probe_exec_activity(self):
    with self.assertRaises(BenchmarkFailure):
        healthcheck.require_no_probe_activity({'probe_execs': 1})
```

Also reject malformed JSONL, wrong container IDs, >128 events, unmatched exec lifecycle, and unexpected controlled-mode execs.

- [ ] **Step 2: Verify Red**

Run: `python -m unittest tests.test_benchmark_healthcheck -v`
Expected: FAIL because event parsing/audit support is absent.

- [ ] **Step 3: Implement event parsing and bounded retrieval**

Use strict JSONL parsing. Attribute health execs by container ID and Docker event attributes containing the configured probe command; require complete create/start/die lifecycles. Retrieve events immediately after each interval using explicit RFC3339 UTC boundaries. Do not run `docker events` concurrently with `oha`.

- [ ] **Step 4: Verify Green**

Run: `make test-benchmark`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark/healthcheck.py benchmark/environment.py tests/test_benchmark_healthcheck.py
git commit -m 'feat: audit health probe activity per measurement interval'
```

### Task 4: Diagnostic-only A/B runner and descriptive analysis

**Files:**
- Create: `benchmark/healthcheck_investigation.py`
- Create: `tests/test_benchmark_healthcheck_investigation.py`
- Modify: `Makefile`
- Modify: `benchmark/report.py`
- Modify: `tests/test_benchmark_report.py`

**Interfaces:**
- Produces: `analyze_pair(baseline: dict, controlled: dict) -> dict` with selected-value absolute/percent deltas, three-run min/max, and paired-direction counts for throughput, latency, memory.
- Produces CLI: `python -m benchmark.healthcheck_investigation --output .cache/healthcheck-investigation/result.json`.
- Adds `make healthcheck-investigation` as diagnostic-only command.

- [ ] **Step 1: Write failing analysis/publication-safety tests**

```python
def test_analysis_handles_positive_negative_zero_and_zero_denominator(self): ...

def test_diagnostic_identity_is_never_official(self):
    artifact = {'official': False, 'publishable': False, 'mode': 'healthcheck-investigation', ...}
    with self.assertRaises(BenchmarkFailure):
        report.validate_report(artifact)
```

Add orchestration tests using fake environments to prove alternating policy order by registry index, both policies use the exact full `PROFILE`, failures do not write partial output, and output path must remain under `.cache/healthcheck-investigation/`.

- [ ] **Step 2: Verify Red**

Run: `python -m unittest tests.test_benchmark_healthcheck_investigation tests.test_benchmark_report -v`
Expected: FAIL because investigation runner/analysis are absent.

- [ ] **Step 3: Implement minimal diagnostic runner**

For each active member, run two fresh `DockerEnvironment` instances sequentially, alternating policy order by registry index. Reuse the existing full-profile measurement/selection contracts, but write only the dedicated diagnostic schema and raw artifacts below `.cache/healthcheck-investigation/`. Mark `official: false`, `publishable: false`, `mode: healthcheck-investigation`.

- [ ] **Step 4: Verify Green and all non-Docker unit gates**

Run: `make test-benchmark && make test-workflows`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark/healthcheck_investigation.py tests/test_benchmark_healthcheck_investigation.py Makefile benchmark/report.py tests/test_benchmark_report.py
git commit -m 'feat: add non-publishing healthcheck A/B investigation'
```

### Task 5: Temporary PR full-profile evidence, decision record, and final cleanup

**Files:**
- Temporarily modify: `.github/workflows/ci.yml`
- Modify: `tests/test_workflows.py`
- Create after evidence: `docs/investigations/2026-09-healthcheck-interference.md`
- Modify after evidence: `docs/METHODOLOGY.md`
- Final state: remove temporary investigation job from `.github/workflows/ci.yml` before merge.

**Interfaces:**
- Temporary job name: `healthcheck-investigation`.
- Artifact name: `healthcheck-investigation-${{ github.run_id }}-${{ github.run_attempt }}`.
- Final normal CI job topology remains `plan`, `shared`, `implementation`, `smoke`, `required` only.

- [ ] **Step 1: Add a failing workflow contract for the temporary diagnostic boundary**

```python
def test_healthcheck_investigation_job_is_read_only_and_non_publishing(self):
    job = load('ci.yml')['jobs']['healthcheck-investigation']
    self.assertNotIn('benchmark.official', str(job))
    self.assertNotIn('benchmark.publish', str(job))
    self.assertIn('make healthcheck-investigation', str(job))
    self.assertIn('.cache/healthcheck-investigation', str(job))
```

- [ ] **Step 2: Verify Red, then add the temporary job and open draft PR**

Run through PR CI. Expected initial workflow test failure until the temporary job exists. The job uses `ubuntu-24.04`, read-only permissions, pinned checkout/setup-python/upload-artifact actions, finite timeout <= 90 minutes, and `if: github.event_name == 'pull_request' && github.head_ref == 'investigate/issue-23-healthcheck-interference'`.

- [ ] **Step 3: Collect and audit the full-profile artifact**

Wait for the temporary job to complete. Download the artifact, validate schema/source commit/cohort/conditions, verify baseline probe events are present and controlled probe events are absent, calculate selected deltas and three-run spreads, and record exact run/job IDs and artifact digest.

- [ ] **Step 4: Record evidence and choose the supported outcome**

Create `docs/investigations/2026-09-healthcheck-interference.md` containing measured raw/selected summaries and descriptive interpretation. If the effect is small/inconsistent relative to observed spread, retain current official policy and update `docs/METHODOLOGY.md` to disclose recurring probes are included. If effect is consistent/practically relevant, stop before changing official behavior and present the evidence to the owner for separate methodology approval.

- [ ] **Step 5: Remove the temporary full-profile job before merge**

Update workflow tests to assert the permanent topology is restored and no `healthcheck-investigation` job remains. Keep reusable investigation code/command and the evidence document only if they are useful to reproduce/audit the decision; no permanent PR runtime doubling.

- [ ] **Step 6: Run final quality gates**

Final PR head must pass normal split CI: `plan`, `shared`, all registry implementation jobs, `smoke`, `required`. Confirm `.github/workflows/benchmark.yml` remains sequential and unchanged, Pages trust tests remain Green, and `results/latest.json`/history blobs are unchanged from base.

- [ ] **Step 7: Self-review, mark ready, squash merge, and post-merge verify**

Re-review the diff for methodology drift/publication paths, check latest head CI, squash merge only after all final gates pass, then verify exact-main CI and Pages. Do not dispatch an official benchmark as part of this issue unless the owner separately approves a methodology change.
