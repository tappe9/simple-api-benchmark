# Local results

`make benchmark` creates `results/latest.json` only after every measured run and
all cleanup checks succeed. It is an ignored local output, not an official result.
A failed or partial run leaves an existing file byte-for-byte unchanged.

There are no fabricated placeholder measurements in the repository. Development
fixtures live under `tests/fixtures/`; smoke diagnostics live under `.cache/` and
never replace this file. Official publication and history automation are separate
work. See [the benchmark guide](../docs/BENCHMARK.md) for the schema and limitations.
