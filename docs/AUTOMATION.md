# CI and official benchmark automation

## Pull request CI

`.github/workflows/ci.yml` runs on pull requests and non-result-only pushes to
`main`. The workflow keeps the stable name `CI`, uses only `contents: read`, and
uses SHA-pinned official actions. Every checkout disables `persist-credentials`.
Pull-request jobs do not receive publication or Pages permissions, and no PR
artifact is accepted as an official-result or Pages publication input.

Correctness CI is split into five logical jobs:

1. `plan` validates `benchmark/implementations.json` and emits the active
   implementation matrix in registry order. The workflow YAML does not maintain a
   second list of implementation IDs.
2. `shared` runs checks independent of one API implementation: Python 3.10
   benchmark/contract-unit compatibility, actionlint and workflow security tests,
   pinned Ruff format/lint, registry/projection drift, README generation checks,
   site/Pages tests, the shared database environment, and normal plus optimized
   benchmark unit tests.
3. `implementation` expands the registry-derived matrix. Each implementation runs
   on a separate `ubuntu-24.04` runner and executes its existing focused
   acceptance/failure-path target plus the same real-container contract suite
   focused on that implementation.
4. `smoke` runs the existing non-publishing smoke benchmark on one runner. It
   remains sequential across the active cohort and requires both tracked and
   untracked source state to remain clean.
5. `required` is the stable aggregate result. It uses `if: always()` and succeeds
   only when `plan`, `shared`, the complete `implementation` matrix, and `smoke`
   each report the literal result `success`. Failure, cancellation, or unexpected
   skip is rejected by `benchmark.ci` rather than being hidden by an aggregate
   job skip.

Each implementation matrix job owns a Compose project named from the run ID, run
attempt, and implementation ID, for example
`sab-ci-<run>-<attempt>-node-fastify`. Cleanup uses that exact project under
`if: always()`. The managed contract runner continues to create its own
`sab-contract-*` project and cleans it independently. Because matrix entries run
on separate hosts, their common `127.0.0.1:8080` binding does not conflict and no
job removes another job's container, network, or volume.

Local execution intentionally stays different: `make test-implementations` and
`make test` remain sequential because local API services share port 8080. Focused
commands remain available while developing:

```bash
make test-workflows
make test-go-gin
make test-contract CONTRACT_IMPL=go-gin
make benchmark-smoke
make test
```

Only the failure-only Ruff formatting patch may be uploaded by CI. Smoke output is
not uploaded, committed, or promoted to an official result.

## Official benchmark trust boundary

`.github/workflows/benchmark.yml` runs Saturdays at 14:27 UTC (23:27 JST) and
through `workflow_dispatch`, without caller-supplied inputs. Both jobs check the
repository, event, and default-branch ref. The Python entry point additionally
requires the exact `main` workflow ref and matching workflow/source SHA. A
dispatch from a feature branch is skipped; a renamed default branch requires an
explicit reviewed configuration update. No `pull_request_target` or
`workflow_run` chain is used.

PR CI parallelism does not change measurement execution. The `measure` job has no
matrix and calls `python -m benchmark.official` exactly once. All active cohort
members are measured sequentially on the same `ubuntu-24.04` runner under the
same fixed limits. Numbers from correctness matrix runners are never combined or
published as one benchmark run.

## Measurement and artifacts

The `measure` job has read-only repository access. It checks out the immutable
`github.sha`, verifies a clean source tree and calls `benchmark.official`.
This wrapper calls the existing `run_benchmark()` once; it does not reimplement
its measurement loop. All active stacks run sequentially on the same
GitHub-hosted runner with the unchanged fixed profile. The shared contract,
measured runs, state checks, memory sampling, and environment teardowns must all
succeed. There are no performance-based retries.

The wrapper adds runner name/type/OS/architecture, runner image OS/version, CPU
model, Docker client/Compose versions, and GitHub run identity to existing source,
Docker server, PostgreSQL, and pinned language/framework/driver provenance. Source
manifests provide declared exact stack versions; API image IDs and the actual
PostgreSQL server version identify the built environment.

Raw oha JSON, memory sample logs, build logs, and the full local-shaped
`candidate.json` are retained under `.cache/official/`. Only after a separate
raw-data audit does the workflow create `selected.json`, with `mode: official`
and `official: true`. The immutable
`official-benchmark-<run_id>-<run_attempt>` artifact is retained for 90 days.
Failed attempts retain available diagnostics but have no publishable selected
result. Artifact existence alone is not evidence of success.

## Atomic publication

Only `publish`, dependent on successful measurement and artifact upload, receives
`contents: write`. It starts on a fresh runner, checks out the same source SHA,
and downloads only the artifact named for this workflow run and attempt. There is
no caller-supplied artifact ID, repository, branch, or cross-run credential. The
GitHub token is exposed only to the final publishing command. No API, Docker
build, package install, or benchmark runs in this write-enabled job.

The publisher revalidates complete schema and provenance, normalized records
against raw oha and API-only memory samples, selected whole runs, and the exact
source commit/tree. Symlinked, missing, oversized, and escaping artifact paths are
rejected. It prepares these four publication paths from the same report:

