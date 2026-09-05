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

`benchmark/config.json` fixes the v0.1 baseline. Changing the baseline requires
updating its validator, tests and methodology in a reviewed change, not silently
adjusting a slow implementation. The full profile is 1 CPU, 512 MiB (536,870,912
bytes), one server/worker, pool maximum 10, HTTP/1.1, 50 connections, a 5-second
warm-up per endpoint, and exactly three 30-second measured runs for each of JSON,
PostgreSQL and CPU. All four implementations run sequentially on the same host.
API dependencies and Dockerfile pins are not changed by the runner.

The smoke profile uses one-second warm-ups, two-second runs and two connections,
still with three runs and all four APIs. Its report is explicitly `mode: smoke`,
`official: false`, saved only in its unique `.cache/benchmark/` directory. It does
not substitute for full-profile validation or publishable measurements.

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

Each backend follows: build its pinned image; start PostgreSQL and that API; wait
for Compose readiness; verify container identity, resource limits and one server
process; call the existing shared `run_contract()` against the running API; then
warm and measure each endpoint. The shared suite is not copied or specialized,
and `make test-contract` is not nested inside another lifecycle.

The unique `sab-benchmark-*` Compose project is removed after every backend,
recreating the PostgreSQL tmpfs fixture for the next one. It is also removed after
build, startup, contract, measurement, parser, metric or handled-interruption
failure. Teardown checks that its own containers, networks and volumes are gone.
No other project is removed. Cleanup failure invalidates the whole result.

A failed run is not retried. A low throughput value is kept when valid; there is
no adaptive load search, score, outlier removal, or retry-until-fast behavior.
Diagnostics identify the implementation, endpoint/run or lifecycle stage and the
underlying failure. The command exits nonzero, preserving the previous result.
Raw oha JSON and per-sample memory diagnostics remain under the printed unique
artifact directory, including partial attempts; their existence is not success.

Build/startup/cleanup commands have 900/120/60-second deadlines. Docker metadata,
state and statistics commands have finite deadlines of 8–30 seconds. On timeout,
metric failure, SIGINT or SIGTERM, load-generator/Compose process groups are killed
and their direct children reaped before project teardown. An early-exiting command
cannot leave descendants running in that group. Cleanup ignores a second handled
signal while finishing its bounded work. SIGKILL, host failure, uninterruptible
kernel I/O or an unavailable Docker daemon cannot guarantee teardown. Recover only
the printed project once Docker is available:

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
committed. This command does not create official README/Pages results or history.

Schema version 1 contains:

- `schema_version`, `status: verified`, `mode: local`, `official: false`,
  `started_at` and `completed_at` in UTC, and complete `conditions`.
- `metadata`: source commit/tree, host and Docker environment, declared exact
  runtime/framework/server/driver versions read from source manifests, lock-file
  hashes, oha version/asset/hash and measurement-method descriptions.
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
Do not interpret small differences as universal rankings. Permanent CI, scheduled
benchmarking and official publication remain separate issues.
