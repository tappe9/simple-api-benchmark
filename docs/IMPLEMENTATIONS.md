# Implementation registry and benchmark cohorts

## Sources of truth

`benchmark/implementations.json` is the small, versioned registry for implemented
stacks. An entry contains the stable implementation ID, language, framework,
display name, source/build directory, required version fields, service acceptance
test, and optional focused acceptance-failure test. The Compose service name is
the implementation ID; its build context must equal the registered source path.
This is source configuration, not a plugin interface or executable command list.

Python reads that JSON directly through `benchmark/registry.py`. The unchanged
measurement definition lives in `benchmark/definition.py`; `config.json` is still
checked against that fixed profile. Language-specific manifest/version extraction
remains explicit in `benchmark/environment.py`. Its implementation coverage and
required version keys are checked against the registry rather than assumed.

Two deterministic projections are committed:

- `benchmark/implementations.mk` defines the existing `make test-<ID>` targets and
  their acceptance/failure entry points, in registry order.
- `site/registry.mjs` contains only the viewer's identity, source-path, version,
  definition, and cohort metadata. It contains no measurements.

```bash
python -m benchmark.registry --write  # regenerate those two files only
make test-registry                   # source paths and byte-for-byte drift check
```

Generation and validation require only Python 3.10+ and its standard library.
Do not edit a projection manually. CI also verifies registry/Compose build-context
agreement and that the registry-backed Make target retains every acceptance and
failure gate. The site builder refuses a stale viewer projection before replacing
the previous artifact. No JavaScript package, YAML code generator, or runtime
plugin dependency is introduced.

## Registered and measured implementations

The six registered implementations are Go / Gin, Go / Echo, Rust / Actix Web,
Rust / Axum, Node.js / Fastify, and Python / FastAPI. Registration enables their
source checks, real-container acceptance and unchanged shared contracts. It does
not activate a benchmark cohort: Echo and Axum are implemented candidates outside
`four-stack-v1`, not missing or zero-valued rows in the published result.

`registered_pinned_versions()` in `benchmark/environment.py` extracts all six
stacks, while `pinned_versions()` retains only active-cohort metadata for complete
benchmark reports. Axum additionally records its explicit Tokio version. The
[Axum-only diagnostic](AXUM.md) consumes the registered Axum metadata separately
and does not introduce partial official reports.

## Shared Compose isolation defaults

`docker-compose.yml` defines `x-api-defaults` as the common runtime envelope for
every registered API service. Each API inherits PostgreSQL readiness, the
loopback-only `8080` binding, 1 CPU, 512 MiB, the `benchmark` network, disabled
restarts, `cap_drop: [ALL]`, and `no-new-privileges:true`. Build contexts,
framework-specific environment variables, and API healthcheck commands remain
explicit on each service so implementation differences stay readable.

`make test-compose` validates the **resolved** `docker compose config --format
json` output for every implementation ID returned by the registry, rather than
assuming the YAML merge is correct from source text alone. It also verifies that
PostgreSQL publishes no host port. Per-implementation acceptance tests continue
to prove non-root runtime users and inspect live containers for resource,
capability, privilege, restart, and loopback constraints. Adding a registered API
without the common envelope therefore fails the shared parity gate before its CI
matrix job can run.

The benchmark-time `external-readiness` policy is separate: it disables only the
owned API container's recurring healthcheck during measurement. It does not alter
the shared isolation defaults or PostgreSQL's healthcheck.

## Frozen historical cohort

`four-stack-v1` is an immutable ordered cohort of:

```text
go-gin → rust-actix → node-fastify → python-fastapi
```

Its definition is `simple-api-v1`. A schema-v1 report without a `benchmark` field
resolves **only** to this cohort, even if the active cohort or implementation
registry later grows. It must still contain all four members, all three endpoints
in order, all required versions, valid provenance and measurements. Schema-v1 is
not a fallback that accepts an arbitrary list of implementations. A schema-v1
report with a `benchmark` field is rejected rather than ambiguously reinterpreted.

Existing `results/latest.json` and history files are retained byte-for-byte. IDs,
source paths, required version fields, and published cohort membership are
compatibility contracts: do not repurpose a historical ID or mutate a cohort in
place. A change to those contracts needs a separately reviewed compatibility
policy, not just regeneration against today's implementation list. Runtime and
dependency **version values** remain recorded in each result as before.

