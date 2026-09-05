# CI and official benchmark automation

## Two separate trust boundaries

`ci.yml` runs on pull requests and non-result-only pushes to `main`. It uses
`contents: read`, no publishing/deployment secret, and SHA-pinned official actions.
Every checkout disables `persist-credentials`. All four application quality gates,
the shared contract, focused benchmark/publication tests, workflow validation and
a shortened `make benchmark-smoke` run are required. The smoke run never changes
`results/latest.json`, history, or README. Only a formatting patch may be uploaded
on a failed CI run; no PR benchmark numbers are uploaded or committed.

`benchmark.yml` runs Saturdays at 14:27 UTC (23:27 JST) and through
`workflow_dispatch`, without caller-supplied inputs. Both jobs check the repository,
event and default-branch ref. The Python entry point additionally requires the
exact `main` workflow ref and matching workflow/source SHA. A dispatch from a
feature branch is skipped; a renamed default branch requires an explicit reviewed
configuration update. No `pull_request_target` or `workflow_run` chain is used.

## Measurement and artifacts

The `measure` job has read-only repository access. It checks out the immutable
`github.sha`, verifies a clean source tree and calls `benchmark.official`.
This wrapper calls the existing `run_benchmark()` once; it does not reimplement
its measurement loop. All four stacks run sequentially on the same
`ubuntu-24.04` GitHub-hosted runner, with the unchanged full v0.1 profile.
The shared contract and all 36 measured runs, state checks, memory sampling and
four environment teardowns must succeed. There are no performance-based retries.

The wrapper adds runner name/type/OS/architecture, runner image OS/version, CPU
model, Docker client/Compose versions and GitHub run identity to existing source,
Docker server, PostgreSQL and pinned language/framework/driver provenance. Source
manifests provide declared exact stack versions; the API image IDs and actual
PostgreSQL server version identify the built environment. These are not claims
that a compiled Rust runtime exposes a runtime package inventory.

It retains raw oha JSON, memory sample logs, build logs and the full local-shaped
`candidate.json` under `.cache/official/`. Only after a separate raw-data audit does
it create `selected.json`, with `mode: official` and `official: true`.
This JSON still retains all three normalized runs and their whole-run selection.
The immutable artifact `official-benchmark-<run_id>-<run_attempt>` is uploaded
with 90-day retention. Failed attempts retain available diagnostic files but
have no publishable selected result. Artifact existence is not evidence of success.

## Atomic publication

Only `publish`, dependent on successful measurement and artifact upload, receives
`contents: write`. It starts on a fresh runner, checks out the same source SHA,
and downloads only the artifact named for this workflow run and attempt. There
is no caller-supplied artifact ID, repository, branch or cross-run credential.
The GitHub token is exposed only to the final publishing command. No API,
Docker build, package install or benchmark runs in this write-enabled job.

The publisher revalidates the complete schema and provenance, all 36 normalized
records against raw oha and API-only memory samples, the selected whole runs,
and the exact source commit/tree. Symlinked, missing, oversized and escaping
artifact paths are rejected. It prepares these four files from the same report:

- `results/latest.json`;
- `results/history/<UTC-completion>-<run_id>-<attempt>.json`;
- the marker-delimited result section in `README.md`;
- the corresponding section in `README.ja.md`.

History filenames distinguish same-day runs and attempts and are never overwritten.
Both README tables show throughput, mean response time and observed peak memory
for each selected endpoint run. There is no composite score or universal winner.
Missing official data is described honestly instead of displayed as zero.

All bytes are prepared before publication. An isolated temporary Git index builds
one commit containing exactly those four changed paths; the working tree and
normal index are not modified. A normal fast-forward push updates the remote
`main` ref atomically. There is no force push, rebase, merge or retry loop. A stale
source detected before publication, or a concurrent update rejected by the push,
leaves the previous verified remote state intact. The artifact remains available
for diagnosis; rerun only for a justified fresh measurement, not a preferred score.
Encoding, parsing, README marker, Git object creation or transport failure before
the ref update likewise leaves all published files unchanged. As with any network
write, a lost acknowledgement can make the client uncertain after the server has
accepted the update; inspect the remote SHA before recovery.

Git credentials are supplied through process-environment Git configuration, not
persisted in `.git/config`, embedded in remote URLs or printed in diagnostics.
Repository rules may disallow this automated push; the workflow fails safely
rather than bypassing those rules. Permission changes require owner review.

## Loop prevention and interpretation

Official measurement has only schedule/manual triggers, never `push`. Result
commits use the repository `GITHUB_TOKEN`, include `[skip ci]`, and touch only
paths excluded from the CI push trigger. These independent guards prevent
results from repeatedly triggering measurement/CI. Do not replace this token
with a PAT to work around publication failures.

A successful manual trusted-main run validates the same path used by the weekly
schedule; the configured cron is not evidence that a future scheduled run has
already executed. GitHub may delay scheduled jobs, and shared hosted hardware
can vary. Always read the run date, conditions and versions together. Local,
fixture and PR smoke reports are not official measurements.

## Developer checks

```bash
make test-benchmark
python -m pip install --only-binary=:all: PyYAML==6.0.3
go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
make test-workflows
make generate-readme       # valid official latest.json, or honest empty state
python -m benchmark.generate_readme --check
make test                 # all acceptance gates and smoke, sequentially
```

The focused publication tests use synthetic reports and temporary local bare Git
repositories. They never publish to GitHub. They test complete transactions,
malformed data, source races, rejected pushes, collision protection and unchanged
working-tree/index state. The official workflow is first executable as trusted
code after merge; PR CI must succeed before that merge.

GitHub Pages and release automation belong to Issue #10, not these workflows.
