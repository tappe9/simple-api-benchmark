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

Exact language, framework, server, and database driver versions are stored with each result.

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

The database is warmed before measurement. This is not a disk benchmark.

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
| Protocol | HTTP/1.1 |
| Benchmark duration | 30 seconds |
| Concurrent connections | 50 |
| Warm-up | 5 seconds |
| Runs per test | 3 |
| Load generator | `oha` |

All implementations run with the same settings and on the same GitHub Actions job.

## Measurement sequence

For each backend:

1. build its pinned Docker image;
2. start PostgreSQL and the API;
3. wait until `GET /health` succeeds;
4. run all contract tests;
5. warm up the selected endpoint for 5 seconds;
6. run `oha` for 30 seconds;
7. repeat until three valid runs exist;
8. collect the API container's peak memory;
9. stop and remove the API container.

The complete run is repeated for JSON, PostgreSQL, and CPU tests.

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

A run is invalid when any of the following occurs:

- a contract test fails;
- an HTTP response has an unexpected status;
- `oha` reports connection errors or timeouts;
- the API container exits or restarts;
- memory collection fails;
- fewer than three valid measurements are produced.

An invalid or incomplete scheduled benchmark must not replace the latest verified result.

## GitHub Actions limitations

GitHub-hosted runners are not dedicated benchmark machines. Hardware and background load may differ between runs. To reduce confusion:

- every backend is measured in the same job;
- versions and runner information are recorded;
- each test is run three times;
- results are presented as reference values, not universal facts;
- large changes should be reproduced locally or in another scheduled run.

Comparisons within one run are more meaningful than small changes between different dates.

## Reproducibility

The target local command is:

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
