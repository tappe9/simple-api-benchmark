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

How to read the table:

- More requests per second is better.
- Lower response time is better.
- Lower peak memory is better.
- Results only describe the documented test environment.

## Same conditions

Every implementation uses:

- the same API contract;
- the same input and expected output;
- the same CPU and memory limits;
- the same PostgreSQL data and SQL;
- the same load settings;
- three benchmark runs, with the middle result shown.

Contract tests run before measurements. A result with request errors or timeouts is not published as a valid result.

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
