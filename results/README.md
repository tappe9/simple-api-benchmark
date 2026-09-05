# Benchmark results

Official `latest.json` and unique `history/<UTC-completion>-<run_id>-<attempt>.json`
are generated only by successful trusted-main weekly/manual benchmark automation.
The same JSON generates both README result sections in one atomic Git commit.
A failed, partial, invalid or stale-source run never replaces the published state.
There is no fabricated placeholder result before the first official success.

`make benchmark` instead produces a **local** `official: false` working-copy result.
The ignore rule prevents accidentally adding a first local file; once the official
file is tracked, a local run appears as an ordinary working-copy modification.
Do not commit it as official data. `make benchmark-smoke` writes only diagnostics
under `.cache/` and never replaces latest. Synthetic test data stays in temporary
test repositories, not here.

[Automation and publication safety](../docs/AUTOMATION.md) documents artifact
retention, history naming, trust boundaries and failure recovery. The
[benchmark guide](../docs/BENCHMARK.md) defines units and the schema. GitHub-hosted
results compare complete API stacks under the recorded conditions, not languages
in isolation. Inspect `metadata` for source, runner and version provenance.
