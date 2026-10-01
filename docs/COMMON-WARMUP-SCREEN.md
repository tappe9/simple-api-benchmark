# Common warm-up screen v1 (Issue #73)

This predeclared, non-publishing diagnostic follows the initial
[JVM diagnostic](JVM-DIAGNOSTIC.md). It does not replace that study or retrospectively
change its interpretation. Protocol ID: `common-warmup-screen-v1`. Java stays
registered-only; official profiles, cohorts, runtime tuning, pins and results are
unchanged. The output is a candidate for independent confirmation, not proof of
steady state or authorization for a nine-implementation comparison.

## Fixed experiment

Java / Spring Boot, Node / Fastify and Go / Gin each receive two fresh starts for
**each** of `/json`, `/db/42` and `/cpu`: 18 traces. All traces run sequentially on
one host. Each owns a fresh Compose project, API process and PostgreSQL tmpfs
fixture. Host caches and image-build caches are not reset, and process restarts
are not independent hosts. The first-round order is:

1. Java JSON, Node DB, Go CPU
2. Java DB, Node CPU, Go JSON
3. Java CPU, Node JSON, Go DB

The second round reverses all nine entries. This balances simple early/late
positions, but two starts do not eliminate host drift or establish confidence
intervals. All attempts are retained, including failed and unstarted entries.

Before measurement, one separate sacrificial instance per implementation passes
the full shared two-round correctness contract. Those instances are cleaned up;
measured instances never receive that contract or another endpoint's load. The
measured image must match its validated image, and API/database identities must
be distinct across all instances. Only logged `/health` readiness requests occur
before measured load. They can initialize shared application code: these are not
untouched cold starts. PostgreSQL identity and fixture checks occur before API
startup. The resource caps remain 1 CPU and 512 MiB, pool maximum 10, 50 connections,
HTTP/1.1 and the existing 15-second request timeout. Recurring API healthchecks are
disabled in the owned projects only. No application or dependency tuning occurs.

Each trace sends five seconds of initial load, then eight 30-second windows.
All 162 invocations (18 warm-ups and 144 windows) are retained. Separate oha
invocations drain requests and have state-check, sampling and orchestration gaps.
Window timestamps, elapsed time, process age and gaps expose this limitation;
these are nominal cumulative-load budgets, not exact process-age intervals or a
single continuous load stream.

## Predeclared screening rule

Candidates are 5, 35 and 65 seconds of nominal cumulative load. Their first three
measurement windows are respectively 1–3, 2–4 and 3–5. The reference is always
windows 6–8 (nominal load 155–245 seconds), disjoint from those candidate windows.
There is no search outside this grid, adaptive extension or automatic retry.

For each trace, all warm-ups/windows must have valid raw evidence, zero transport
or non-200 errors, and passing resource/identity/restart checks. Then:

- Reference throughput range / median is at most 5%; p95 range / median at most 10%
- Every window from the candidate's first measurement through window 8 is within
  ±5% throughput and ±10% p95 of the respective reference median
- The candidate's first-three throughput range / median is at most 5%; its p95
  range / median is at most 10%

A candidate is screened in only if **all 18 traces** pass: both starts, every
endpoint and all three implementations. Otherwise it remains unsupported by this
screen. No passing candidate means **inconclusive**; it is not proof that a longer
warm-up would solve the problem. Report every window and all candidate outcomes.
Inclusive comparisons allow only machine-roundoff-scale relative error (1e-12
of the threshold), so decimal boundary values are not rejected accidentally.

These are practical engineering tolerances, inherited in magnitude from the first
study, not statistically established equivalence margins. A strictly monotonic
reference sequence is reported but does not by itself reject arbitrarily small
noise. This deliberately differs from the first study's strict monotonic rule;
that study and its original failures remain intact. The new rule is fixed before
new data collection. Even a passing candidate needs independent confirmation
using an explicitly specified continuous warm-up, and eventual coverage of all
nine implementations under separately approved conditions.

## Evidence and limits

The screen retains source commit/tree, host and pinned version information, lock
hashes, image/container/database identities, fixture checks, readiness probes,
allowlisted state snapshots, process checks, CPU/memory samples, every raw oha
output, UTC timing, contract logs and failure/cleanup evidence. Inspection records
exclude credentials. A checksum manifest is an integrity aid, not a signature or
proof that missing files never existed.

Docker stats and checks consume host resources. Their overhead is visible in
timing but is not quantified by an uninstrumented comparison. Sampled memory is
not peak RSS. No JIT/GC instrumentation is enabled; neither compilation nor GC can
be established as the cause of a changing window. One JVM process does not mean
one request-handling thread; concurrency semantics remain as documented in the
original guide and implementation sources.

## Budget, execution and stopping

The separate **Common warm-up screen v1** workflow is manual-only on the trusted
default branch, with read-only repository permissions and no publication job.
Code merge does not imply permission for future runs. The approved scope is one
additional run, not automatic repetition or a future official comparison.

Configured load: 18 × (5 + 8 × 30) = 4,410 seconds = 73.5 minutes. Approximately 90–110
minutes including setup is an estimate, not a completion guarantee. The job cap
is 120 minutes; workload is terminated after 104 minutes with a 120-second kill grace.
Checkout and Python setup each have a 3-minute cap, and artifact upload has a
7-minute cap. Cleanup and upload time are reserved. Failure or time exhaustion
aborts remaining work, journals it and attempts scoped cleanup; there is no rerun
or threshold relaxation. Worker loss, SIGKILL or upload failure can still leave
incomplete evidence, which must be disclosed.

Evidence lives only in `.cache/common-warmup-screen/`, uploaded even on failure as
`common-warmup-screen-<run-id>-<attempt>` with 90-day retention. Unique directories
cannot be resumed or overwritten. The schema explicitly marks output
`official: false` and `publishable: false`; official report validation rejects it.
CI tests use synthetic data and do not execute this study's load. Audit raw data
and completeness before recording the outcome in Issue #73. Nine-implementation
confirmation, official-profile changes and result publication require a later
plan and separate approval; they are not included in this run's budget.
