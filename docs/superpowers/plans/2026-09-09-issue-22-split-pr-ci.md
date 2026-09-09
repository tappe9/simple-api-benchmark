# Split Pull Request CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split pull-request CI into shared, registry-driven per-implementation, smoke, and fail-closed aggregate jobs while preserving official sequential measurements and all existing coverage.

**Architecture:** Keep `benchmark/implementations.json` authoritative. Add a small Python CI helper that emits matrix JSON and validates aggregate predecessor results; use it from one `CI` workflow with `plan`, `shared`, `implementation`, `smoke`, and `required` jobs. Local Make targets stay sequential; official benchmark workflow stays one sequential measurement job.

**Tech Stack:** GitHub Actions YAML, Python 3.10+, existing benchmark registry module, unittest, Make, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-09-issue-22-split-pr-ci-design.md`

## Global Constraints

- Workflow-level PR permissions remain `contents: read`.
- All Actions remain pinned to commit SHAs and checkout keeps `persist-credentials: false`.
- The implementation matrix must derive from `benchmark/implementations.json`; no second YAML implementation list.
- Matrix jobs must own unique Compose projects and clean only their own project under `if: always()`.
- `required` must run with `if: always()` and fail for any predecessor result other than `success`.
- Existing Python 3.10, failure-path, real-container contract, smoke, formatting/lint, registry, site, Pages, DB, benchmark, and optimized-mode coverage must remain represented.
- `make test` and `make test-implementations` remain sequential locally.
- `.github/workflows/benchmark.yml` remains sequential and non-matrix.
- No official benchmark dispatch, result/history rewrite, release/tag, branch-protection change, or unrelated issue implementation.

---

### Task 1: CI helper contracts

**Files:**
- Create: `benchmark/ci.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Produces: `matrix_payload() -> str`, compact JSON object with `include` entries containing registry implementation IDs.
- Produces: `require_success(results: dict[str, str]) -> None`, returning normally only if every value is `success`, otherwise raising `ValueError`.
- CLI: `python -m benchmark.ci matrix` prints the payload; `python -m benchmark.ci require-success key=result ...` exits non-zero on failure/cancelled/skipped.

- [ ] Add failing tests for registry-derived matrix IDs/order and aggregate all-success/failure/cancelled/skipped behavior.
- [ ] Run focused workflow tests and record expected Red failures because `benchmark.ci` does not exist.
- [ ] Implement only the helper/CLI required by the tests.
- [ ] Re-run focused tests to Green and refactor names/output determinism without changing behavior.
- [ ] Commit with `feat: add registry-backed CI planning helpers`.

### Task 2: Split CI workflow

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- `plan.outputs.matrix` is the sole matrix input for `implementation.strategy.matrix`.
- `implementation` sets `IMPLEMENTATION_ID` from matrix data through job env and sets `COMPOSE_PROJECT_NAME` from trusted run metadata plus the implementation ID.
- `required.needs` is exactly `plan`, `shared`, `implementation`, `smoke` and calls `benchmark.ci require-success` with their job results.

- [ ] Add failing workflow-structure tests requiring jobs `plan/shared/implementation/smoke/required`, matrix from `needs.plan.outputs.matrix`, unique Compose project ownership, fail-closed aggregate, and preserved coverage mapping.
- [ ] Run `python -m unittest tests.test_workflows -v` and record Red failures against the current single `quality` job.
- [ ] Replace `quality` with the approved topology, reusing existing pinned actions and commands.
- [ ] Ensure each implementation matrix entry runs its existing generated Make acceptance target plus `CONTRACT_IMPL=$IMPLEMENTATION_ID make test-contract`; cleanup is always-run and project-scoped.
- [ ] Keep non-publishing smoke in its own sequential job with dirty/untracked guards.
- [ ] Re-run workflow tests and actionlint-compatible syntax checks to Green.
- [ ] Commit with `ci: split pull request checks by implementation`.

### Task 3: Coverage, trust, and local docs

**Files:**
- Modify: `tests/test_workflows.py`
- Modify: `CONTRIBUTING.md`
- Modify: `ARCHITECTURE.md` if its CI description would otherwise become stale.

**Interfaces:**
- Tests derive required implementation acceptance/failure paths from `benchmark/implementations.json`.
- Documentation names focused local commands without changing `make test` semantics.

- [ ] Add/strengthen tests proving every registry implementation is covered by matrix acceptance + focused contract execution, Pages still trusts successful main `CI` only, and official benchmark remains one non-matrix measure job.
- [ ] Update contributor docs with `make test-workflows`, one `make test-<implementation>` plus focused `CONTRACT_IMPL=<id> make test-contract`, and `make benchmark-smoke`.
- [ ] Run workflow/unit/site/registry checks and confirm Green.
- [ ] Commit with `docs: explain focused CI checks`.

### Task 4: Real CI verification and timeout tuning

**Files:**
- Modify: `.github/workflows/ci.yml` only if observed runtimes justify timeout changes.
- Modify: PR body / Issue #22 comment for evidence.

- [ ] Open a draft PR from `feat/issue-22-split-pr-ci` to `main` with `Closes #22` and the design constraints.
- [ ] Let GitHub Actions execute real `shared`, four `implementation` matrix entries, `smoke`, and `required` jobs.
- [ ] Inspect exact job runtimes and failure/cleanup evidence; adjust timeouts only if the observed margins are poor, then re-run to final Green.
- [ ] Confirm no PR artifact can become a trusted Pages/publication input and no official benchmark workflow was dispatched.
- [ ] Record final exact-head run IDs and runtimes in the PR.

### Task 5: Review, merge, and post-merge verification

**Files:** none unless review finds a defect.

- [ ] Self-review the complete PR diff against Issue #22 acceptance criteria and the spec; fix any defect with TDD.
- [ ] Verify latest head, reviews/threads, mergeability, and exact-head CI success including `required`.
- [ ] Squash merge with expected head SHA.
- [ ] Verify exact merged `main` CI and Pages workflow success.
- [ ] Confirm `results/latest.json` and retained history bytes are unchanged and no official benchmark was dispatched.
- [ ] Add a concise Issue #22 completion record with runtime evidence and post-merge verification.
