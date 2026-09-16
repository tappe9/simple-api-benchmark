# Roadmap

Simple API Benchmark is developed in small stages. The v0.1 goal is a complete, understandable comparison rather than a large framework catalog.

## v0.1.0

**Status: released.** v0.1.0 provides a cloneable, one-command benchmark with verified results for four API stacks and a simple GitHub Pages result view.

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

The completed work and acceptance criteria are recorded in the `v0.1.0` GitHub milestone.

## Current main (after v0.1.0)

These changes are implemented on `main`; they do not retag or change the original
v0.1.0 release. A next release version remains an explicit maintainer decision.

| Milestone | Status and evidence |
| --- | --- |
| Eight API implementations | Complete: Gin, Echo, Actix Web, Axum, Fastify, Express, FastAPI and Flask are registered and CI-covered. Axum retains its required non-publishing diagnostic. |
| Versioned eight-stack cohort | Active: `eight-stack-v1`; the historical `four-stack-v1` remains frozen. [#50](https://github.com/tappe9/simple-api-benchmark/issues/50), [#57](https://github.com/tappe9/simple-api-benchmark/pull/57), [#58](https://github.com/tappe9/simple-api-benchmark/pull/58). |
| Verified eight-stack publication | Complete: the first full result was published on September 15, 2026, by [run 34925168324](https://github.com/tappe9/simple-api-benchmark/actions/runs/34925168324). See [#50](https://github.com/tappe9/simple-api-benchmark/issues/50) for measured-source, publication and Pages identities. Activation alone is not measurement evidence. |
| Result presentation | Complete: README charts, the filterable light/dark Pages dashboard and historical-run navigation. History was delivered in [#28 / #46](https://github.com/tappe9/simple-api-benchmark/pull/46); old reports retain their own cohort and provenance. |
| Focused CI toolchains | Complete: registry-derived setup with all existing gates retained. [#51 / #61](https://github.com/tappe9/simple-api-benchmark/pull/61). |
| Pages/release separation | Routine Pages deployment cannot create a product release. Use the explicit [release procedure](docs/RELEASING.md), tracked in [#53](https://github.com/tappe9/simple-api-benchmark/issues/53). |

## Remaining tracked work

- [#59](https://github.com/tappe9/simple-api-benchmark/issues/59): the direct
  official-publication-to-Pages dependency was implemented by
  [#60](https://github.com/tappe9/simple-api-benchmark/pull/60). Ordinary Pages and
  live-file verification passed, but a new real official producer followed by its
  dependent deployment still needs end-to-end evidence. Fixture tests and manual
  recovery do not close that boundary; do not rerun measurement just for display.
- [#52](https://github.com/tappe9/simple-api-benchmark/issues/52): design and obtain
  maintainer approval for main protection compatible with trusted result
  publication before changing settings, credentials or result storage.

## Future candidates

Java / Spring Boot and C# / ASP.NET Core may be evaluated one at a time. These are
candidates, not commitments or implemented benchmark entries. Historical-result
navigation is already available, not a future candidate.

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
