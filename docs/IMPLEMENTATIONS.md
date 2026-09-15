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

The eight registered implementations, in deterministic registry order, are:
Go / Gin, Go / Echo, Rust / Actix Web, Rust / Axum, Node.js / Fastify,
Node.js / Express, Python / FastAPI, and Python / Flask. Registration enables
source checks, real-container acceptance and unchanged shared contracts; it does
not by itself activate a benchmark cohort or create measured results.

| Cohort | Ordered members | Current role |
| --- | --- | --- |
| `four-stack-v1` | `go-gin`, `rust-actix`, `node-fastify`, `python-fastapi` | Active official cohort; existing published results |
| `eight-stack-v1` | `go-gin`, `go-echo`, `rust-actix`, `rust-axum`, `node-fastify`, `node-express`, `python-fastapi`, `python-flask` | Registered and compatibility-tested; activation and first official publication pending |

`registered_pinned_versions()` in `benchmark/environment.py` extracts all eight
stacks, while `pinned_versions()` includes only the active cohort's metadata.
Axum additionally records its explicit Tokio version. The
[Axum-only diagnostic](AXUM.md) consumes registered Axum metadata separately and
does not introduce partial official reports.

### Eight-stack rollout boundary (#50)

The preparation change retains `active_cohort: four-stack-v1`. Both readers accept
complete four/eight-stack reports, but no synthetic fixture is published and the
existence of `eight-stack-v1` is not evidence of a real eight-stack measurement.
README and Pages identify the selected report's cohort, definition and API
readiness policy; historical views never fill absent frameworks with zero.
Runtime, framework/driver versions, source SHA and runner metadata remain tied to
that one report. Do not combine separate runs into a single ranking.

Activation requires explicit maintainer approval. Changing `active_cohort` also
changes the next scheduled official run, even without manual dispatch. After that
approval, change only the active pointer in a reviewed follow-up, rerun all gates,
and merge before running the existing official workflow on its exact latest-main
SHA. This is not permission to dispatch or publish during preparation.

The unchanged profile requires 8 x 3 x 3 = **72 measured samples**, plus 24 five-second
warm-ups, sequentially on one runner. Test doubles verify that execution sequence
and late failure/cleanup rejection, not actual throughput or elapsed runtime.
The current 60-minute measurement timeout is retained until real execution
provides build, startup, measurement and cleanup timings. Validate that budget
before rollout; justify any change from recorded evidence without parallelizing
official measurements or changing per-stack settings.

Keep #50 open until an authorized full run and atomic JSON/history/README/SVG
publication succeed, followed by downstream Pages and result-link checks. Record
the measured source SHA, publication commit SHA, official run ID/attempt and Pages
run ID separately. A partial run, invalid raw evidence, timeout, cleanup failure
or stale main cannot publish. Leave previous verified results unchanged; obtain a
fresh authorized latest-main run rather than rewriting provenance or force-pushing.

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
set. The current active cohort remains `four-stack-v1`; `eight-stack-v1` is registered
but not yet activated.
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
methodology links remain pinned to the report's measured source commit. Schema-v2
requires a recognized `api_health_policy`; schema-v1 without that field retains
`container-healthcheck` and cannot claim a newer policy.

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

Real-ID compatibility tests in `tests/test_benchmark_eight_stack.py` and
`tests/eight_stack_cases.mjs` use the production cohort registration with temporary
synthetic four/eight-stack reports. They cover complete and malformed reports,
raw-evidence/atomic-publication/Pages authorization, 72-sample sequencing, and
browser filtering/history navigation. Test fixture identities and legacy report
membership do not depend on which cohort is currently active.
