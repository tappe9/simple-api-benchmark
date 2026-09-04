# Architecture

This document describes the planned v0.1 structure of Simple API Benchmark.

## Design goals

The architecture is intentionally small.

1. A new reader should understand the repository quickly.
2. Every backend should implement the same API contract.
3. A local benchmark should run with one command.
4. GitHub Actions should measure every backend in the same job.
5. README and GitHub Pages should read the same result file.

## Non-goals for v0.1

v0.1 does not attempt to provide:

- hundreds of framework implementations;
- a universal language ranking;
- TLS, HTTP/2, HTTP/3, WebSocket, or gRPC tests;
- ORM, write-heavy, file I/O, or multi-service tests;
- a plugin system or a custom benchmark language;
- a single composite score.

## Components

```mermaid
flowchart LR
    U[Developer] --> M[Makefile]
    G[GitHub Actions] --> M
    M --> R[Python benchmark runner]
    R --> O[oha load generator]
    R --> A1[Go / Gin]
    R --> A2[Rust / Actix Web]
    R --> A3[Node.js / Fastify]
    R --> A4[Python / FastAPI]
    A1 --> P[(PostgreSQL)]
    A2 --> P
    A3 --> P
    A4 --> P
    R --> J[results/latest.json]
    J --> D[README result table]
    J --> S[GitHub Pages]
```

### API applications

Each backend lives in its own directory under `apps/` and is built as a Docker image. An application owns only its framework-specific implementation. It must not contain benchmark orchestration or framework-specific test data.

Every application exposes:

```text
GET /health
GET /json
GET /db/:id
GET /cpu
```

The exact behavior is defined in [docs/API-CONTRACT.md](docs/API-CONTRACT.md).

### PostgreSQL

One PostgreSQL container is shared by all implementations. The schema and fixture data are created from `database/init.sql`. The DB test uses the same parameterized query and the same row for every backend.

### Contract tests

`benchmark/contract_test.py` checks response status, content type, and JSON values before any performance measurement. A backend that fails the contract is not benchmarked.

### Benchmark runner

`benchmark/run.py` is the orchestration entry point. It will:

1. read `benchmark/config.json`;
2. start one backend at a time;
3. wait for `GET /health`;
4. run a short warm-up;
5. run each test three times with `oha`;
6. collect throughput, response time, and peak container memory;
7. reject runs with HTTP errors or timeouts;
8. write `results/latest.json`.

The runner is Python because it is easy to read and is not part of the measured request path.

### Results page

The v0.1 results page is a static site under `site/`. It reads `results/latest.json` and displays a small table and bar charts. It does not need a frontend framework or server-side runtime.

## Planned repository layout

```text
simple-api-benchmark/
├── .github/workflows/
│   ├── ci.yml
│   └── benchmark.yml
├── apps/
│   ├── go-gin/
│   ├── rust-actix/
│   ├── node-fastify/
│   └── python-fastapi/
├── benchmark/
│   ├── config.json
│   ├── contract_test.py
│   ├── generate_readme.py
│   └── run.py
├── database/
│   └── init.sql
├── docs/
│   ├── API-CONTRACT.md
│   └── METHODOLOGY.md
├── results/
│   ├── latest.json
│   └── history/
├── site/
│   ├── app.js
│   ├── index.html
│   └── style.css
├── docker-compose.yml
├── Makefile
└── README.md
```

Directories are added only when the related implementation issue is completed.

## Local benchmark flow

```text
make benchmark
  ├─ build Docker images
  ├─ start PostgreSQL
  ├─ verify all API contracts
  ├─ benchmark JSON
  ├─ benchmark PostgreSQL
  ├─ benchmark CPU
  ├─ collect memory values
  ├─ write results/latest.json
  └─ stop containers
```

Cleanup must run even when a build, contract test, or benchmark fails.

## GitHub Actions flow

### Pull requests

`ci.yml` will build changed applications, run contract tests, and execute a short smoke benchmark. Pull requests do not update published results.

### Scheduled and manual benchmarks

`benchmark.yml` will run weekly and through `workflow_dispatch`. All four backends are measured sequentially in one GitHub Actions job so that they use the same runner.

A successful run updates the result artifact used by README and GitHub Pages. A failed or incomplete run must not replace the latest verified result.

## Resource limits

The initial v0.1 profile is deliberately easy to explain:

```text
API container CPU:       1 CPU
API container memory:    512 MB
Benchmark duration:      30 seconds
Concurrent connections:  50
Runs per test:            3
Displayed value:          middle result
```

The values may be adjusted before the first published benchmark if GitHub-hosted runner measurements show that the load generator becomes the bottleneck. Any change must be documented before publishing results.

## Security boundary

Framework implementations are executable code. Pull request workflows therefore use read-only repository access and do not receive deployment credentials. Publishing is performed only from trusted code on the default branch.
