# Issue #22: Split Pull Request CI Design

## Goal

Reduce pull-request CI critical-path time as the implementation registry grows, while preserving every existing correctness gate and keeping official benchmark measurements sequential on one runner.

## Scope

This change restructures `.github/workflows/ci.yml` and the workflow contract tests around the registry introduced by Issue #21. It may add small CI-support code or Make targets when needed for deterministic matrix generation or aggregate-result validation. It does not change API implementations, benchmark conditions, metrics, official cohort membership, publication inputs, branch protection, release/tag state, or Pages presentation.

## CI topology

Use five logical stages inside the existing `CI` workflow:

1. `plan` — read `benchmark/implementations.json`, validate the registry, and emit the active implementation IDs as compact JSON for the matrix. The registry remains the only implementation list.
2. `shared` — run checks that are independent of one measured implementation: Python 3.10 compatibility, pinned formatting/lint, actionlint, workflow tests, registry/projection drift, README generation checks, site/Pages tests, database environment checks, benchmark unit tests, optimized-mode benchmark tests, and other shared source/security checks.
3. `implementation` — a matrix driven only by `needs.plan.outputs.matrix`. Each entry runs on its own `ubuntu-24.04` runner and executes that implementation's acceptance/failure-path checks plus the shared contract runner focused on that implementation.
4. `smoke` — run the existing non-publishing smoke benchmark separately. It remains sequential across the active cohort and must leave the working tree clean.
5. `required` — a stable aggregate check with `if: always()` that evaluates `plan`, `shared`, `implementation`, and `smoke`. It succeeds only when every required predecessor result is exactly `success`; failure, cancellation, or unexpected skip is a failure.

The workflow-level permissions remain `contents: read`. Every checkout keeps `persist-credentials: false`, and all third-party actions remain commit-SHA pinned.

## Matrix and Compose isolation

The implementation matrix is derived from `benchmark/implementations.json`; no second YAML list of implementation IDs is introduced.

Each implementation matrix job owns an explicit Compose project name that includes the workflow run, attempt, and implementation ID, for example:

` sab-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${IMPLEMENTATION_ID} `

The value is passed through `env`, not interpolated into shell from untrusted expression data. Cleanup uses the exact owned project name with `docker compose -p ... down --remove-orphans --volumes` and runs under `if: always()`. Matrix jobs never tear down another job's project.

Because each implementation has a separate host, their use of host port 8080 does not conflict. Local `make test` and `make test-implementations` remain sequential because local execution still shares one host.

## Coverage mapping

The split must preserve current coverage:

- Python 3.10 benchmark and contract-unit compatibility stays in `shared`.
- Registry/projection, README, workflow-security, site, Pages, DB, lint/format, and optimized-mode checks stay in `shared`.
- Every registry implementation runs its current acceptance test, configured failure-path test when present, and focused real-container contract suite in `implementation`.
- The existing non-publishing smoke benchmark stays in `smoke`, including dirty/untracked-tree guards.
- Official benchmark workflow remains a single `measure` job with one `python -m benchmark.official` execution and no matrix.

Workflow tests must verify this mapping directly from the registry so future framework additions cannot silently lose CI coverage.

## Aggregate result

`required` is the stable result intended for repository policy. It has no conditional that can skip the job when an upstream job fails. Instead, `if: always()` makes it run after all declared needs finish, and a small deterministic shell/Python check rejects any result other than `success`.

The aggregate decision logic is unit-tested against at least: all success, one failure, cancellation, and skipped predecessor results. The workflow contract also verifies that all expected predecessor jobs are included in `needs`.

## Pages trust boundary

The workflow name remains `CI`, so the existing Pages `workflow_run` authorization continues to identify the same trusted workflow. Pages must still require a successful `push` run on the repository's current main SHA; PR runs remain ineligible publication inputs. Tests continue to enforce this boundary after the CI job restructuring.

## Official benchmark boundary

`.github/workflows/benchmark.yml` is not parallelized. The active cohort is measured sequentially by `benchmark.official` on one runner under identical limits, and matrix correctness jobs are never treated as benchmark measurements or combined into an official report.

No additional official benchmark is dispatched for this issue.

## Timeout policy and runtime evidence

Use measured history rather than increasing timeouts speculatively:

- Existing monolithic main CI run `34205435379` completed successfully in about 10 minutes.
- Existing official run `33979190013` completed successfully in about 25 minutes for the full four-member cohort including publication.

Initial split-job timeouts should retain comfortable margins around the actual responsibility of each job rather than inherit a blanket 60-minute budget unnecessarily. Final values are adjusted only after the PR's real matrix/shared/smoke runtimes are observed. The PR records observed job runtimes separately from historical and estimated values.

## Documentation

Document focused CI commands for contributors while preserving `make test` as the full sequential local gate. At minimum, document how to run shared workflow tests, one implementation's acceptance/contract checks, and the non-publishing smoke check.

## TDD and verification

Start with workflow tests that fail on the current single `quality` job and require:

- registry-derived matrix generation,
- separate shared/implementation/smoke jobs,
- unique Compose project ownership,
- fail-closed stable aggregate behavior,
- preserved coverage mapping,
- unchanged sequential official measurement,
- unchanged Pages trusted-success authorization.

Then implement until the focused tests pass, refactor without weakening assertions, and run the repository's current quality gates. The final PR head must pass real Docker DB/acceptance/contract/smoke jobs before merge. After squash merge, verify exact-main CI, Pages build/deploy, and unchanged official result/history bytes.

## Non-goals

Do not implement Issues #23-#32, add frameworks, change performance methodology, change concurrency/measurement duration/workers/pools, rewrite published results, modify branch protection, create releases/tags, or introduce a reusable-workflow/plugin framework.