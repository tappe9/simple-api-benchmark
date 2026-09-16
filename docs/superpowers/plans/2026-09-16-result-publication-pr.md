# Result-only publication PR implementation plan

> For agentic workers: use superpowers:executing-plans task by task. Status is recorded per task below.

**Goal:** Prepare the approved no-bypass result-PR publisher without applying live settings or producing measurements.

**Architecture:** Keep deterministic generated content and the source-parent contract. Separate proposal, read-only CI waiting and exact-head squash merge. Reuse the existing Pages call with the actual publication SHA. The unset publication mode retains the legacy path during the explicitly staged rollout; selecting PR mode never falls back to direct push.

**Tech Stack:** Python >=3.10 standard library, unittest, temporary real Git repositories, SHA-pinned Actions.

**Spec:** Issue #52's 2026-09-16 design checkpoint, approved by the maintainer in chat. Approval covers code/tests/PR; App/environment, effective rules and an official publication need a separate rollout step.

## Global constraints

- Keep applications, locks, registry/cohorts, measured results, old reports, workload and dependency pins unchanged.
- PR CI stays read-only; all eight acceptance/contract jobs, smoke, Axum and fail-closed `required` remain.
- Never put keys in source, token values in arguments/logs/receipts, or tokens in CI-wait/measurement/Pages jobs.
- Never rebase a stale result, force-push, bypass rules or merge ordinary code PRs automatically.
- The REST merge API guards head, not base. Strict/no-bypass effective policy and an actual stale-base race test are rollout prerequisites, not proven by a fake service.
- API/auth/transport errors are failures, not evidence that a resource is absent.
- Do not create App/environment/secrets, change rules, or run a real official benchmark in this preparation PR.

## Tasks

### 1. Deterministic candidate transaction

Files: `benchmark/publish.py`, `tests/test_benchmark_result_pr.py`.

- [x] Add a real temporary-Git test calling `prepare_candidate(report, root, expected_context=context)` twice, asserting identical SHA/tree, sole measured-source parent, exactly seven paths, no `[skip ci]`, clean checkout and unchanged remote main.
- [x] Observe RED using `python -m unittest discover -s tests -p test_benchmark_result_pr.py -v`.
- [x] Extract the existing report/raw/clean-source audit and generated tree logic into `prepare_candidate`; preserve the legacy `publish` wrapper and its stale-main/normal fast-forward checks.
- [x] Run candidate plus existing publication tests. The staged preparation is committed together after review rather than landing a separate production transition.

### 2. Typed PR and complete CI validation

Files: `benchmark/result_pr.py`, `benchmark/result_pr_checks.py`, `benchmark/github_api.py`, `tests/test_benchmark_result_pr*.py`.

- [x] Write rejection cases for wrong source/head/tree/PR/issuer/run/attempt, incomplete/duplicate/missing jobs, failed/cancelled/skipped/neutral conclusions and malformed API responses.
- [x] Observe RED before implementing each boundary.
- [x] Build a same-repository bounded JSON client without redirects or blind write retries. Re-derive the candidate from the same raw artifact on every job; never trust branch names or stored receipts alone.
- [x] Implement deterministic result branch/PR creation, read-only bounded CI waiting, complete expected-job validation, and idempotent exact-head squash merge with post-merge parent/tree checks.
- [x] Exercise real temporary Git plus fake HTTP/service responses at the external boundary, including lost responses and races; keep synthetic evidence local.

### 3. Inactive-until-cutover workflow and rule template

Files: `.github/workflows/benchmark.yml`, `tests/test_workflows.py`, `docs/main-ruleset.json`.

- [x] Add RED workflow assertions for mutually exclusive modes, exact measured-source checkout, restricted token scopes/revocation, main-only publisher environment, separate no-secret wait and unchanged Pages verification.
- [x] Add PR proposal/wait/merge jobs gated on `RESULT_PUBLICATION_MODE=pull-request-v1` and a deliberate rollout acknowledgement. Preserve the legacy path for the unset/default mode only; reject unknown modes before measuring.
- [x] SHA-pin create-github-app-token, restrict its repository and Contents/Pull requests permissions, and mint afresh in merge. Never retain a token across jobs.
- [x] Prepare (do not apply) a ruleset with PR requirement, strict `required` from app 15368, squash, conversation resolution, no bypass, no force push/deletion.

### 4. Runbook, review and PR verification

Files: `docs/PUBLISHING.md`, `docs/AUTOMATION.md`, this plan.

- [x] Document owner-only administration inventory, App/environment setup, public-rule checks versus private bypass visibility, staged cutover, exact rejected/successful live test evidence, race limitations and rollback.
- [x] Run normal/optimized focused tests, existing publication/Pages/workflow suites, pinned Ruff and generated-content checks.
- [x] Review the actual diff and verify unchanged measured inputs/results.
- [ ] Create one English PR referencing #52, not closing it.
- [ ] Verify latest-head full GitHub CI; do not call an inactive implementation a validated live publishing policy.

## Preparation evidence

- Candidate, pure identity/policy gates, transport and controller contracts were
  added before production changes and their expected failures were recorded.
- Final focused tests: 30 normal and 30 optimized successful; workflow tests:
  23 normal and 23 optimized successful. Exact Ruff 0.16.5 lint and formatting,
  registry generation, README generation and whitespace validation passed.
- Full local benchmark suite was executed in two shards: 94 tests (93 passed,
  one existing Go/Echo test unable to download pinned Go 1.27.1 without DNS) and
  109 passed. No test is disabled: the unfiltered full CI must pass remotely.
- Local Docker is unavailable. Real eight-container, browser, pinned Python 3.10,
  actionlint and complete smoke/Axum verification remain GitHub CI gates.
- Strict-base race and no-bypass enforcement are modeled, not live-verified;
  owner administration and actual authorized rollout tests remain outside this PR.
