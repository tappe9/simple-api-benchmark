# CI and official benchmark automation

## Pull request CI

`.github/workflows/ci.yml` runs on pull requests and non-result-only pushes to
`main`. The workflow keeps the stable name `CI`, uses only `contents: read`, and
uses SHA-pinned official actions. Every checkout disables `persist-credentials`.
Pull-request jobs do not receive publication or Pages permissions, and no PR
artifact is accepted as an official-result or Pages publication input.

Correctness CI is split into five logical jobs:

1. `plan` validates `benchmark/implementations.json` and emits the full registered
   implementation/toolchain matrix in registry order. The workflow YAML does not
   maintain a second list of implementation IDs.
2. `shared` runs checks independent of one API implementation: Python 3.10
   benchmark/contract-unit compatibility, actionlint and workflow security tests,
   pinned Ruff format/lint, registry/projection drift, README generation checks,
   site/Pages tests, the shared database environment, and normal plus optimized
   benchmark unit tests.
3. `implementation` expands the registry-derived matrix. Each implementation runs
   on a separate `ubuntu-24.04` runner and executes its existing focused
   acceptance/failure-path target plus the same real-container contract suite
   focused on that implementation. The `rust-axum` entry then runs
   `make axum-diagnostic` and verifies that tracked and untracked source files
   remain unchanged. This is a normal required step, not `continue-on-error`.
4. `smoke` runs the existing non-publishing smoke benchmark on one runner. It
   remains sequential across the active cohort, uses the same `external-readiness`
   measurement startup policy as the full benchmark, and requires both tracked and
   untracked source state to remain clean.
5. `required` is the stable aggregate result. It uses `if: always()` and succeeds
   only when `plan`, `shared`, the complete `implementation` matrix, and `smoke`
   each report the literal result `success`. Failure, cancellation, or unexpected
   skip is rejected by `benchmark.ci` rather than being hidden by an aggregate
   job skip.

### Implementation host toolchains

The matrix's `toolchain` value is derived from the registry's `language`, not an
implementation-ID prefix or a second framework list. Unsupported languages and
invalid registry data fail planning before any partial matrix is emitted. All
registered implementations are tested, even when outside the active measurement
cohort. The `implementation (<ID>)` job names and `required` aggregate stay stable.

Every implementation runner explicitly installs the pinned Python harness. Only
Go jobs additionally run `setup-go`, only Node.js jobs run `setup-node`, and only
Rust jobs install Rust with rustfmt/Clippy. Python implementation jobs need no
additional language setup. The existing versions, action SHAs, acceptance/failure
targets, shared contracts, cleanup and Axum diagnostic are unchanged. The shared
job still explicitly installs Go for actionlint/Go-related tests and Node.js for
site tests; its Python 3.10 compatibility gate is retained.

CI invokes the host acceptance, contract and Axum diagnostic commands through
`python -m benchmark.ci run-isolated --implementation <ID> -- <command>`. This
prepends temporary failing executables for unrelated host Go/Node/Rust tools to
the child PATH, so a preinstalled runner tool cannot silently satisfy an
undeclared dependency. Actual tool use fails the gate even if its immediate
caller ignores the exit status. The exact `rustc --version` probe is the one
exception: it returns 127 without executing Rust or reporting a version, allowing
pip's optional User-Agent metadata lookup to treat the compiler as absent.
Compilation, additional arguments, and other tool invocations remain fatal.
Common Python, Make, Git, Docker and shell tools remain available. The parent environment is not changed; guards are removed when
the command returns, including ordinary command failures. These are dependency
checks, not a security sandbox: absolute executable paths, deliberate PATH resets
and container-internal toolchains are not intercepted. Actions' own runtimes are
unaffected. Do not add host-tool bypasses to acceptance commands.

When assessing setup changes, compare the per-step setup timestamps separately
from per-implementation duration and total workflow elapsed time, recording run
ID, attempt, head SHA and runner-image identity. Matrix durations overlap; their
sum is not wall-clock CI latency. Hosted-runner/network/cache variation can
outweigh setup savings. Do not change measured binaries, caches, benchmark
conditions or gates just to obtain a faster CI result.

Each implementation matrix job owns a Compose project named from the run ID, run
attempt, and implementation ID, for example
`sab-ci-<run>-<attempt>-node-fastify`. Cleanup uses that exact project under
`if: always()`. The managed contract runner continues to create its own
`sab-contract-*` project and cleans it independently. Because matrix entries run
on separate hosts, their common `127.0.0.1:8080` binding does not conflict and no
job removes another job's container, network, or volume.

