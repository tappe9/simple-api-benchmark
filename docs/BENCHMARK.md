# Running and interpreting benchmarks

## Commands and requirements

Use Python 3.10+ on a POSIX host, Make, Git, curl, and Docker Compose v2 with
`up --wait`. The Docker daemon must run local Linux containers through a Unix
socket. Remote TCP/SSH contexts and alternate Compose wrappers are rejected:
requests target this host's `127.0.0.1:8080`, never an unrelated remote service.
Linux amd64 is the validated platform. The installer also has verified published
asset pins for Linux arm64 and macOS amd64/arm64; those host environments have not
been validated by this change. Docker Desktop adds a VM/networking boundary and
its results should not be compared as identical to native Linux results.

```bash
make install-oha       # optional; make benchmark also verifies/installs it
make test-benchmark    # focused tests; no Docker and no performance claims
make benchmark         # full documented profile, all four APIs and endpoints
make benchmark-smoke   # short diagnostic only; never writes results/latest.json
```

Commit source changes before either real-container command. The runner refuses a
dirty tracked/untracked source tree, but permits the previous local result file.
Stop manually started APIs before running: every API uses port 8080. A port conflict
fails startup; the runner does not stop the process occupying that port.

`benchmark/config.json` fixes the v0.1 load/resource baseline. Changing that
profile requires updating its validator, tests and methodology in a reviewed
change, not silently adjusting a slow implementation. The full profile is 1 CPU,
512 MiB (536,870,912 bytes), one server/worker, pool maximum 10, HTTP/1.1, 50
connections, a 5-second warm-up per endpoint, and exactly three 30-second measured
runs for each of JSON, PostgreSQL and CPU. All four implementations run
sequentially on the same host. API dependencies and Dockerfile pins are not
changed by the runner.

The benchmark measurement health policy is `external-readiness`. The normal
Compose file still contains healthchecks for PostgreSQL and each API. Benchmark
execution overlays only the currently measured API service with
`healthcheck.disable: true`; normal implementation acceptance and standalone
contract workflows keep their existing healthchecks.

The smoke profile uses one-second warm-ups, two-second runs and two connections,
still with three runs and all four APIs. It exercises the same
`external-readiness` startup path as the full benchmark, but its report is
explicitly `mode: smoke`, `official: false`, saved only in its unique
`.cache/benchmark/` directory. It does not substitute for full-profile validation
or publishable measurements.

## Verified load generator

The runner uses the official non-PGO oha **1.16.0** release assets, pinned by SHA256
in `benchmark/install_oha.py`. The digest is verified **before** invoking
`--version`, including on a cached installation. Downloads use HTTPS-only curl,
connection/whole-download deadlines, a temporary file and atomic installation.
Checksum or version mismatch fails rather than falling back to PATH or replacing
a suspicious cache silently. No API dependency is upgraded.

The exact load command includes:

```text
oha --no-tui --output-format json --output <raw-result>
    --http-version 1.1 --redirect 0 --disable-compression
    -c 50 -z 30s -w -t 15s --connect-timeout 5s <endpoint>
```

`-z 30s` sends requests for 30 seconds. On HTTP/1.1, oha normally aborts requests
still pending at that deadline. `-w` instead drains them; the 15-second per-request
timeout bounds that drain. A timeout is still a failed run, never discarded or
retried. The recorded `elapsed_seconds` includes drain; successful requests/s uses
that actual elapsed time, not an assumed 30-second denominator. A two-second
accounting tolerance bounds extra scheduling overhead in the JSON duration check.
The command supervisor has a separate finite outer deadline.