## Explicit identity for new reports

New local, smoke, and official reports use report schema-v2. This identity fragment
is added to the otherwise unchanged report structure; it is not a complete report:

```json
{
  "schema_version": 2,
  "benchmark": {
    "definition": "simple-api-v1",
    "cohort": "four-stack-v1"
  }
}
```

The definition and cohort IDs are versioned. The validator accepts only a known
pair from trusted source configuration; the report cannot declare its own member
set. The current active cohort is still the same four implemented stacks.
`conditions.schema_version` remains `1`: CPU, memory, worker/pool limits, endpoints,
warm-up/duration/concurrency, run count, units, and middle-throughput whole-run
selection have **not** changed.

`benchmark/report.py` resolves the known cohort and requires its complete ordered
members, exact version-map membership, required version fields, and complete
ordered endpoint records. Unknown/duplicate IDs, unknown cohorts/definitions,
missing members/endpoints/versions, malformed identities, invalid ordering, and
unofficial or smoke reports fail closed. The existing raw-data audit, trusted
GitHub provenance, clean-source checks and atomic publication remain mandatory.

The runner selects one active cohort before starting and measures it sequentially
on one host, with fresh fixtures and cleanup between members. It does not use a
report-supplied list to control execution. `make test-contract` checks registered
implementations, while official measurement selects the active cohort. Local or
partial data cannot become a complete official result by setting a flag or
supplying a smaller list. No partial benchmark publication mode is introduced.

JavaScript performs presentation validation, not publication authorization. It
renders the report's known cohort rather than the current active list. Missing or
invalid results remain empty/unavailable, never zero. The result JSON link stays
`./results/latest.json` in the displayed publication; implementation and
methodology links remain pinned to the report's measured source commit.

## Adding an implementation

1. Start from an approved implementation issue. Implement the shared API under
   `apps/<ID>/`, with the existing resource limits and pinned production build.
   Add its service acceptance tests and appropriate failure-path coverage. An
   approved framework choice alone is not an implemented or measured stack.
2. Register its identity, source path, required versions and test paths in
   `implementations.json`. Add the explicit version extractor in `environment.py`
   and matching Compose service/build context. Inherit `x-api-defaults`, then keep
   language-specific build, environment, and healthcheck settings explicit. Run
   `make test-compose` so the resolved service proves the common isolation policy.
   Keep language-specific extraction readable; do not introduce a general plugin
   mechanism.
3. Preserve every published cohort. To change the measured member set, add a new
   versioned cohort with its complete ordered membership and the known definition.
   Change `active_cohort` only after the new implementation, compatibility tests,
   and intended cohort activation have been reviewed. Do not modify the old
   `four-stack-v1` list. A definition/profile change needs separate explicit review.
4. Regenerate projections and run the focused gates, substituting the actual ID:

   ```bash
   python -m benchmark.registry --write
   make test-registry
   make test-compose
   make test-<ID>
   make test-contract CONTRACT_IMPL=<ID>
   make test-benchmark
   make test-site
   make test-workflows
   python -m benchmark.generate_readme --check
   git diff --check
   make test
   ```

   `make test-implementations` runs all registered acceptance targets sequentially.
   `make test` retains Compose parity, DB acceptance, all implementation gates,
   shared contracts, tooling/site/workflow checks, non-publishing smoke and the
   separate Axum-only diagnostic. Do not
   run multiple focused API targets concurrently on one host: they share loopback
   port 8080.
5. Add compatibility tests for the new cohort, historical results, malformed and
   incomplete reports, required version extraction, and generated-file/Compose
   drift. Complete PR CI and review before merge. A new official measurement is
   a separate authorized operation; do not hand-edit results or history.

`tests/fixtures/registry/extended.json` and `tests/registry_fixtures.py` provide
four **synthetic** extra members for isolated eight-member tests. They are not
Echo, Axum, Express, or Flask implementations and do not claim measured performance.
Only tests temporarily substitute this trusted fixture registry; there is no CLI
option to load a registry from a report or PR artifact. Synthetic reports, raw
files and generated viewer projections remain in temporary test directories.