Local execution intentionally stays different: `make test-implementations` and
`make test` remain sequential because local API services share port 8080. Focused
implementation and standalone contract checks keep the normal Compose
healthchecks; the benchmark-specific API health override is not applied globally.
Focused commands remain available while developing:

```bash
make test-workflows
make test-go-gin
make test-contract CONTRACT_IMPL=go-gin
make benchmark-smoke
make test
```

CI may upload the failure-only Ruff formatting patch and the Axum-only diagnostic
cache. The Axum artifact is named `axum-diagnostic-<run>-<attempt>`, retained for
seven days, and includes hidden cache files on success or failure when available.
It contains diagnostic JSON, source/version metadata, build logs, raw load data,
and memory samples, never an official publication. Axum's diagnostic owns and
cleans a separate random `sab-benchmark-*` project on its runner. See
[the Axum guide](AXUM.md) for output and failure guarantees.

Smoke output is not uploaded, committed, or promoted to an official result.
The temporary `axum-development.yml` workflow is removed; the repository retains
`ci.yml`, `benchmark.yml`, `pages.yml`, and the local reusable `pages-deploy.yml`. Neither diagnostic evidence nor
its upload grants publication permissions or changes official cohort membership.

## Official benchmark trust boundary

`.github/workflows/benchmark.yml` runs Saturdays at 14:27 UTC (23:27 JST) and
through `workflow_dispatch`, without caller-supplied inputs. The measurement, publication and dependent Pages call check the
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
GitHub-hosted runner with the unchanged load/resource profile. The shared
contract, measured runs, state checks, memory sampling, and environment teardowns
must all succeed. There are no performance-based retries.

The official wrapper explicitly selects the approved `external-readiness` API
health policy. For each implementation it keeps the PostgreSQL Docker healthcheck,
waits for PostgreSQL to become healthy, disables only the benchmark-owned API
container's recurring healthcheck, proves through Docker inspect that the API
healthcheck is disabled, then performs bounded exact `/health` readiness from the
host. Readiness polling finishes before shared-contract execution, warm-up, and
measured load. Wrong health responses, deadline expiry, startup failure, resource
or process drift, restart/OOM, container identity change, HTTP errors/timeouts,
memory failure, and cleanup failure remain fatal.

The generic `DockerEnvironment` default is deliberately not changed globally.
Focused implementation acceptance and standalone contract workflows continue to
use their ordinary Compose health behavior. This isolates Issue #23 to benchmark
measurement rather than turning it into an API implementation change.

The wrapper adds runner name/type/OS/architecture, runner image OS/version, CPU
model, Docker client/Compose versions, GitHub run identity, and the explicit API
health policy to existing source, Docker server, PostgreSQL, and pinned
language/framework/driver provenance. Source manifests provide declared exact
stack versions; API image IDs and the actual PostgreSQL server version identify
the built environment.

Raw oha JSON, memory sample logs, build logs, and the full local-shaped
`candidate.json` are retained under `.cache/official/`. Only after a separate
raw-data audit does the workflow create `selected.json`, with `mode: official`
and `official: true`. The immutable
`official-benchmark-<run_id>-<run_attempt>` artifact is retained for 90 days.
Failed attempts retain available diagnostics but have no publishable selected
result. Artifact existence alone is not evidence of success. The Issue #23 A/B
investigation artifact is diagnostic (`official: false`, `publishable: false`) and
is never an accepted publication input.

## Atomic publication

Only `publish`, dependent on successful measurement and artifact upload, receives
`contents: write`. It starts on a fresh runner, checks out the same source SHA,
and downloads only the artifact named for this workflow run and attempt. There is
no caller-supplied artifact ID, repository, branch, or cross-run credential. The
GitHub token is exposed only to the final publishing command. No API, Docker
build, package install, or benchmark runs in this write-enabled job.

The publisher revalidates complete schema and provenance, including the API health
policy, normalized records against raw oha and API-only memory samples, selected
whole runs, and the exact source commit/tree. Symlinked, missing, oversized, and
escaping artifact paths are rejected. It prepares these seven publication paths
from the same report:

- `results/latest.json`;
- `results/history/<UTC-completion>-<run_id>-<attempt>.json`;
- the marker-delimited result section in `README.md`;
- the corresponding section in `README.ja.md`;
- all three `results/charts/*-throughput.svg` files (JSON, PostgreSQL and CPU),
  using the exact shared publication manifest rather than a directory wildcard.

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

