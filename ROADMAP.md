# Roadmap

Simple API Benchmark is developed in small stages. The v0.1 goal is a complete, understandable comparison rather than a large framework catalog.

## v0.1.0

v0.1 is complete when a reader can clone the repository, run one command, and see verified results for four API stacks.

1. Define the shared API contract.
2. Add the Docker Compose and PostgreSQL environment.
3. Implement Go / Gin.
4. Implement Rust / Actix Web.
5. Implement Node.js / Fastify.
6. Implement Python / FastAPI.
7. Add contract tests for all implementations.
8. Add the simple benchmark runner.
9. Add pull request CI and weekly benchmark automation.
10. Add the GitHub Pages result view and publish v0.1.0.

Detailed work and acceptance criteria are tracked in the `v0.1.0` GitHub milestone.

## After v0.1

Possible additions are evaluated one at a time:

- Go / Echo;
- Rust / Axum;
- Node.js / Express;
- Python / Flask;
- Java / Spring Boot;
- C# / ASP.NET Core;
- a simple historical result view.

These are candidates, not commitments.

## Features intentionally deferred

The following remain outside v0.1:

- TLS and HTTP/2 or HTTP/3;
- ORM comparisons;
- database writes and transactions;
- file I/O;
- multi-core scaling;
- cloud price comparisons;
- developer-experience scoring;
- a universal or composite ranking.

A future feature should preserve the core promise:

> Same API. Same limits. Simple results.
