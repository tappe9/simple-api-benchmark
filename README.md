# Simple API Benchmark

[日本語](README.ja.md)

**Go vs Rust vs Node.js vs Python — same API, same limits, simple results.**

Simple API Benchmark compares four API stacks with the same endpoints, Docker resource limits, and benchmark settings. The goal is not to declare a universal winner. The goal is to make a small, repeatable comparison that anyone can understand.

> **Project status:** v0.1 is being designed and implemented. No benchmark results have been published yet.

## What is compared?

| Language | Framework |
|---|---|
| Go | Gin |
| Rust | Actix Web |
| Node.js | Fastify |
| Python | FastAPI |

Each implementation will provide the same three benchmark endpoints:

| Test | Endpoint | Simple explanation |
|---|---|---|
| JSON | `GET /json` | Return a small JSON response |
| PostgreSQL | `GET /db/42` | Read one row and return it as JSON |
| CPU | `GET /cpu` | Calculate Fibonacci(30) and return the result |

A separate `GET /health` endpoint is used only to check readiness.

## Results

The latest verified results will be generated automatically here after v0.1 is implemented.

| Backend | JSON requests/s | PostgreSQL requests/s | CPU requests/s | Peak memory |
|---|---:|---:|---:|---:|
| Go / Gin | — | — | — | — |
| Rust / Actix Web | — | — | — | — |
| Node.js / Fastify | — | — | — | — |
| Python / FastAPI | — | — | — | — |

How to read the published results:

- More requests per second is better.
- Lower average response time is better and will be shown in the detailed results.
- Lower peak memory is better.
- Results only describe the documented test environment.

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

The Go implementation lives in `apps/go-gin/` and currently uses Go 1.27.1, Gin 1.12.0, and pgx/v5 5.10.0. It runs one server process with a PostgreSQL pool capped at 10 connections. Docker Compose limits the API container to 1 CPU and 512 MB, runs it as non-root user `65532:65532`, and publishes port `8080` only on the loopback interface.

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

`make test-node-fastify` requires Node.js 24.20.0, npm, Python 3, Docker Compose v2, and Make. It runs focused tests, syntax validation, image and API checks (including real DB updates and errors), resource and process checks, graceful shutdown, and container/network cleanup.

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

All four API implementations are available. The shared contract suite, benchmark runner, and permanent CI remain future work; no performance results are available.

## Planned usage

The v0.1 target is one command:

```bash
make benchmark
```

It will build the containers, verify the APIs, run the benchmarks, and write `results/latest.json`.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [API contract](docs/API-CONTRACT.md)
- [Benchmark methodology](docs/METHODOLOGY.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Important limitation

This project compares complete API stacks, not programming languages in isolation. Results include the framework, runtime, HTTP server, JSON library, PostgreSQL driver, and container configuration. A result such as “Rust / Actix Web was fastest in this run” does not mean “Rust is always fastest.”

## License

[MIT](LICENSE)
