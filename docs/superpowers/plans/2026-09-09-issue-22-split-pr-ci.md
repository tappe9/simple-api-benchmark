# Split Pull Request CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split pull-request correctness CI into registry-driven isolated implementation jobs while preserving all existing gates, a fail-closed stable aggregate result, and sequential official measurements.

**Architecture:** Keep the existing `CI` workflow name and read-only trust boundary. Add a small `benchmark.ci` helper for deterministic registry matrix output and fail-closed aggregate-result validation; use it from a five-stage `plan → shared / implementation / smoke → required` workflow. Keep local Make behavior and the official benchmark workflow sequential.

**Tech Stack:** GitHub Actions YAML, Python 3.10+ standard library, existing benchmark registry, Docker Compose v2, unittest, Make.

**Spec:** `docs/superpowers/specs/2026-09-09-issue-22-split-pr-ci-design.md`

## Global Constraints

- The workflow name remains exactly `CI` and workflow permissions remain `contents: read`.
- Every checkout keeps `persist-credentials: false`; existing actions remain pinned to 40-character commit SHAs.
- The implementation matrix must be derived from `benchmark/implementations.json`; do not add a second implementation-ID list to YAML.
- Each implementation matrix job owns a unique Compose project containing run ID, run attempt, and implementation ID.
- `required` must run with `if: always()` and fail on failure, cancelled, or skipped predecessor results.
- `make test` and `make test-implementations` remain sequential locally.
- `.github/workflows/benchmark.yml` remains one sequential `measure` job with one `python -m benchmark.official` invocation.
- Do not dispatch an official benchmark, alter published result/history JSON, change measurement conditions, or modify branch protection.

---

### Task 1: Specify the split CI contract in Red tests

**Files:**
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Consumes: `benchmark/implementations.json` registry entries and existing `load()` YAML helper.
- Produces: failing assertions that define the required job topology, matrix derivation, Compose isolation, coverage mapping, aggregate behavior, Pages trust compatibility, and unchanged official measurement boundary.

- [ ] **Step 1: Replace the monolithic-CI expectations with explicit split-job assertions**

Add tests that require `set(ci["jobs"]) == {"plan", "shared", "implementation", "smoke", "required"}`; `implementation["needs"] == "plan"`; its matrix expression consumes only `needs.plan.outputs.matrix`; `required["needs"]` names all four predecessor jobs; and `required["if"] == "always()"`.

- [ ] **Step 2: Require registry-derived coverage and owned Compose projects**

Parse `benchmark/implementations.json`; assert the YAML does not contain a literal static matrix list of the four IDs; assert the implementation job passes the selected ID through `env`; assert `COMPOSE_PROJECT_NAME` contains `github.run_id`, `github.run_attempt`, and the matrix implementation value; assert cleanup uses the same project and `if: always()`; assert acceptance and focused contract commands are present while local Make sequencing tests remain unchanged.

- [ ] **Step 3: Require fail-closed aggregate and preserved shared/smoke gates**

Assert `shared` contains Python 3.10 compatibility, workflow/security checks, registry, site, DB, benchmark normal/optimized checks; assert `smoke` contains `make benchmark-smoke` plus dirty/untracked-tree guards; assert `required` runs `python -m benchmark.ci require-success` with predecessor results supplied via `env`, not shell interpolation.

- [ ] **Step 4: Run the focused workflow tests and capture Red**

Run through PR CI after opening the draft PR:

```bash
python -m unittest discover -s tests -p test_workflows.py -v
```

Expected: FAIL because current `ci.yml` only has `quality` and lacks `benchmark.ci` aggregate behavior.

- [ ] **Step 5: Commit the Red tests**

```bash
git add tests/test_workflows.py
git commit -m "test: specify split pull request CI contract"
```

---

### Task 2: Add deterministic CI helper logic

**Files:**
- Create: `benchmark/ci.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Consumes: `benchmark.registry.implementation_ids()`.
- Produces: `matrix_payload() -> dict[str, list[str]]`, `require_success(results: dict[str, str]) -> None`, CLI command `python -m benchmark.ci matrix`, and CLI command `python -m benchmark.ci require-success`.

- [ ] **Step 1: Add failing unit tests for matrix and aggregate decisions**

Add tests equivalent to:

```python
from benchmark import ci as ci_support

