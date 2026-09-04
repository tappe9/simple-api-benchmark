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

## Implemented stack baselines

The current Go baseline uses Go 1.27.1, Gin 1.12.0, and pgx/v5 5.10.0. The current Rust baseline uses Rust 1.98.1, Actix Web 4.15.0, and SQLx 0.9.0. Both implementations use one server process or worker, the shared pool maximum of 10 connections, and the same Compose resource limits. Published result files record these versions so later dependency updates remain visible.

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

This target checks Go formatting, unit tests, `go vet`, Compose configuration, image build, service health, exact endpoint responses, the 1 CPU and 512 MB limits, non-root execution, and cleanup. The target complete benchmark command remains:

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