Official references: [release and assets](https://github.com/hatoo/oha/releases/tag/v1.16.0),
[CLI semantics](https://github.com/hatoo/oha/blob/v1.16.0/README.md), and
[JSON serialization](https://github.com/hatoo/oha/blob/v1.16.0/src/printer.rs).
Actual captured outputs, including HTTP errors and timeouts, are committed under
`tests/fixtures/oha-1.16.0/`; they are not API measurements.

## Execution and failure boundary

Each benchmark backend follows this lifecycle:

1. build its pinned API image;
2. start PostgreSQL and require its existing Docker healthcheck to become healthy;
3. start that API with only its recurring Docker healthcheck disabled by a
   benchmark-owned Compose override;
4. inspect the API container and fail unless Docker reports its healthcheck as
   disabled;
5. from the host, poll the shared `/health` contract endpoint with a finite
   absolute deadline until the exact expected response succeeds;
6. stop readiness polling before shared-contract execution, warm-up, and load;
7. verify container identity, resource limits and exactly one server process;
8. call the existing shared `run_contract()` against the running API;
9. warm and measure each endpoint with the fixed profile.

Readiness transport failures may retry only within the absolute deadline. An
unexpected health response fails immediately rather than being treated as a
transient startup condition. Deadline expiry, startup failure, or any later
validation failure prevents measurement publication and enters the same bounded
cleanup path. No host-side readiness request runs during warm-up or any oha load
window.

PostgreSQL is deliberately different: its Docker healthcheck remains active and
is used by `docker compose up --wait`. The policy change applies only to the API
container whose CPU, latency, throughput, and memory are being measured.

The unique `sab-benchmark-*` Compose project is removed after every backend,
recreating the PostgreSQL tmpfs fixture for the next one. It is also removed after
build, startup/readiness, contract, measurement, parser, metric or handled-
interruption failure. Teardown checks that its own containers, networks and
volumes are gone. No other project is removed. Cleanup failure invalidates the
whole result.

A failed run is not retried. A low throughput value is kept when valid; there is
no adaptive load search, score, outlier removal, or retry-until-fast behavior.
Diagnostics identify the implementation, endpoint/run or lifecycle stage and the
underlying failure. The command exits nonzero, preserving the previous result.
Raw oha JSON and per-sample memory diagnostics remain under the printed unique
artifact directory, including partial attempts; their existence is not success.

Build/startup/cleanup commands have 900/120/60-second deadlines. Docker metadata,
state and statistics commands have finite deadlines of 8–30 seconds. External API
readiness has its own finite 60-second absolute deadline and short per-request
bound. On timeout, metric failure, SIGINT or SIGTERM, load-generator/Compose
process groups are killed and their direct children reaped before project
teardown. An early-exiting command cannot leave descendants running in that
group. Cleanup ignores a second handled signal while finishing its bounded work.
SIGKILL, host failure, uninterruptible kernel I/O or an unavailable Docker daemon
cannot guarantee teardown. Recover only the printed project once Docker is
available:

```bash
docker compose -f docker-compose.yml -p <printed-sab-benchmark-project> down --remove-orphans --volumes
```

## Strict parser and units

The parser accepts only the pinned default JSON structure. Missing/extra fields,
wrong types, booleans where numbers are required, duplicate JSON keys, non-finite
numbers, invalid histogram counts, inconsistent units and missing required metrics
are rejected. Counts must be genuine integers. Every status must be 200 and
`errorDistribution` must be empty; success rate must be 1. oha's requests/s counts
all attempts, so it becomes successful throughput only after those error checks.

| oha field | Verified meaning | Stored representation |
| --- | --- | --- |
| `summary.requestsPerSec` | all attempts / actual elapsed seconds | successful requests/s after rejecting every error |
| `summary.average` | mean response time, **seconds** | multiply by 1000 for `mean_response_time_ms` |
| `summary.total` | actual elapsed seconds, including drain | `elapsed_seconds` |
| `summary.totalData` | received body bytes | `response_bytes` |
| `statusCodeDistribution["200"]` | completed 200-response count | `successful_requests` |
| `metrics.latency_ms` | rounded milliseconds | cross-check only; no precision loss in displayed mean |

The parser checks count/elapsed/throughput and byte-rate consistency. A successful
command exit alone does not make JSON valid. Real HTTP error/timeout fixtures
prove that distinction. An API exit, restart, OOM kill, changed start timestamp or
missing memory sample also invalidates the run independently of oha output.

## API memory, not PostgreSQL memory

The runner samples only the exact API container ID with
`docker stats --no-stream --no-trunc --format '{{json .}}' <api-id>`. It validates
the returned ID, binary unit, 512 MiB limit and positive value. State inspection
before samples and after load checks identity/start time and zero restarts.
PostgreSQL is never part of this memory measurement.

Peak memory is the **highest observed Docker CLI sample for that run**, including
its request-drain window. It is not a kernel high-water mark, total process RSS,
or exact continuous peak. Docker rounds its human-readable sample; conversion to
bytes rounds upward to an integer. On Linux, Docker's CLI subtracts inactive file
cache. Samples run serially while oha is pending; Docker's own sampling latency
and state-inspection cost determine spacing (typically roughly two seconds), not
an assumed exact frequency. Sample timestamps and count are retained. A sample
request can straddle load completion; no other endpoint runs in that window.
Short spikes between samples can be missed. See the
[Docker statistics reference](https://docs.docker.com/reference/cli/docker/container/stats/).

## Result format and atomic publication

`results/latest.json` is an ignored local output generated only after **all 36
measured runs and all four teardowns** succeed. No fabricated result file is
committed. The local command does not create official README/Pages results or
history. Once an official result is committed, a local run replaces only your
working copy with `official: false`; do not commit that local replacement as
project results.

New schema-v2 reports contain the fields below plus an explicit
`benchmark.definition` / `benchmark.cohort` identity and an explicit
`metadata.api_health_policy`:

- `schema_version`, `status: verified`, `mode: local`, `official: false`,
  `started_at` and `completed_at` in UTC, and complete `conditions`.
- `metadata`: source commit/tree, host and Docker environment, declared exact
  runtime/framework/server/driver versions read from source manifests, lock-file
  hashes, oha version/asset/hash, API health policy, and measurement-method
  descriptions.
- `implementations`: API/image IDs, command, actual PostgreSQL version and shared
  contract count; each endpoint has its three normalized `runs` and `selected`.

Each run records its 1-based index, successful requests/s, mean milliseconds,
observed peak API memory bytes, memory sample count, actual elapsed seconds,
successful response count and received body bytes. All three raw oha JSON reports
and timestamped memory samples stay in the invocation's artifact directory.

Selection sorts by `(requests_per_second, run)` and takes the middle whole run.
For exact throughput ties, chronological run order breaks the tie. Throughput,
mean response time and memory are copied from that **same** selected run, not
three independently computed medians. Invalid, duplicate or non-three-run inputs
cannot be selected.

Only after complete validation and cleanup does the writer encode finite JSON,
write and fsync a temporary file in the destination directory, and atomically
replace `latest.json`. No partially written file is exposed. A measurement,
cleanup, encoding or pre-rename write failure leaves existing bytes unchanged.
The atomic rename is the publication commit point; it is not a distributed
transaction or a guarantee against storage/host failure.

GitHub-hosted machines are shared infrastructure. Full-profile development
validation artifacts are real measurements but **not official project results**.
Do not interpret small differences as universal rankings.

## Registry and report compatibility

Schema-v2 reports have explicit `benchmark.definition`, `benchmark.cohort`, and
`metadata.api_health_policy` identities. A schema-v2 report without an API health
policy is rejected rather than silently assigned one.

Historical schema-v1 reports remain readable as the frozen ordered
`four-stack-v1` cohort. Those files predate the policy field, so a missing policy
on schema-v1 resolves specifically to the legacy `container-healthcheck` method.
Schema-v1 cannot claim `external-readiness`. Existing JSON is not rewritten.

Comparison compatibility includes the definition/cohort, ordered implementation
members, fixed benchmark conditions, and API health policy. A legacy
`container-healthcheck` result therefore is not methodology-compatible with a new
`external-readiness` result even when endpoints and resource limits are the same.
That distinction preserves historical meaning; it does not declare historical
results invalid.

The policy was changed after the controlled Issue #23 investigation demonstrated
practically relevant recurring-probe interference on one same-runner experiment.
The observed +2.3% to +23.1% selected throughput differences are investigation
evidence, not guaranteed speedups for future runs. See
[the investigation record](investigations/2026-09-09-healthcheck-interference.md).

See [the registry and cohort guide](IMPLEMENTATIONS.md) for identity rules, drift
checks and the framework-addition procedure.

## Official automation

[CI and official automation](AUTOMATION.md) describes the separate trusted-main
wrapper, complete raw-data audit, runner provenance, same-run artifacts and atomic
publication of latest/history/README. The official wrapper explicitly selects
`external-readiness`, while the generic environment default remains the legacy
Compose-health behavior so non-benchmark development workflows are not changed
globally. Official records use `mode: official` and `official: true`, plus
`metadata.github`, `metadata.runner`, `metadata.docker_cli`,
`metadata.docker_compose`, and `metadata.api_health_policy`.

Local and smoke benchmark paths use the same external-readiness measurement
boundary. GitHub Pages and release automation remain outside this runner.
