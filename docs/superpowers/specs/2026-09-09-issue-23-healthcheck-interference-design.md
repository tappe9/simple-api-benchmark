# Issue #23: Health-Check Interference Investigation Design

## Goal

Determine, with controlled same-runner evidence, whether recurring API-container health probes materially affect throughput, mean response time, or observed API-container peak memory. Do not change official benchmark methodology, publication, or historical interpretation until the investigation produces evidence and the owner explicitly approves any policy change.

## Current behavior

The shared Compose file configures every API service with an in-container health command that repeats every two seconds. The benchmark environment starts each service with `docker compose up --detach --wait`, requires Docker health to become `healthy`, accepts exactly one server process plus independently identifiable health-probe processes, and samples container-wide Docker memory during every warm-up and measured run.

This means health probes execute inside the measured API container while load generation and memory observation are active. PostgreSQL health remains separate and is not part of this investigation.

## Decision boundary

This PR is an investigation first, not a methodology change.

The branch may add reusable support for selecting and observing an API health policy, an isolated non-publishing A/B investigation runner, deterministic analysis, tests, and documentation of the observed outcome. The current benchmark path must retain its existing behavior by default.

If the investigation does not establish a consistent effect relative to run-to-run variation, the final merged behavior keeps recurring API health checks enabled during measurements and documents that their resource use is included.

If the investigation shows a consistent, practically relevant effect, stop before changing official measurement behavior. Record the evidence and propose the controlled policy to the owner for explicit methodology approval. Historical runs remain unchanged and must never be silently reinterpreted.

## Compared policies

### Baseline: `container-healthcheck`

Use the repository's current Compose behavior without an override:

- API health command enabled at the existing two-second interval;
- PostgreSQL health enabled;
- `docker compose up --detach --wait` readiness;
- one server process plus only the configured independent health-probe process is allowed;
- existing contract, restart/OOM/container-identity, deadline, memory-sampling, and cleanup behavior unchanged.

### Controlled alternative: `external-readiness`

Disable only the selected API service's Compose healthcheck by supplying a generated Compose override with `healthcheck.disable: true`. The override is generated from the validated implementation registry; it must not introduce another hand-maintained implementation list.

Preserve all other Compose settings, including PostgreSQL health and `depends_on` behavior. Start the selected API in the same owned Compose project, then perform bounded host-side readiness polling of `GET /health` on `127.0.0.1:8080`.

External readiness requirements:

- absolute deadline no longer than the existing 60-second readiness budget;
- HTTP 200 plus the exact shared health response contract;
- container state/identity checked while polling and once readiness succeeds;
- startup failure, exit, restart, OOM, wrong container ownership, and timeout remain fatal;
- after readiness, only the single server process is allowed in the API container because no independent health command should exist;
- PostgreSQL remains healthy through its existing Docker healthcheck;
- normal shared contract runs before any measurement;
- cleanup remains scoped to the environment's unique Compose project.

The external readiness requests end before warm-up. No host-side readiness polling is allowed to continue during measured runs.

## Investigation profile

Use the existing full benchmark profile without changing workload inputs or resource limits:

- active registry cohort only;
- same Git commit and same GitHub-hosted runner for both policies;
- 1 API CPU and 512 MiB API memory limit;
- one server process/worker;
- pool maximum 10;
- HTTP/1.1;
- 50 concurrent connections;
- 5-second warm-up;
- 30-second measured duration;
- exactly three measured runs per endpoint;
- `/json`, `/db/42`, and `/cpu`;
- the existing pinned `oha` version and parser;
- the same contract checks and result validity rules.

Run both policies sequentially in one investigation job. To reduce order bias without creating an elaborate experiment framework, use a fixed documented alternating order by implementation: the first registry member runs baseline then controlled, the second controlled then baseline, and so on. The analysis records the actual execution order. Do not combine measurements from different GitHub runners.

The investigation output is diagnostic only. It is never eligible for official publication and must not write `results/latest.json`, `results/history/`, README generated result blocks, or Pages inputs.

## Probe activity evidence

Record Docker event evidence around every warm-up and measured interval so the investigation can confirm whether recurring health commands were active.

For the baseline policy, collect container-scoped Docker events covering `exec_create`, `exec_start`, and `exec_die` for the selected API container and classify events that correspond to the configured health command. Record at minimum the count and timestamps per interval.

For the controlled policy, assert that no health-probe exec events occur during warm-up or measured intervals. Unexpected exec activity is an investigation failure rather than something to ignore.

Do not estimate or subtract health-probe CPU or memory from measured values. The question is whether the complete observed measurement changes when recurring probes are removed under otherwise equivalent conditions.

