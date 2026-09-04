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

These are intentionally simple local-only defaults, not production credentials. Future API services use the common `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, and `DATABASE_PASSWORD` settings from `docker-compose.yml`.

```bash
make db-up      # start PostgreSQL, wait for health, and validate the fixture
make db-check   # validate the exact fixture in the running database
make db-reset   # discard all current DB state and recreate the fixture
make test-db    # run the complete startup, reset, and cleanup acceptance check
make down       # remove containers and the project network
```

PostgreSQL data lives on `tmpfs`. It is never reused across a recreated environment, and `database/init.sql` always creates the same `items` table and row `42 | Item 42 | 4200`.

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
