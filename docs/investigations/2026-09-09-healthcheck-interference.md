# Health-check interference investigation — 2026-09-09

## Status

Issue #23 produced controlled same-runner evidence that recurring API-container health probes materially affect the measured benchmark. This record is diagnostic only. It does not change the official benchmark policy, reinterpret historical results, or authorize publication under a new policy.

Current official behavior remains `container-healthcheck` until the maintainer explicitly approves a methodology change.

## Evidence identity

- Pull request: #37
- Measurement workflow run: `34306951462`
- Measurement job: `healthcheck-investigation`
- Job conclusion: `success`
- Diagnostic artifact: `10087963930` (`healthcheck-investigation-34306951462-1`)
- Artifact digest: `sha256:46d1d77338cc6f1beb0e4ee7313eeba6625ff6e179e6ead8d8e1933d20e603a3`
- Branch head measured: `8daf6604807db0fb41a5c68849c04a55daa34299`
- GitHub PR merge commit measured: `d873851dbd627b7dee21d1a8b55326328ae7a422`
- Source tree: `f2c6c0794794a9f0a96f1aa591d9fd0cd1903748`
- Started: `2026-09-09T03:25:46.497104+00:00`
- Completed: `2026-09-09T04:09:50.882850+00:00`
- Diagnostic markers: `status: verified`, `official: false`, `publishable: false`

The PR merge commit and branch head have the same source tree, so the measurement corresponds exactly to the branch content under review.

## Controlled comparison

The two policies were run sequentially on one GitHub-hosted runner with the frozen full profile unchanged:

- 1 API CPU;
- 512 MiB API memory limit;
- one worker/server process;
- pool maximum 10;
- HTTP/1.1;
- 50 concurrent connections;
- 5-second warm-up;
- 30-second measured runs;
- exactly three measured runs per endpoint;
- `/json`, `/db/42`, and `/cpu`;
- pinned `oha` 1.16.0;
- the same contracts, restart/OOM/container-identity checks, deadlines, memory sampling, and cleanup.

Policy order alternated by implementation to reduce simple order bias:

- Go / Gin: baseline → controlled;
- Rust / Actix Web: controlled → baseline;
- Node.js / Fastify: baseline → controlled;
- Python / FastAPI: controlled → baseline.

`container-healthcheck` is the existing Compose policy. `external-readiness` disables only the selected API healthcheck, retains PostgreSQL health, completes bounded host-side `/health` readiness before warm-up, and performs no readiness polling during measurement.

## Selected-run differences

Positive throughput deltas favor `external-readiness`; negative latency and memory deltas mean the controlled policy measured lower values.

| Implementation | Endpoint | RPS baseline | RPS controlled | RPS delta | Mean ms baseline | Mean ms controlled | Latency delta | Peak MiB baseline | Peak MiB controlled | Memory delta |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Go / Gin | `/json` | 20,950.38 | 21,747.94 | +3.81% | 2.384 | 2.296 | -3.66% | 18.46 | 12.96 | -29.79% |
| Go / Gin | `/db/42` | 9,752.30 | 10,157.21 | +4.15% | 5.123 | 4.919 | -3.98% | 22.59 | 16.04 | -29.00% |
| Go / Gin | `/cpu` | 206.20 | 211.65 | +2.64% | 241.578 | 235.312 | -2.59% | 20.18 | 13.90 | -31.12% |
| Rust / Actix Web | `/json` | 48,199.15 | 49,455.42 | +2.61% | 1.035 | 1.009 | -2.54% | 2.98 | 3.19 | +6.98% |
| Rust / Actix Web | `/db/42` | 8,406.39 | 8,601.81 | +2.32% | 5.943 | 5.808 | -2.27% | 9.16 | 4.65 | -49.28% |
| Rust / Actix Web | `/cpu` | 315.27 | 322.96 | +2.44% | 158.172 | 154.405 | -2.38% | 4.95 | 4.88 | -1.42% |
| Node.js / Fastify | `/json` | 12,873.55 | 13,755.15 | +6.85% | 3.881 | 3.632 | -6.43% | 55.46 | 33.30 | -39.96% |
| Node.js / Fastify | `/db/42` | 5,869.36 | 6,425.68 | +9.48% | 8.513 | 7.776 | -8.66% | 61.22 | 44.71 | -26.97% |
| Node.js / Fastify | `/cpu` | 91.36 | 95.09 | +4.08% | 542.560 | 521.296 | -3.92% | 67.81 | 44.69 | -34.10% |
| Python / FastAPI | `/json` | 2,496.95 | 3,072.58 | +23.05% | 19.993 | 16.264 | -18.65% | 52.71 | 40.56 | -23.05% |
| Python / FastAPI | `/db/42` | 1,418.46 | 1,702.99 | +20.06% | 35.228 | 29.344 | -16.70% | 54.08 | 42.04 | -22.26% |
| Python / FastAPI | `/cpu` | 8.36 | 9.13 | +9.32% | 5,491.904 | 5,061.167 | -7.84% | 55.13 | 42.29 | -23.29% |

For throughput and mean latency, every implementation and every endpoint moved in the same favorable direction in all three paired run positions: controlled RPS was higher in `3/3` pairs and controlled mean latency was lower in `3/3` pairs.

Peak-memory direction was also strongly lower for most stacks/endpoints, but Rust `/json` was noisy and its selected controlled value was 6.98% higher. The memory evidence therefore should not be described as uniformly directional, even though the throughput/latency evidence is uniform.

## Probe activity audit

The Docker exec-event audit confirmed that the intended treatment was actually applied.

Across the nine 30-second measured runs per implementation, baseline probe executions were:

| Implementation | Baseline probe execs | Per-run range | Controlled probe execs |
|---|---:|---:|---:|
| Go / Gin | 127 | 13–15 | 0 |
| Rust / Actix Web | 133 | 14–16 | 0 |
| Node.js / Fastify | 106 | 8–14 | 0 |
| Python / FastAPI | 90 | 8–12 | 0 |

All 12 controlled warm-up/measured interval event files per implementation contained zero API-container exec events. Baseline event windows contained only the configured health-probe lifecycle; unexpected API-container exec activity was not observed.

## Interpretation

This is descriptive evidence from one same-runner A/B experiment with three runs per endpoint. It does not claim inferential statistical significance or a universal percentage overhead.

However, the effect is too large and too directionally consistent to classify as merely unestablished within this run. In particular:

- controlled throughput improved on every endpoint for every implementation;
- controlled mean latency decreased on every endpoint for every implementation;
- every throughput/latency paired run position agreed on direction;
- the largest selected throughput changes were Python `/json` (+23.05%), Python `/db/42` (+20.06%), and Node `/db/42` (+9.48%);
- recurring in-container health commands therefore are a material part of the currently measured complete-stack workload, and their cost differs by implementation.

## Decision boundary

The approved Issue #23 design requires explicit maintainer approval before changing official methodology when a practically relevant effect is established. That threshold has been met by this evidence.

Until that approval occurs:

- official benchmark behavior remains `container-healthcheck`;
- historical result bytes keep their original meaning;
- `results/latest.json`, result history, README generated result blocks, and Pages inputs are not rewritten;
- no official benchmark is dispatched under `external-readiness`;
- this diagnostic artifact must never be accepted as publication input.

The proposed methodology change, if approved, is to use `external-readiness` consistently for every API stack: retain PostgreSQL Docker health, disable the measured API container's recurring healthcheck, complete bounded exact `/health` readiness before warm-up, then run the existing contracts and measurement profile with all restart/OOM/identity/deadline/cleanup safeguards intact.
