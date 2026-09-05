# Benchmark Methodology

The methodology is intentionally simple enough to explain in a few minutes and strict enough to make the results useful.

## Question being answered

For the documented environment:

> How many requests can each API stack handle, how long do responses take, and how much memory does the API container use?

The project does not claim to identify the universally fastest programming language or framework.

## Compared stacks

v0.1 compares one common framework from each language:

| Display name | Language | Framework |
|---|---|---|
| Go / Gin | Go | Gin |
| Rust / Actix Web | Rust | Actix Web |
| Node.js / Fastify | Node.js | Fastify |
| Python / FastAPI | Python | FastAPI |

The current Go / Gin implementation baseline uses Go 1.27.1, Gin 1.12.0, and pgx/v5 5.10.0. Exact language, framework, server, and database driver versions are stored with each published result so that later dependency updates remain visible.

The Rust / Actix Web baseline uses [Rust 1.98.1](https://github.com/rust-lang/rust/releases/tag/1.98.1), [Actix Web 4.15.0](https://docs.rs/crate/actix-web/4.15.0), and [SQLx 0.9.0](https://docs.rs/crate/sqlx/0.9.0). Serde 1.0.228 and serde_json 1.0.145 are exact direct pins, and `Cargo.lock` fixes the transitive graph. The [official Rust image](https://hub.docker.com/_/rust) has a published 1.98.0 Bookworm builder; it is pinned to index digest `sha256:82150a52ec202c1b14d7817e14516c392bb7f5cfebd88f1ed531cb37ebd39922` and explicitly installs compiler 1.98.1 to retain its miscompilation fix. The Debian Bookworm slim runtime is pinned to `sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171`. Builds use `cargo +1.98.1 build --release --locked`, thin LTO, and one code-generation unit.

Rust uses one Actix worker, normal Serde serialization, a SQLx pool capped at 10 connections, and the common 1 CPU / 512 MB limits. CPU requests execute direct recursive Fibonacci(30) on the worker without caching, memoization, or an executor. Framework/runtime helper threads are not additional HTTP workers. This is a complete-stack comparison, including compiler optimization, not a framework-only result.

The Node / Fastify baseline uses [Node.js 24.20.0 LTS](https://nodejs.org/en/blog/release/v24.20.0), [Fastify 5.12.3](https://www.npmjs.com/package/fastify/v/5.12.3), and [pg 8.23.0](https://www.npmjs.com/package/pg/v/8.23.0). The LTS runtime and stable framework release line are selected for maintenance support. The official Debian Bookworm slim image is fixed by version and index digest in the Dockerfile; exact direct versions and `package-lock.json` freeze the dependency graph. Updating these pins is an explicit baseline change.

Node runs directly as one process with `NODE_ENV=production`, a maximum of 10 DB connections, and the shared 1 CPU / 512 MB limits. Fastify uses its default native-object serialization path without a custom serializer, response schema optimization, cluster mode, or worker threads. CPU requests perform direct recursive Fibonacci(30) on the main event loop, so each CPU calculation occupies that process until completion. This behavior is part of the stack being compared.

The Python / FastAPI baseline uses [Python 3.14.7](https://www.python.org/downloads/release/python-3147/), [FastAPI 0.141.1](https://pypi.org/project/fastapi/0.141.1/), [Uvicorn 0.52.4](https://pypi.org/project/uvicorn/0.52.4/), and [asyncpg 0.31.0](https://pypi.org/project/asyncpg/0.31.0/). The standard CPython release and binary wheels avoid custom interpreter or compiler builds. The official [Python Docker image](https://hub.docker.com/_/python) is fixed as `python:3.14.7-slim-bookworm` plus its index digest. Runtime and development lock files pin the complete resolved dependency graphs and published wheel SHA256 hashes; installation uses `--require-hashes --only-binary=:all:`. Dependency or image updates are deliberate baseline changes, not floating upgrades.

Uvicorn uses one worker, standard asyncio, and h11 for HTTP/1.1, without optional uvloop or httptools acceleration. FastAPI serializes ordinary Python values using its normal response handling. The asyncpg pool is capped at 10, reads the shared database settings, and is checked before HTTP startup. Each async CPU route executes direct recursive Fibonacci(30) on the event loop, occupying the process until the calculation finishes; it does not offload work to a thread or process pool. The common 1 CPU / 512 MB limits remain unchanged. Focused validation is separate from performance measurement.

## Tests

### JSON

```text
GET /json
```

Returns a small JSON object. This includes routing, native object construction, JSON serialization, and HTTP response handling.

### PostgreSQL

```text
GET /db/42
```

Reads one row by primary key and returns JSON. This includes the framework, runtime, PostgreSQL driver, connection pool, database round trip, and serialization.

The shared environment uses PostgreSQL 18.6 from the official `postgres:18.6-bookworm` image pinned by digest. `database/init.sql` creates the exact documented schema and one fixture row. Database data lives on `tmpfs`, and a reset removes the previous environment before recreating the fixture. The database is warmed before measurement, so this is not a disk benchmark.

### CPU

```text
GET /cpu
```

Calculates Fibonacci(30) using the exact recursive definition in the API contract. This includes language runtime and compiler performance in addition to HTTP handling.

## Common conditions

The initial v0.1 settings are:

| Setting | Value |
|---|---:|
| API container CPU limit | 1 CPU |
| API container memory limit | 512 MB |
| API server processes/workers | 1 |
| PostgreSQL pool maximum | 10 connections |
| Protocol | HTTP/1.1 |
| Benchmark duration | 30 seconds |
| Concurrent connections | 50 |
| Warm-up | 5 seconds |
| Runs per test | 3 |
| Load generator | `oha` |

All implementations run with the same settings and on the same GitHub Actions job. A framework may use its normal event loop or runtime threads, but it must expose only one server process or worker and remain within the 1 CPU limit.

## Measurement sequence

For each backend:

1. build its pinned Docker image;
2. start PostgreSQL and the API;
3. wait until `GET /health` succeeds;
4. run all contract tests;
5. warm up the selected endpoint for 5 seconds;
6. run `oha` for 30 seconds;
7. perform exactly three measured runs;
8. collect the API container's peak memory for each run;
9. stop and remove the API container.

The complete sequence is run for JSON, PostgreSQL, and CPU tests.

## Displayed values

### Requests per second

The number of successful responses completed per second. Higher is better.

### Response time

The mean response time reported by the load generator for the selected run. Lower is better. Detailed result data may also retain percentiles for troubleshooting, but the main table stays simple.

### Peak memory

The highest API container memory usage observed during the selected test. Lower is better. PostgreSQL memory is not included in the API container value because the same database container is shared by all backends.

### Middle of three runs

The runner sorts the three valid `requests per second` values and selects the middle run. The throughput, response time, and peak memory shown together all come from that selected run.

Example:

```text
Run 1: 10,500 requests/s
Run 2:  9,900 requests/s
Run 3: 10,100 requests/s

Displayed run: 10,100 requests/s
```

## Valid result rules

A test result is invalid when any of its three measured runs has one of the following problems:

- a contract test fails;
- an HTTP response has an unexpected status;
- `oha` reports connection errors or timeouts;
- the API container exits or restarts;
- memory collection fails.

An invalid or incomplete scheduled benchmark must not replace the latest verified result. Failed runs are not retried until a preferred number appears.

## GitHub Actions limitations

GitHub-hosted runners are not dedicated benchmark machines. Hardware and background load may differ between runs. To reduce confusion:

- every backend is measured in the same job;
- versions and runner information are recorded;
- each test is run three times;
- results are presented as reference values, not universal facts;
- large changes should be reproduced locally or in another scheduled run.

Comparisons within one run are more meaningful than small changes between different dates.

## Reproducibility

The shared database environment can be verified independently:

```bash
make test-db
```

The Go / Gin implementation can be verified independently with:

```bash
make test-go-gin
```

This target checks Go formatting, unit tests, `go vet`, Compose configuration, image build, service health, exact endpoint responses, the 1 CPU and 512 MB limits, non-root execution, and cleanup.

With Node.js 24.20.0 installed, the Node / Fastify implementation can be verified with:

```bash
make test-node-fastify
```

It runs `npm ci`, focused Node tests, syntax validation, production image build, exact API responses against PostgreSQL, BIGINT boundaries, sanitized DB errors, resource/process checks, graceful shutdown, and container/network cleanup. These are focused implementation checks; the common contract suite is available separately, and the local benchmark runner is available separately. Start and test API services sequentially because they share local port `8080`.

With Python 3.14.7 on a POSIX host, Python / FastAPI can be verified with:

```bash
make test-python-fastapi PYTHON=python3.14
```

The target verifies SHA256-locked installs, dependency consistency, Ruff, compilation, and focused pytest behavior before real Docker acceptance. It checks native JSON, exact signed BIGINT values, actual SQL updates, sanitized DB errors, startup failure, one non-root worker, resource limits, pool cleanup, and removal of containers and project networks. These checks do not generate benchmark results or replace the shared contract suite. Docker execution is validated separately from mocked focused tests; unsupported or unexecuted environments must not be reported as passing.

Rust / Actix Web can be verified with:

```bash
make test-rust-actix
```

This target checks the committed source with rustfmt, locked Rust tests, and Clippy, then builds and verifies the pinned production container. Real DB updates and errors, exact numeric JSON, BIGINT boundaries, startup failure, SIGTERM exit, and DB connection/container/network cleanup are included. Run all available DB/API targets after shared Compose changes. These are implementation acceptance checks, not performance measurements.

All four implementations can now be checked against the same documented contract:

```bash
make test-contract
make test-contract CONTRACT_IMPL=python-fastapi
```

The common target performs no measurement. It uses an isolated Compose project,
recreates the PostgreSQL fixture between implementations, verifies each endpoint
twice with strict JSON type and value checks, and fails non-zero before a caller
may proceed to measurement. See [the shared contract guide](../CONTRIBUTING.md#shared-contract-checks)
for standalone base-URL checks, deadlines, and failure cleanup behavior.

The complete local benchmark command is:

```bash
make benchmark
```

The result file records:

- source commit;
- measurement date;
- operating system and architecture;
- Docker version;
- language and framework versions;
- PostgreSQL version;
- resource limits;
- duration and connection count;
- the three raw summaries and selected run.

Anyone may rerun the same commit and compare the generated JSON.

## Runner implementation details

See [the execution and result-format guide](BENCHMARK.md) for strict oha 1.16.0
parsing, verified installation, atomic saving and cleanup. The 30-second setting
is oha's request-sending window; `-w` drains in-flight requests with a 15-second
request timeout. Reported requests/s uses actual elapsed time including drain.
Errors and timeouts invalidate the result rather than being dropped or retried.

Peak memory is the maximum observed, rounded Docker CLI API-container sample,
excluding inactive file cache on Linux. It is not a continuous kernel high-water
mark; sample timestamps/counts are retained and short peaks can be missed.
PostgreSQL is not included. Local and development-validation reports are marked
`official: false`; the runner does not publish README/Pages results or history.