self.assertEqual(
    ci_support.matrix_payload(),
    {"implementation": ["go-gin", "rust-actix", "node-fastify", "python-fastapi"]},
)
for bad in ("failure", "cancelled", "skipped", "", "success "):
    with self.subTest(bad=bad), self.assertRaises(RuntimeError):
        ci_support.require_success({"plan": "success", "shared": bad, "implementation": "success", "smoke": "success"})
ci_support.require_success({"plan": "success", "shared": "success", "implementation": "success", "smoke": "success"})
```

Also patch the registry with the existing extended fixture and assert `matrix_payload()` expands automatically without changing YAML.

- [ ] **Step 2: Run focused tests and verify the new tests fail**

Run:

```bash
python -m unittest discover -s tests -p test_workflows.py -v
```

Expected: FAIL with missing `benchmark.ci`.

- [ ] **Step 3: Implement the minimal helper**

Create `benchmark/ci.py` using only the standard library. `matrix_payload()` returns `{"implementation": list(registry.implementation_ids())}`. `require_success()` requires exactly `plan`, `shared`, `implementation`, and `smoke` keys and requires every value to equal the literal string `success`. CLI `matrix` prints one GitHub-output line `matrix=<compact-json>`; CLI `require-success` reads `PLAN_RESULT`, `SHARED_RESULT`, `IMPLEMENTATION_RESULT`, and `SMOKE_RESULT` from the environment, validates them, and exits non-zero with a concise stderr message on any invalid result.

- [ ] **Step 4: Run focused tests and verify helper Green**

Run:

```bash
python -m unittest discover -s tests -p test_workflows.py -v
python -m benchmark.ci matrix
```

Expected: PASS; matrix output is compact JSON in registry order.

- [ ] **Step 5: Commit**

```bash
git add benchmark/ci.py tests/test_workflows.py
git commit -m "feat: add fail-closed CI support helpers"
```

---

### Task 3: Split the GitHub Actions CI workflow

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Consumes: `benchmark.ci matrix` output and existing Make targets.
- Produces: jobs `plan`, `shared`, `implementation`, `smoke`, `required`; stable check name `CI / required`.

- [ ] **Step 1: Implement `plan`**

Checkout with fetch depth 1 and no persisted credentials; setup Python 3.10; run registry check; append `python -m benchmark.ci matrix` output to `$GITHUB_OUTPUT`; expose that step's `matrix` as job output. Give the job a bounded timeout suitable for source-only work.

- [ ] **Step 2: Implement `shared`**

Move the current source/tooling gates here: Python 3.10 benchmark + contract-unit compatibility, pinned Python/Go/Node/Rust workflow tooling needed by shared checks, actionlint, workflow tests, Ruff format/lint, README/source drift, `make test-registry`, `make test-site`, `make test-db`, `make test-benchmark`, and optimized-mode benchmark tests. Retain failure-only formatting diagnostic artifact and read-only permissions.

- [ ] **Step 3: Implement registry-driven `implementation` matrix**

Set `needs: plan`, `strategy.fail-fast: false`, and `strategy.matrix` from `fromJSON(needs.plan.outputs.matrix)`. Pass `${{ matrix.implementation }}` only through job `env` as `IMPLEMENTATION_ID`; define an owned `COMPOSE_PROJECT_NAME` including run ID, attempt, and implementation ID. Run `make test-$IMPLEMENTATION_ID` and `make test-contract CONTRACT_IMPL=$IMPLEMENTATION_ID COMPOSE="docker compose -p $COMPOSE_PROJECT_NAME"`; cleanup the exact project with `if: always()`.

- [ ] **Step 4: Implement separate sequential `smoke`**

Use one runner and one owned project; preserve `make benchmark-smoke`, `git diff --exit-code HEAD`, untracked-file check, and `if: always()` cleanup. Do not upload or publish benchmark output.

- [ ] **Step 5: Implement stable `required` aggregate**

Set `needs: [plan, shared, implementation, smoke]` and `if: always()`. Setup Python and run `python -m benchmark.ci require-success`. Supply `${{ needs.<job>.result }}` only through the four environment variables. Do not write permissions or artifacts.

- [ ] **Step 6: Run workflow contract checks**

Run:

```bash
python -m unittest discover -s tests -p test_workflows.py -v
actionlint -color
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml tests/test_workflows.py
git commit -m "ci: split pull request checks by implementation"
```

---

### Task 4: Document focused CI checks and timeout policy

**Files:**
- Modify: `CONTRIBUTING.md`
- Modify: `docs/AUTOMATION.md`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: final job topology and existing focused Make commands.
- Produces: contributor-facing commands and recorded historical/observed timeout basis without changing benchmark methodology.

- [ ] **Step 1: Add contributor commands**

Document:

```bash
make test-workflows
make test-go-gin
make test-contract CONTRACT_IMPL=go-gin
make benchmark-smoke
make test
```

Explain that PR CI runs implementation correctness on isolated runners, while local `make test` remains sequential because local services share port 8080.

- [ ] **Step 2: Document CI topology and trust boundary**

In `docs/AUTOMATION.md`, describe the five jobs, registry-derived matrix, unique Compose project ownership, stable `required` aggregate, read-only PR permissions, and that Pages still trusts only successful `CI` push runs on exact main SHA.

- [ ] **Step 3: Record timeout evidence correctly**

Record historical evidence separately: main CI run `34205435379` ≈10 minutes; official run `33979190013` ≈25 minutes including publication. State that final split-job timeouts are based on observed PR job runtimes plus margin; do not claim eight-framework measurements.

- [ ] **Step 4: Run documentation/security checks**

Run:

```bash
python -m unittest discover -s tests -p test_workflows.py -v
python -m benchmark.generate_readme --check
git diff --check origin/main...HEAD
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add CONTRIBUTING.md docs/AUTOMATION.md tests/test_workflows.py
git commit -m "docs: document split CI validation"
```

---

### Task 5: Full PR verification, runtime review, and finalization

**Files:**
- Modify only if a verified failure requires a scoped fix.

**Interfaces:**
- Consumes: completed implementation branch and GitHub Actions runtime evidence.
- Produces: merge-ready PR with exact-head evidence and justified timeouts.

- [ ] **Step 1: Run the complete PR CI on the exact head**

Expected jobs: `plan`, `shared`, four `implementation (<id>)` matrix jobs, `smoke`, and `required`. Every required job must conclude `success`.

- [ ] **Step 2: Inspect job runtimes and timeout margin**

Compare each observed job duration with its configured timeout. If a timeout has less than a comfortable operational margin or is vastly excessive, adjust it with a test-backed workflow change and rerun exact-head CI. Keep the official 60-minute measurement budget unchanged unless independent evidence shows it is unsafe; this issue does not require changing it.

- [ ] **Step 3: Verify coverage and security**

Confirm Python 3.10, DB, each acceptance/failure path, focused real-container contract, normal/optimized benchmark tests, non-publishing smoke, pinned actions, read-only PR permissions, dirty-tree guards, cleanup, and aggregate behavior all ran. Confirm no PR artifact is used by Pages or official publication.

- [ ] **Step 4: Self-review the PR diff**

Check scope, registry single-source behavior, Compose isolation, aggregate fail-closed semantics, unchanged local sequencing, unchanged official benchmark behavior, Pages trust compatibility, and absence of published result/history changes.

- [ ] **Step 5: Update PR body and merge**

Record final exact head SHA, CI run, observed job runtimes, historical timing evidence, and verification boundaries. Remove draft status only after all required jobs are Green. Re-read main/head and unresolved review threads, then squash merge using the expected head SHA.

- [ ] **Step 6: Post-merge verification**

Verify the squash commit is current main; exact-main `CI / required` and all component jobs succeed; Pages runs from the successful main CI and deploys the same main SHA; Pages artifact is valid; `results/latest.json` and history bytes are unchanged; no official benchmark was dispatched by this issue. Public HTTP/browser status must be reported separately from Actions deployment evidence.