## Diagnostic result format

Write one bounded JSON artifact under `.cache/healthcheck-investigation/` containing:

- schema/version for the diagnostic format;
- source commit and source tree;
- active benchmark/cohort identity;
- normal provenance needed to compare same-run conditions;
- exact full benchmark conditions;
- policy definitions;
- per-implementation policy execution order;
- normal three-run endpoint summaries for both policies;
- selected whole-run result using the existing selection rule;
- probe-event counts/timestamps for every interval;
- readiness duration and readiness attempt count;
- any validation failure details;
- deterministic analysis summary.

The artifact must have an explicit marker such as `official: false`, `mode: "healthcheck-investigation"`, and `publishable: false`. Existing official report validators must reject it as an official publication input.

Bound artifact sizes and event counts. Reject malformed Docker events, unexpected container IDs, unbounded output, or missing diagnostic fields.

## Analysis policy

The investigation is descriptive. It does not claim statistical significance from three runs.

For each implementation and endpoint, compare the three baseline and three controlled values for:

- requests per second;
- mean response time;
- observed peak memory.

Record absolute and percentage differences for selected whole-run values, plus each policy's observed min/max across the three runs. The analysis should state whether the direction of the difference is consistent across the three paired run positions, but it must not manufacture confidence intervals, p-values, or a composite score.

A methodology change is not automatically triggered by a numeric threshold in code. The evidence is presented to the owner with run variability and probe activity. The owner decides whether the effect is practically relevant enough to change the measurement policy.

If differences are small or inconsistent relative to the observed three-run spread, prefer retaining the current policy and documenting that in-container probe overhead is included in the measured API container.

## TDD structure

Production behavior changes require failing tests first.

Add tests for:

- policy parsing/default behavior preserves `container-healthcheck`;
- registry-derived generated override disables only the selected API healthcheck and leaves PostgreSQL health enabled;
- external readiness requires the exact `/health` contract and is bounded;
- controlled mode rejects restart/OOM/identity change while waiting;
- process validation allows server + configured probe only in baseline and exactly one server in controlled mode;
- event parser attributes only the owned container and configured health command;
- controlled mode rejects health-probe exec activity during measurement;
- diagnostic artifact cannot be treated as official or publishable;
- deterministic analysis handles positive/negative/zero differences, zero denominators, tied runs, and malformed/incomplete data;
- normal benchmark and official workflow behavior remains unchanged.

Keep test helpers deterministic and isolate Docker integration from unit-level parsing tests.

## Temporary PR measurement job

A one-off full-profile investigation needs real Docker measurement evidence on one GitHub-hosted runner. Add a temporary PR-only job while the investigation is underway. It should:

- run only on this Issue #23 branch/PR;
- use read-only repository permissions;
- use the same pinned actions/tooling and local Docker daemon requirements;
- run both policies sequentially in one job;
- upload only the bounded diagnostic artifact and raw diagnostics needed for audit;
- never use publication credentials or call official/publish/Pages paths;
- clean its owned Compose projects under `if: always()`;
- have a finite timeout justified from the existing official full-cohort runtime and the fact that it runs two policy passes.

After evidence is collected and analyzed, remove this temporary full-profile job before merge. Permanent PR CI must not double in runtime because of a completed one-time investigation.

The final PR head still passes the repository's normal split CI from Issue #22.

## Documentation outcome

Update `docs/METHODOLOGY.md` only with the investigation outcome that is actually supported by evidence.

If current policy is retained, explicitly disclose that recurring API health probes run inside the measured container and their resource use is included in observed complete-stack throughput/latency/memory measurements. Link the investigation evidence/decision record without claiming that no effect exists beyond the tested run.

If a policy change is later approved, update methodology/provenance/schema compatibility before running or publishing any new-policy official result. Clearly distinguish new-policy reports from historical reports.

## Publication and historical safety

Throughout this issue:

- existing `results/latest.json` and history bytes are immutable unless a separately authorized official benchmark later publishes a newly approved methodology;
- no A/B diagnostic is publishable;
- README and Pages must continue to display the existing verified official report;
- Pages trusted-success authorization remains unchanged;
- no official benchmark is dispatched merely to gather investigation evidence;
- old reports remain readable with their original meaning.

## Scope exclusions

Do not implement Issue #24 isolation refactoring, framework Issues #29-#32, README/Pages redesign Issues #25-#28, new benchmark endpoints, new resource budgets, automatic significance testing, health-overhead subtraction, purchased runners, or arbitrary framework tuning.

Do not remove PostgreSQL readiness, contract validation, process-count validation, restart/OOM checks, container identity checks, memory observation, deadlines, or scoped cleanup to improve measured scores.