Issue #23 changes the measurement policy only. It does not itself rewrite existing
`results/latest.json`, history files, generated README result blocks, or Pages
output. A future official run under the new policy and any resulting publication
remain separate actions.

## Loop prevention and interpretation

Official measurement has only schedule/manual triggers, never `push`. Result
commits use the repository `GITHUB_TOKEN`, include `[skip ci]`, and touch only
paths excluded from the CI push trigger. These independent guards prevent result
publication from repeatedly triggering measurement/CI. Do not replace this token
with a PAT to work around publication failures.

A successful manual trusted-main run validates the same path used by the weekly
schedule; the configured cron is not evidence that a future scheduled run has
already executed. GitHub may delay scheduled jobs, and shared hosted hardware can
vary. Always read the run date, conditions, versions, and API health policy
together. Local, fixture, PR smoke, and Issue #23 investigation reports are not
official measurements.

The controlled Issue #23 run observed selected throughput differences of roughly
+2.3% to +23.1% after recurring API probes were removed from the measured window.
Those numbers describe that same-runner investigation only. They are not universal
speedups, do not mean the API implementations were optimized, and do not imply
that every memory metric improves.

<a id="github-pages-and-v010-release"></a>

## GitHub Pages

The automatic official route is now a job dependency, not another completion event:

```text
benchmark.yml: measure -> publish -> pages-deploy.yml (build -> deploy)
pages.yml:     successful main CI / manual recovery -> pages-deploy.yml
```

`pages.yml` subscribes only to successful, current-main push `CI` runs and retains
explicit main-only `workflow_dispatch` recovery. `Official benchmark` is no longer
in its `workflow_run` subscription: there is one automatic official-publication
route, regardless of whether the producer was scheduled or dispatched by a
maintainer or bot. An unsuccessful, cancelled or skipped `publish` cannot invoke
that route. PR and smoke jobs remain read-only and cannot call deployment.

After the raw audit and successful fast-forward push, `benchmark.publish` emits
`publication_sha`, `source_sha`, `producer_run_id` and `producer_run_attempt` through
`GITHUB_OUTPUT`. Failed publication does not emit handoff outputs. A later output
write failure cannot undo a completed publication; recover Pages rather than
rerunning measurement or pushing the old result again.

Both callers use the local reusable workflow from their own immutable revision.
GitHub's reusable-workflow context belongs to the caller: for official runs,
`GITHUB_SHA` is the **measured source**, not its child publication commit. The
controller checkout always uses that caller SHA. `benchmark.pages_handoff`
separately validates the target SHA, caller workflow/ref/event/repository and
producer identity, fetches only current main, then requires the official target
to have the measured source as its sole parent. It revalidates the report/context,
source tree, exact seven-path manifest, byte-identical history, and deterministic
README/SVG contents. No GitHub environment variable is spoofed, and no code is
executed from a caller-supplied feature-branch revision. The historical
`benchmark.pages.validate_event` validator remains available for existing audit
callers; the reusable entry point allows only CI through that event route.

Build uses a detached, verified-target worktree under `.cache/pages-source`.
The artifact name binds the target, run ID and **build attempt**, and the deploy
job consumes the build job's saved output. Deployment-only retries can have a
new caller attempt while retaining the original producer attempt and original
artifact name. They cannot invent a new measurement identity. An expired/missing
artifact requires rebuilding the Pages jobs or explicit Pages recovery, never a
new benchmark solely to repair presentation.

The caller grants a ceiling of `contents: read`, `pages: write`, and
`id-token: write` only to the reusable call. Its build job reduces this to
`contents: read`; its deploy job retains read access for the trusted-controller
checkout and freshness check plus Pages/OIDC permissions. The publisher keeps
only its existing `contents: write`; neither measurement nor PR privileges change.
No `actions: write`, PAT, App secret or new credential is introduced.

Only the dependent deploy job acquires the shared `pages` concurrency group, with
`cancel-in-progress: false`. Ineligible runs cannot cancel a valid deployment.
After environment approval and inside that serialized job, the controller
re-fetches main and repeats authorization immediately before `deploy-pages`.
Thus an older queued target cannot overwrite an already newer deployment. This
check is not an atomic lock on repository writes, and concurrency is not an
exactly-once delivery guarantee. A main update after the last check is handled by
the newer eligible deployment; repeated explicit deployment of identical content
is safe. The artifact content SHA is the validated target; Actions/Pages run
metadata can still identify the caller's measured-source SHA on official calls.
Record these identities separately.

