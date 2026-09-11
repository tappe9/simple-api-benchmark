# Simple API Benchmark

[日本語](README.ja.md) · [Results site](https://tappe9.github.io/simple-api-benchmark/)

**Go vs Rust vs Node.js vs Python — same API, same limits, simple results.**

Simple API Benchmark contains six API implementations with the same endpoints, Docker resource limits, and validation rules. The goal is not to declare a universal winner. The goal is to make a small, repeatable comparison that anyone can understand.

> **Project status:** v0.1.0 is released. CI, official benchmark automation, and the GitHub Pages results site are available. Go / Echo and Rust / Axum are implemented and CI-covered, while the published official benchmark remains on the frozen `four-stack-v1` cohort until a complete expanded cohort is enabled.

## What is compared?

| Language | Framework |
|---|---|
| Go | Gin |
| Go | Echo |
| Rust | Actix Web |
| Rust | Axum |
| Node.js | Fastify |
| Python | FastAPI |

Each implementation provides the same three benchmark endpoints:

| Test | Endpoint | Simple explanation |
|---|---|---|
| JSON | `GET /json` | Return a small JSON response |
| PostgreSQL | `GET /db/42` | Read one row and return it as JSON |
| CPU | `GET /cpu` | Calculate Fibonacci(30) and return the result |

A separate `GET /health` endpoint is used only to check readiness.

The published result below still represents `four-stack-v1`: Go / Gin, Rust / Actix Web, Node.js / Fastify, and Python / FastAPI. Neither Go / Echo nor Rust / Axum is silently added to that historical cohort.

## Results

<!-- benchmark-results:start -->

Measured (UTC): `2026-09-09T07:25:22.908825+00:00`
Source: `94500edc982a0cfb09be73262266e46eea1cde45` · [Actions run](https://github.com/tappe9/simple-api-benchmark/actions/runs/34321830470)

1 CPU · 512 MiB · 1 worker · DB pool 10 · HTTP/1.1 · 50 connections · 5 s warm-up · 3 × 30 s per endpoint. Middle-throughput whole run selected.

| Backend | Test | Requests/s ↑ | Mean response ms ↓ | Observed peak MiB ↓ |
| --- | --- | ---: | ---: | ---: |
| Go / Gin | JSON | 62,360.983 | 0.800 | 13.080 |
| Go / Gin | PostgreSQL | 27,337.810 | 1.827 | 16.130 |
| Go / Gin | CPU | 306.113 | 162.939 | 15.940 |
| Rust / Actix Web | JSON | 110,917.004 | 0.450 | 2.828 |
| Rust / Actix Web | PostgreSQL | 22,723.975 | 2.198 | 4.547 |
| Rust / Actix Web | CPU | 424.353 | 117.597 | 4.352 |
| Node.js / Fastify | JSON | 46,833.611 | 1.066 | 42.500 |
| Node.js / Fastify | PostgreSQL | 16,157.800 | 3.092 | 53.240 |
| Node.js / Fastify | CPU | 158.943 | 312.997 | 51.280 |
| Python / FastAPI | JSON | 6,307.000 | 7.925 | 40.530 |
| Python / FastAPI | PostgreSQL | 3,127.435 | 15.982 | 42.080 |
| Python / FastAPI | CPU | 16.840 | 2,840.372 | 42.020 |

↑ Higher is better; ↓ lower is better. Memory samples cover only the API container, not PostgreSQL, and can miss brief peaks. These are complete-stack reference results on shared GitHub-hosted hardware, not universal language rankings.

[Result JSON](results/latest.json) · [History](results/history/) · [Methodology](docs/METHODOLOGY.md) · [Versions and conditions](results/latest.json)

<!-- benchmark-results:end -->

## Same conditions

Every implementation uses:

- the same API contract;
- the same input and expected output;
- the same CPU and memory limits;
- one server process or worker;
- the same PostgreSQL data, SQL, and pool limit;
- the same load settings;
- three benchmark runs, with the middle result shown.

Contract tests run before measurements. A result with request errors or timeouts is not published as a valid result.

## Local PostgreSQL environment

Docker Compose v2 and Make are required. The shared database uses the official `postgres:18.6-bookworm` image pinned by digest. It runs as the `postgres` service on the project-scoped `benchmark` network and does not publish a host port.

| Setting | Value |
|---|---|
| Service / host | `postgres` |
| Internal port | `5432` |
| Database | `benchmark` |
| User | `benchmark` |
| Password | `benchmark` |

These are intentionally simple local-only defaults, not production credentials. API services use the common `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, and `DATABASE_PASSWORD` settings from `docker-compose.yml`.

```bash
make db-up      # start PostgreSQL, wait for health, and validate the fixture
make db-check   # validate the exact fixture in the running database
make db-reset   # discard all current DB state and recreate the fixture
make test-db    # run the complete startup, reset, and cleanup acceptance check
make down       # remove containers and the project network
```

PostgreSQL data lives on `tmpfs`. It is never reused across a recreated environment, and `database/init.sql` always creates the same `items` table and row `42 | Item 42 | 4200`.

## Go / Gin implementation

The Go / Gin implementation lives in `apps/go-gin/` and currently uses Go 1.27.1, Gin 1.12.0, and pgx/v5 5.10.0. It runs one server process with a PostgreSQL pool capped at 10 connections. Docker Compose limits the API container to 1 CPU and 512 MB, runs it as non-root user `65532:65532`, and publishes port `8080` only on the loopback interface.

```bash
docker compose up --detach --build --wait go-gin
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
```

Run the complete Go formatting, unit-test, vet, container, API-contract, resource-limit, and cleanup checks with:

```bash
make test-go-gin
```

## Go / Echo implementation

The Go / Echo implementation lives in `apps/go-echo/` and pins Go 1.27.1, Echo v5.3.1, and pgx/v5 5.10.0 so it stays directly comparable with the Gin baseline without silently upgrading the Go runtime or PostgreSQL driver. It uses the same SQL and fixture, connects before serving HTTP, and caps the PostgreSQL pool at 10 connections.

One `net/http` server process serves the Echo router. The implementation adds no unrelated middleware, response cache, or CPU precomputation; `/cpu` performs direct recursive Fibonacci(30) for every request. The production image contains only the statically built binary, runs as non-root `65532:65532`, and inherits the shared 1 CPU / 512 MB isolation envelope, capability drop, no-new-privileges policy, loopback-only port publication, and restart policy from Compose.

```bash
docker compose up --detach --build --wait go-echo
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
make test-go-echo
```

`make test-go-echo` runs formatting, unit tests, vet, production image and real PostgreSQL/API acceptance checks, BIGINT boundaries, startup failure, graceful SIGTERM shutdown, resource/process isolation, and cleanup. The shared contract suite runs against Echo unchanged. A future Gin-versus-Echo result is still a complete-stack comparison of framework/router behavior under this repository's fixed conditions, not a universal ranking of Go frameworks.

## Rust / Actix Web implementation

The Rust implementation lives in `apps/rust-actix/` and pins Rust 1.98.1, Actix Web 4.15.0, SQLx 0.9.0, Serde 1.0.228, and serde_json 1.0.145. `Cargo.lock` fixes the transitive dependency graph. One Actix worker serves port `8080`, uses native Serde response values, and performs direct recursive Fibonacci(30) for every CPU request. The SQLx pool connects before HTTP startup and allows at most 10 PostgreSQL connections.

The production Dockerfile uses the published `rust:1.98.0-bookworm` builder pinned by digest and explicitly installs compiler 1.98.1, which fixes a compiler miscompilation. It builds with `cargo +1.98.1 build --release --locked`. The digest-pinned Debian Bookworm slim runtime contains the release binary, not Cargo or the source tree, and runs as `65532:65532`. Compose waits for healthy PostgreSQL, drops capabilities, disallows privilege escalation, applies 1 CPU / 512 MB limits, publishes only `127.0.0.1:8080`, and disables restarts.

```bash
docker compose up --detach --build --wait rust-actix
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
make test-rust-actix
```

The acceptance target requires Rustup, Python 3, Docker Compose v2, and Make. It runs formatting, locked Rust tests, Clippy with warnings denied, real DB and API checks, BIGINT boundaries, startup failure, SIGTERM shutdown, and container/network cleanup. Run API services sequentially because they share host port `8080`.

## Rust / Axum implementation

`apps/rust-axum/` adds Axum 0.8.9 and Tokio 1.53.1 without changing the Actix implementation. Rust 1.98.1, SQLx 0.9.0, Serde 1.0.228, serde_json 1.0.145, and the digest-pinned builder/runtime bases match that baseline. The committed lockfile fixes transitive dependencies.

One direct server process uses an explicit Tokio `current_thread` executor. Native Serde responses, the shared parameterized SQL and pool maximum of 10, and per-request direct recursive Fibonacci(30) are preserved. There is no CPU offload, response cache, or additional async worker. SIGINT/SIGTERM drain accepted requests before closing the pool. The non-root release image inherits the shared 1 CPU / 512 MiB isolation envelope.

```bash
make test-rust-axum                       # Rust gates and real PostgreSQL/container acceptance
make test-contract CONTRACT_IMPL=rust-axum # unchanged shared contract
make axum-diagnostic                      # clean committed source; never publishes results
```

Run these commands sequentially with port 8080 free. The Axum-only diagnostic uses the existing pinned load generator and external readiness, records provenance, versions and raw evidence under `.cache/axum-diagnostic/`, and fails on request errors or cleanup failure. Its short profile is not an official performance result. It is a required step in Axum's normal CI job; no temporary development workflow is needed. See [Axum implementation and diagnostic](docs/AXUM.md) for runtime details, test coverage, and output guarantees.

## Node.js / Fastify implementation

The Node implementation lives in `apps/node-fastify/` and uses Node.js 24.20.0 LTS, Fastify 5.12.3, and pg 8.23.0. Direct dependencies and `package-lock.json` are pinned; the official `node:24.20.0-bookworm-slim` image is also pinned by digest. The LTS runtime and stable Fastify 5 release line keep this baseline reproducible and maintainable.

It starts one Node process directly in production mode, waits for a PostgreSQL readiness query, and uses a pool capped at 10 connections. The container runs as non-root user `node`, drops Linux capabilities, and uses the shared 1 CPU / 512 MB limits. Only `127.0.0.1:8080` is published. `/json` uses native objects and `/cpu` calculates Fibonacci(30) by direct recursion on every request. Shutdown closes the HTTP server and pool.

Start only one API at a time because implementations share the local port:

```bash
docker compose up --detach --build --wait node-fastify
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
make test-node-fastify
```

`make test-node-fastify` requires Node.js 24.20.0, npm, Python 3, Docker Compose v2, and Make. It runs focused tests, syntax validation, production image build, exact API responses against PostgreSQL, BIGINT boundaries, sanitized DB errors, resource/process checks, graceful shutdown, and container/network cleanup.

## Python / FastAPI implementation

The Python implementation lives in `apps/python-fastapi/` and uses Python 3.14.7, FastAPI 0.141.1, Uvicorn 0.52.4, and asyncpg 0.31.0. Runtime and development dependencies have exact, SHA256-verified lock files. Both Docker stages use the official `python:3.14.7-slim-bookworm` image pinned by index digest.

Uvicorn runs directly with one worker, the standard asyncio event loop, and the h11 HTTP/1.1 implementation. Startup checks PostgreSQL before accepting HTTP requests; the asyncpg pool has at most 10 connections. Responses are serialized from ordinary Python values, including exact signed BIGINT IDs. Every `/cpu` request computes Fibonacci(30) by direct recursion, without caching or precomputation. Lifespan shutdown closes the pool.

The production container runs as non-root user `10001:10001`, excludes tests and development dependencies, drops Linux capabilities, and uses 1 CPU / 512 MB. Compose waits for PostgreSQL health, publishes only `127.0.0.1:8080`, probes `/health`, and does not restart the service.

```bash
docker compose up --detach --build --wait python-fastapi
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
make test-python-fastapi PYTHON=python3.14
```

The complete acceptance target requires Python 3.14.7 on a POSIX host, Docker Compose v2, and Make. It installs the hash-locked development dependencies in a temporary virtual environment, runs Ruff and focused pytest tests, and verifies the real Docker service, DB errors and updates, resources, one worker, startup failure, SIGTERM shutdown, and container/network cleanup. See [Contributing](CONTRIBUTING.md) for focused tests without Docker.

All six API implementations and the shared contract suite are available:

```bash
make test-contract                       # all six APIs, one at a time
make test-contract CONTRACT_IMPL=go-echo # one API with the same contract
```

The suite checks exact statuses, JSON content and types, documented errors, and
repeated responses, and cleans up its isolated environments even after failure.
See [the shared contract guide](CONTRIBUTING.md#shared-contract-checks) for
requirements, standalone base-URL checks, and cleanup limits. The local benchmark runner
is available, and pull requests run the same checks plus a non-publishing smoke benchmark.
Official results come only from the trusted-main [weekly/manual workflow](docs/AUTOMATION.md).
The active official cohort remains `four-stack-v1`, so adding Echo and Axum to the implementation
registry does not alter or republish the existing official result set.

## Run the local benchmark

With a clean committed source tree, Python 3.10+, curl and local Docker Compose v2:

```bash
make benchmark
```

It verifies/installs checksum-pinned oha 1.16.0, builds and starts one API at a time,
runs the shared contract, performs the fixed warm-up and three measured runs per
endpoint, and atomically writes `results/latest.json` only after all results and
cleanup succeed. Existing results survive any partial failure. The generated file
is a local result, not an official publication.

Use `make test-benchmark` for focused tests or `make benchmark-smoke` for a short
diagnostic that never replaces `latest.json`. See [the benchmark guide](docs/BENCHMARK.md)
for requirements, exact units, result schema, deadlines and memory-sampling limitations.

## Documentation

- [Results site](https://tappe9.github.io/simple-api-benchmark/)
- [Architecture](ARCHITECTURE.md)
- [Axum implementation and diagnostic](docs/AXUM.md)
- [API contract](docs/API-CONTRACT.md)
- [Benchmark methodology](docs/METHODOLOGY.md)
- [Running benchmarks and result format](docs/BENCHMARK.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Important limitation

This project compares complete API stacks, not programming languages or frameworks in isolation. Results include the framework, runtime, HTTP server, JSON library, PostgreSQL driver, and container configuration. A result such as “Rust / Actix Web was fastest in this run” does not mean “Rust is always fastest,” and a future Gin-versus-Echo difference would not establish a universal ordering between those Go frameworks.

## License

[MIT](LICENSE)