- `results/latest.json`;
- `results/history/<UTC-completion>-<run_id>-<attempt>.json`;
- the marker-delimited result section in `README.md`;
- the corresponding section in `README.ja.md`.

History filenames distinguish same-day runs and attempts and are never
overwritten. Both README tables show throughput, mean response time, and observed
peak memory for each selected endpoint run. Missing official data is described
honestly instead of displayed as zero.

All bytes are prepared before publication. An isolated temporary Git index builds
one commit containing exactly those publication changes; the normal working tree
and index are not modified. A normal fast-forward push updates remote `main`.
There is no force push, rebase, merge, or retry loop. Stale-source and concurrent
update failures preserve the previous verified remote state.

Git credentials are supplied through process-environment Git configuration, not
persisted in `.git/config`, embedded in remote URLs, or printed in diagnostics.
Repository rules may reject the automated push; the workflow fails safely rather
than bypassing those rules.

## Loop prevention and interpretation

Official measurement has only schedule/manual triggers, never `push`. Result
commits use the repository `GITHUB_TOKEN`, include `[skip ci]`, and touch only
paths excluded from the CI push trigger. These independent guards prevent result
publication from repeatedly triggering measurement/CI. Do not replace this token
with a PAT to work around publication failures.

A successful manual trusted-main run validates the same path used by the weekly
schedule; the configured cron is not evidence that a future scheduled run has
already executed. GitHub may delay scheduled jobs, and shared hosted hardware can
vary. Always read the run date, conditions, and versions together. Local, fixture,
and PR smoke reports are not official measurements.

## GitHub Pages and v0.1.0 release

`pages.yml` runs only after a completed `CI` or `Official benchmark` workflow, or
through an explicit manual dispatch. Keeping the workflow name `CI` preserves
that trigger after CI partitioning. `benchmark.pages` independently verifies the
repository, default-branch ref, workflow identity, source SHA, upstream event, and
upstream conclusion before the static artifact is built. A pull-request CI run,
even with a successful `required` job, is not a trusted Pages input.

The Pages build job has read-only repository access. Only the dependent deploy job
receives `pages: write` and OIDC permissions. The one-time `v0.1.0` release job
runs after a successful Pages deployment and only when the upstream workflow is a
successful `push` CI run for the repository's default branch at the same SHA. It
receives `contents: write` only for release creation. Manual Pages runs and
official benchmark result refreshes cannot create the release. If `v0.1.0`
already exists, the job leaves it unchanged.

## Registry compatibility and aggregate policy

The implementation list comes from `benchmark/implementations.json`, not a
CI-specific list. The `plan` job derives the matrix from that registry, and
workflow tests use the same registry plus an isolated eight-member synthetic
fixture to prove future additions expand the matrix without editing the workflow
ID list. The production registry still enables only implemented stacks.

The `required` job is the stable aggregate intended for repository policy. This
issue does not modify branch protection or repository rules. The repository's
policy can therefore adopt that check independently without tying protection to
changing matrix job display names.

New reports continue to use explicit schema-v2 definition/cohort identity.
Historical schema-v1 four-stack reports remain accepted without rewriting stored
results. See [implementation and cohort compatibility](IMPLEMENTATIONS.md).

## Runtime evidence and timeouts

Timeouts are based on measured history and observed split-CI behavior rather than
being raised speculatively:

- historical monolithic main CI run `34205435379` completed in about 10 minutes;
- official run `33979190013` completed in about 25 minutes including publication;
- split PR CI run `34247372701` observed `plan` at about 6 seconds,
  `implementation (node-fastify)` at about 1 minute 18 seconds,
  `implementation (go-gin)` at about 2 minutes 43 seconds, and the sequential
  non-publishing `smoke` job at about 5 minutes 22 seconds.

Run `34247372701` intentionally did not count as a final Green run because a
pinned-Ruff formatting gate failed in `shared`; importantly, all four real
implementation matrix jobs and smoke succeeded, and `required` correctly failed
because `shared` failed. Final exact-head runtimes are recorded in the pull
request verification before merge.

Configured timeout ceilings are 10 minutes for `plan` and `required`, 25 minutes
for `shared`, and 30 minutes for each implementation and smoke job. These provide
large margins over observed responsibility-specific runtimes while retaining
finite failure/cleanup bounds. The official measurement budget remains 60 minutes.
No eight-framework official runtime is claimed or inferred from the synthetic
registry fixture.

## Developer checks

```bash
make test-registry
make test-workflows
make test-benchmark
make test-go-gin
make test-contract CONTRACT_IMPL=go-gin
make benchmark-smoke
make generate-readme
python -m benchmark.generate_readme --check
make test                 # full local gate, sequentially
```

Install the pinned workflow tooling before `make test-workflows`:

```bash
python -m pip install --only-binary=:all: PyYAML==6.0.3
go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
```

The focused publication tests use synthetic reports and temporary local bare Git
repositories. They never publish to GitHub. Official publication remains reserved
for complete trusted-main Actions runs.