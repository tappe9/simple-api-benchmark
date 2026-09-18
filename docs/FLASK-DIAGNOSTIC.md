# Flask JSON diagnostic

## Conclusion and boundary

Issue #70 found a reproducible **CPU-placement-sensitive scheduling effect** in
this repository's pinned CPython / Flask / Waitress stack under a one-CPU quota.
It did not establish that Flask's JSON handler is intrinsically slow, that the
published numbers were fabricated, or that a particular GIL/kernel function is
the root cause.

In one same-job baseline / one-CPU-affinity / baseline diagnostic, JSON throughput
was approximately 102 / 1,883 / 103 requests/s. DB throughput stayed approximately
1,190 / 1,204 / 1,207 requests/s. The CPU quota, memory limit, production image,
Waitress worker count and DB pool limit were unchanged. Affinity selected one
already-allowed logical CPU; it did not reserve a dedicated physical core.

These are **non-publishing diagnostic observations**, not replacement official
results, an approved production optimization, or a cross-framework ranking.
Existing applications, pins, official cohorts, methodology and `results/**` were
not changed. Neither #52's deferred publishing/protection work nor #59's next
justified official-run verification is completed by these experiments.

## Retained evidence

All sources below are immutable measured snapshots, not whichever branch is
currently checked out. The corresponding run artifacts were downloaded and their
ZIP SHA-256 values checked during the 2026-09-18 investigation.