Pages deployment never creates, edits or looks up product releases. Both the
ordinary entry point and reusable deployment have only `contents: read` plus the
existing job-scoped Pages/OIDC permissions; neither has repository-write access.
The one-time release bootstrap was removed under Issue #53. The existing `v0.1.0`
tag and release remain unchanged. New product releases use the explicit maintainer
[release procedure](RELEASING.md), independently of Pages and official result
publication. A failed release API lookup must never trigger release recreation.

### Recovery and validation status (#59)

During Issue #50's bot-dispatched run `34925168324`, measurement and publication
succeeded but no automatic Pages completion run was observed for publication
`25fa3f086919f7124afe3c8d22f0791bd83768ef`. Existing manual Pages run `34928391910`
successfully deployed that exact publication. Local event replay passed the old
validator, but does not prove that GitHub delivered an event. Token-origin and
chaining rules remain hypotheses; the internal cause was not established. Older
scheduled runs used different revisions or failed before publication and are not
controlled reproductions. The direct dependency removes that extra event from
the new official path; it does not claim to explain GitHub's internal decision.

To recover presentation without altering measurements, first verify the current
main SHA, successful publication run, published report and intended source. Then
explicitly dispatch the existing Pages workflow on main and check the resulting
deployment SHA and live JSON. The main-only validator refuses stale runs.

```bash
# Read current identities before dispatch; do not substitute an old publisher rerun.
gh api repos/tappe9/simple-api-benchmark/git/ref/heads/main --jq '.object.sha'
gh workflow run pages.yml --repo tappe9/simple-api-benchmark --ref main
gh run list --repo tappe9/simple-api-benchmark --workflow pages.yml --limit 5
```

Do not run another official benchmark merely to validate this refactoring.
Regression tests cover successful/rejected calls, real isolated Git publication,
producer/build retry identities, and stale-target rejection. A normal post-merge
Pages deployment exercises the shared workflow against existing verified data.
The complete new **official producer -> dependent deployment** path is only live
verified when an authorized or normally scheduled official run exercises it;
track that evidence under Issue #59 rather than presenting fixture tests as a
real measurement or a manual recovery as an automatic handoff.

Platform references: [reusable workflow context and permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations),
[rerun identity](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs),
[trigger recursion](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
and [skip instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).

## Registry and methodology compatibility

The implementation list comes from `benchmark/implementations.json`, not a
CI-specific list. The `plan` job derives the matrix from that registry. Planning
regressions verify supported-language registrations under unfamiliar IDs, registry
order, inactive cohort members, and rejection of undeclared synthetic languages.
Future supported implementations expand the matrix without editing the workflow
ID list. The production registry still enables only implemented stacks.

The `required` job is the stable aggregate intended for repository policy. This
issue does not modify branch protection or repository rules. The repository's
policy can therefore adopt that check independently without tying protection to
changing matrix job display names.

Schema-v2 reports have explicit definition/cohort identity and now require
`metadata.api_health_policy`. Historical schema-v1 four-stack reports remain
accepted without rewriting stored results; a missing schema-v1 policy resolves
specifically to the legacy `container-healthcheck` method. Schema-v1 cannot claim
`external-readiness`.

Comparison compatibility includes definition/cohort, ordered implementations,
fixed benchmark conditions, and API health policy. Historical
`container-healthcheck` results and new `external-readiness` results are therefore
separate methodology groups. Historical results are not invalidated; this rule
prevents them from being mistaken for new-policy measurements. See
[BENCHMARK.md](BENCHMARK.md) and
[the Issue #23 investigation record](investigations/2026-09-09-healthcheck-interference.md).

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
Actual eight-stack rollout timings are recorded in Issue #50; synthetic fixtures
do not establish runtime or performance.

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


## Staged protected publication (#52)

The result-only PR controller is preparation code and is not activated by merging
its implementation. The unset/`legacy` publication mode keeps the existing direct
publisher during the staged rollout. Explicit `pull-request-v1` mode instead uses
an audited proposal, a read-only full-CI wait and a new scoped App token for an
exact-head squash merge. Its successful merge feeds the existing Pages call; it
never falls back to direct push when a PR, CI, policy or API operation fails.

See [protected result-PR publishing](PUBLISHING.md) for approved boundaries,
restricted App/Environment setup, the disabled ruleset template, required live
stale-base race validation, paused cutover and rollback. Main protection, App
credentials and live publication are separate owner-approved operations, not
side effects of code preparation. Ordinary PR CI and Pages remain read-only with
respect to repository contents. Issue #52 stays open until effective-policy and
real-publication evidence is recorded; #59 still needs its real producer/deploy
proof, not just synthetic tests.
