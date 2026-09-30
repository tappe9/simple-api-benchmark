# JVM warm-up diagnostic (Issue #73)

This is a predeclared, bounded diagnostic of the current five-second warm-up
budget, not an official comparison or permission to admit Java to a cohort.
Java remains registered-only. Existing profiles, cohort definitions, applications,
dependency pins, published reports and historical results are unchanged.

## Question and fixed plan

Does throughput after the fixed warm-up resemble later windows on the same
process, across three clean starts, under this particular host and endpoint order?
The controls are Node / Fastify (another JIT runtime) and Go / Gin (a non-JIT
runtime). They help identify host/common effects but cannot identify a JVM cause
by themselves. Never compare these rows directly with the old eight-stack report.

The three rounds use these orders, all sequentially in one job:

1. Java / Spring Boot → Node / Fastify → Go / Gin
2. Node / Fastify → Go / Gin → Java / Spring Boot
3. Go / Gin → Java / Spring Boot → Node / Fastify

Each of the nine attempts owns a fresh Compose project, API process and PostgreSQL
tmpfs database initialized from the committed fixture. Images use committed pins
and Docker build caching may be reused; this is not a cold image-build benchmark.
The API has 1 CPU and 512 MiB, the pool maximum is 10, and load uses 50 connections,
HTTP/1.1, the pinned oha and the existing 15-second request timeout. The API's
recurring healthcheck is disabled only in the owned measurement project. External
readiness stops before the shared two-round correctness contract and load.

Within each process the endpoint order is `/json`, `/db/42`, `/cpu`. Each endpoint
gets a five-second warm-up, followed by four consecutive 30-second sending windows.
All windows, including warm-up, are retained. No median-winning run is selected
or discarded. Each oha invocation drains outstanding requests; state checks,
metrics and orchestration introduce gaps. Saved wall-clock timestamps expose
these gaps. Thus the windows are successive invocations, not a single gapless load.
The shared contract itself exercises the process before the five-second warm-up:
this diagnoses the existing contract-first sequence, not untouched cold startup.
Later endpoints inherit prior endpoint activity; a result cannot establish
independent cold-start behavior for every endpoint.

## Predeclared provisional interpretation

For each endpoint in each attempt, the last three windows must satisfy all of:

- throughput range divided by its median is at most 5%;
- p95 latency range divided by its median is at most 10%;
- neither throughput nor p95 has a strictly increasing or strictly decreasing
  sequence across those last three windows;
- every window and warm-up has only successful HTTP 200 responses, valid raw oha
  evidence, valid resource identity and no detected restart/OOM/error.

Only then compare the first window's throughput to the later-three median. A
relative difference at most 5% supports the five-second budget for that observed
endpoint/attempt. An implementation must pass every endpoint in every one of its
three attempts to receive the limited overall support flag. Missing, failed or
inconclusive attempts never become a passing result.

These are provisional engineering thresholds fixed before data collection, not a
statistical confidence test or a universal steady-state guarantee. The strict
trend rule is deliberately conservative and can reject random monotonic noise.
A failed stability rule means insufficient evidence within the fixed window, not
proof that Java needs a particular longer warm-up. No threshold, endpoint order
or duration is adjusted after seeing results, and no automatic retry is permitted.
No single attractive sample can establish adequacy. Inspect all repeated/control
windows and timing before recommending a future policy.

## Concurrency and instrumentation limits

One JVM process does not mean one request-processing thread. Spring MVC uses
embedded Tomcat's platform-thread request handling with virtual threads disabled;
this repository does not pin a custom servlet thread-pool size. JDBC calls and
direct recursive CPU work run synchronously on request threads. HikariCP has a
maximum of ten connections and minimum idle zero. Node / Fastify serves requests
on its event loop without cluster/worker-thread offload, while Go / Gin uses the
Go runtime's concurrent request handling. These are whole-stack concurrency
models under common resource caps, not identical thread counts. No runtime is
tuned for this diagnostic. See the implementation guides and pinned source.

The diagnostic records the raw Docker stats snapshots (including CPU percentage
and memory), UTC window boundaries, resource/image identities, source commit/tree,
versions, lock checksums, host information, raw oha output and errors. Docker
stats sampling and state checks run during load and consume host resources;
Docker's sampled memory is not kernel peak RSS. Instrumentation overhead is not
quantified by a paired uninstrumented run. Same-host controls share that method.

No JIT/GC instrumentation flags, attach tools or extra instrumented load runs are
added. JIT compilation/GC events are therefore unavailable, explicitly recorded
as such; a changing window cannot be attributed specifically to either mechanism.
A later causality investigation would need a separate approved budget and should
keep its instrumented observations distinct.

## Execution, evidence and stopping

The **JVM warm-up diagnostic** Actions workflow accepts manual dispatch only on
the trusted default branch. It has read-only repository permissions and no
publication job. Adding the workflow is not permission for unattended recurring
runs. Run it only for an explicitly authorized investigation; do not rerun a
failed or inconclusive run without approval. CI runs synthetic harness and
workflow tests, never this study's real load.

The job cap is 120 minutes. Checkout/setup each have a three-minute cap, the
entire harness (installation, builds, load and cleanup) has a 104-minute timeout,
with TERM followed by a two-minute kill limit; artifact upload has a seven-minute
cap. There are 27 endpoint sequences × 125 sending seconds = 56 minutes 15 seconds
of configured load. Request drain, readiness, contract, sampling, build and cleanup
add time. This estimate is not a guarantee of completion within the cap; an
exhausted budget stops the experiment without a follow-up run.

Each attempt journals progress before starting and after each retained window.
Failure aborts the study, records untouched attempts as not started, and attempts
scoped cleanup. A SIGTERM follows the same failure path. The workflow always
attempts evidence upload, including partial raw files and logs, under
`jvm-diagnostic-<run-id>-<attempt>`, with normal repository artifact access and a
configured 90-day retention. Abrupt worker loss, SIGKILL or failed upload can still
leave missing evidence; never claim that a checksum list proves completeness.
An evidence SHA-256 manifest covers retained study files after orderly completion
or failure; it is an integrity aid, not an independent signature. The separate
bootstrap record covers failures before the study starts.

Artifacts live under `.cache/jvm-diagnostic/`, never `results/`. A diagnostic has
`official: false`, `publishable: false` and its own schema. Official report
validation rejects it. Attempts use new directories and cannot overwrite/resume
old output. Scratch investigations and plans remain local-only per `AGENTS.md`.

After the one approved run reaches a terminal state, audit all attempts and raw
files, then propose one of: keep Java registered-only; consider a separately
approved unchanged-profile cohort; or investigate a new common versioned profile.
A changed official warm-up would apply to every member, with the full selected
cohort measured together. This diagnostic neither chooses that rollout nor
satisfies it. Issue #73 stays open while evidence or the owner's decision remains
unresolved; preparing the harness alone does not complete it.