| Evidence | Source commit | Run / attempt | Artifact ID |
| --- | --- | --- | --- |
| Original eight-stack publication | `c8e033ea176366644f5bed5ded12cab79e6fcbeb` | [34925168324 / 1](https://github.com/tappe9/simple-api-benchmark/actions/runs/34925168324) | `10380696186` |
| Initial hypothesis matrix | `cbebd385b0f78503d797fcc73167f1ecce1b8611` | [35299848616 / 1](https://github.com/tappe9/simple-api-benchmark/actions/runs/35299848616) | `10529950752` |
| Scheduling probe | `a153a103f445af8cd571687fb095cc0d2f4cb9a3` | [35300974388 / 1](https://github.com/tappe9/simple-api-benchmark/actions/runs/35300974388) | `10529473210` |

ZIP SHA-256 values, in the same order:

```text
cc376a99e573d65c5cedc165ee00fda294795f45ed491a5586ef419f96b9989b
4df46b3f0843e1486d9fe3382c2962efe952dd414283c2f46ba731f6de0e9bf8
ae16af92916f62f198ed509d57273831b5b118c8de4c2f054d57037e42123bec
```

The original selected JSON matched the published file byte-for-byte at audit
main `9b92c74cba34bd5a4bfc389075b9bef135131034`. All 72 original measured windows
passed `benchmark.report.audit_raw`. The original Flask JSON run 2 had mean
response time 315.451675 ms and mean first-byte time 315.450804 ms: downloading
the small body does not explain the observed latency.

Both diagnostic archives were independently replayed against `parse_oha`, the
memory samples, selected whole-run values, observation files and source/tree
identities: **36 + 18 measured windows and 12 + 6 warm-ups**, with no transport
errors or non-200 responses. Every cell used a fresh container; all cells within
each job used one identical image ID. Image IDs between separate jobs need not
match and those jobs must not be pooled as paired measurements. The original
publication does not contain the later per-thread or throttling observations.

Artifacts have finite retention; their availability was verified on the audit
date, not guaranteed forever. An expired original artifact is not recreated by
rerunning a diagnostic. See [Issue #70](https://github.com/tappe9/simple-api-benchmark/issues/70)
for the predeclared plans and review record.

## Experiment 1: switch interval and queue logging

The predefined arms were baseline, Python switch interval 1 ms, and disabled
`waitress.queue` warning output. The second block reversed both arm order and
JSON/DB endpoint order. Each cell recreated PostgreSQL and the API container.
Only the named intervention was applied through a read-only diagnostic startup
hook; baseline had no hook.

Common settings were HTTP/1.1, 50 connections, external readiness stopped before
load, a five-second warm-up and three ten-second measured windows per endpoint.
The unchanged environment enforced one CPU, 512 MiB, one Waitress worker thread
and DB pool maximum 10. These ten-second windows are not the official thirty-
second profile.

| Block | Arm | JSON requests/s | DB requests/s |
| --- | --- | ---: | ---: |
| 1 | baseline | 95.615 | 1,196.952 |
| 1 | switch-1ms | 92.682 | 1,215.155 |
| 1 | queue-quiet | 77.811 | 1,425.894 |
| 2 | queue-quiet | 81.356 | 1,388.971 |
| 2 | switch-1ms | 92.198 | 1,203.858 |
| 2 | baseline | 103.816 | 1,205.640 |

The JSON/DB inversion reproduced. Neither tested intervention improved JSON in
this experiment. Suppressing warnings changed DB throughput, but did not explain
or fix the JSON anomaly. This does not exclude every possible GIL or logging
interaction; it rejects these two simple proposed remedies under the tested
conditions.

## Experiment 2: bracketing CPU-affinity probe

The follow-up plan was recorded before execution. On a new job it ran baseline,
`affinity-one`, then baseline, with fresh environments and JSON then DB in every
cell. Load settings stayed as above. A startup marker confirmed the intervention
in PID 1; `/proc/1/task/*/status` snapshots confirmed the observed threads' CPU
masks. The helper interpreter's metadata is separately labeled, not passed off
as PID 1's runtime configuration.

| Arm | JSON requests/s | JSON mean ms | DB requests/s |
| --- | ---: | ---: | ---: |
| baseline before | 101.553 | 491.030 | 1,190.344 |
| affinity-one | 1,882.871 | 26.508 | 1,204.494 |
| baseline after | 102.701 | 485.357 | 1,206.691 |

JSON throughput in the affinity arm was 18.54 and 18.33 times the two bracketing
baselines. These are within-diagnostic contrasts, not an improvement applied to
an existing official publication. The baselines could run on logical CPUs 0-3;
the affinity arm and its observed threads used CPU 0, still with the one-CPU
quota and identical production image.

JSON observation-span counter deltas were:

| Arm | Throttled periods / periods | Accumulated throttled seconds | Main-thread CPU seconds | Waitress-worker CPU seconds | Worker scheduler slices |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline before | 349 / 363 | 13.613507 | 26.358 | 9.030 | 1,081,401 |
| affinity-one | 25 / 360 | 0.003450 | 17.314 | 17.768 | 28,258 |
| baseline after | 350 / 363 | 13.393709 | 26.353 | 9.038 | 1,066,044 |

These cumulative spans include warm-up, measured windows and observation overhead.
They are not per-request profiles. `schedstat` scheduler slices are not a count
of GIL handoffs, and accumulated throttling time is not a latency decomposition.
DB-pool helper threads showed no material CPU growth in these snapshots.

## Interpretation and next decision

[Waitress's documented design](https://docs.pylonsproject.org/projects/waitress/en/stable/design.html)
separates main-thread client I/O from worker-thread application execution.
[CPU bandwidth control](https://docs.kernel.org/scheduler/sched-bwc.html) limits
aggregate runtime using quota and period; a one-CPU quota is not the same setting
as restricting execution to one logical CPU. Those distinctions explain why
"one process / one worker / one CPU" does not specify every scheduling condition.

The affinity intervention, bracketing baselines and thread/cgroup observations
support a scheduling/CPU-quota interaction in this particular stack. GIL
contention, I/O wakeups, lock contention and kernel scheduling are plausible
lower-level mechanisms, but these experiments do not isolate one of them. No
stack sampling or controlled quota-only experiment was performed. In particular,
it would overstate the evidence to say that the GIL alone, CPU throttling alone,
or a particular Waitress defect was proved responsible. Host noise, one treatment
cell and lack of independent-host replication limit generalization.

The supported next action is to decide and document common CPU-allocation
semantics before changing any official comparison. Keeping the existing quota-
only baseline with an explanation is valid. Adopting affinity would require a
separately reviewed common-methodology decision across the complete cohort, not a
Flask-only boost or a silent overwrite of history. Any later official run still
requires explicit authorization for measurement, audited publication and Pages.

## Reproducing the diagnostics

Use a clean committed checkout, Python 3.10+, Git, curl, Make and a local Linux
Docker Compose v2 daemon reachable through a Unix socket. Leave port 8080 free
and do not run other benchmark services concurrently. No host Flask installation
is needed; the existing pinned production container is built and exercised.

```bash
# No Docker or load: regression tests and CLI help.
python -m unittest discover -s tests -p test_benchmark_flask_diagnostic.py -v
python -m benchmark.flask_diagnostic --help

# Explicit non-publishing invocations; do not run both concurrently.
python -m benchmark.flask_diagnostic --phase initial
python -m benchmark.flask_diagnostic --phase scheduling
```

The initial phase has 36 measured windows and 12 warm-ups; scheduling has 18
measured windows and six warm-ups. Both retain all attempted samples without
selective retries under `.cache/flask-diagnostic/<unique-id>/`. The final
`diagnostic.json` is written only after every cell and its scoped cleanup succeed;
`progress.json` and raw files retain failure evidence. Each invocation uses new
owned Compose projects. CLI help and invalid arguments exit before tool
installation or load. An image change between cells now fails before the next
cell's contract/load; the already measured archives had identical images and
are unchanged by this additional guard.

The report records source/tree, versions, locks, conditions, plan digest,
container identities, readiness, interventions, raw run summaries, memory,
bounded server-log tails and outside-load observations. Tail warning counts may
be lower bounds. Collection introduces overhead outside individual oha windows.
SIGINT/SIGTERM attempt bounded cleanup; SIGKILL/host failure cannot guarantee it.
Inspect the printed owned project name before manually removing leftover
resources, and never use broad Docker cleanup commands for this investigation.

There is no permanent diagnostic workflow or new automatic measurement. The
branch-only investigation workflow was removed after its evidence was retained.
Diagnostics cannot feed the official publisher or Pages. Investigation scratch
notes and Superpowers plans remain untracked under the paths in `AGENTS.md`;
this guide is the durable public explanation, not an implementation plan.
