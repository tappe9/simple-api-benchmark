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

The nine registered implementations, in deterministic registry order, are:
Go / Gin, Go / Echo, Rust / Actix Web, Rust / Axum, Node.js / Fastify,
Node.js / Express, Python / FastAPI, Python / Flask, and Java / Spring Boot. Registration enables
source checks, real-container acceptance and unchanged shared contracts; it does
not by itself activate a benchmark cohort or create measured results.

| Cohort | Ordered members | Current role |
| --- | --- | --- |
| `four-stack-v1` | `go-gin`, `rust-actix`, `node-fastify`, `python-fastapi` | Frozen historical cohort; existing reports remain readable |
| `eight-stack-v1` | `go-gin`, `go-echo`, `rust-actix`, `rust-axum`, `node-fastify`, `node-express`, `python-fastapi`, `python-flask` | Active official cohort; complete verified runs are eligible for publication |

`registered_pinned_versions()` in `benchmark/environment.py` extracts all nine
stacks, while `pinned_versions()` includes only the active cohort's metadata.
Axum additionally records its explicit Tokio version. The
[Axum-only diagnostic](AXUM.md) consumes registered Axum metadata separately and
does not introduce partial official reports.

### Java registration boundary (#67)

`java-spring-boot` is registered with a Java-only host toolchain, real-container
acceptance and the unchanged shared contract. Its static version extractor reads
the committed JDK build, Gradle Wrapper, strict lockfile and SHA-256 verification
metadata without executing Java or Gradle. Other implementation jobs do not need
a host JDK. See [Java / Spring Boot](JAVA-SPRING-BOOT.md).

Neither cohort changes membership or order. Official metadata still contains
only the eight active implementations; Java is not filled into old reports with
zeroes or missing values. A future Java-inclusive cohort and any official run
need a separate decision, including an assessment of JVM warm-up under the common
profile. Registration and passing tests are not measured performance evidence.

### Eight-stack rollout boundary (#50)

The approved activation sets `active_cohort: eight-stack-v1`. Both readers accept
complete four/eight-stack reports, but no synthetic fixture is published and the
active pointer is not evidence of a real eight-stack measurement.
README and Pages identify the selected report's cohort, definition and API
readiness policy; historical views never fill absent frameworks with zero.
Runtime, framework/driver versions, source SHA and runner metadata remain tied to
that one report. Do not combine separate runs into a single ranking.

The maintainer approved the original activation and one full official run with
existing validated automatic publication; Issue #50's rollout is complete. Under
[the current invocation policy](AUTOMATION.md#when-to-request-an-official-benchmark),
future cohort changes require a new explicit measurement/publication request
after the reviewed activation is merged and its CI succeeds. Activation affects
the next explicitly dispatched run; it does not automatically start measurement.
Run the complete cohort on that exact latest-main SHA. Keep main unchanged during
measurement; retain stale-main
rejection rather than rebasing old measurements onto unrelated source.

The unchanged profile requires 8 x 3 x 3 = **72 measured samples**, plus 24 five-second
warm-ups, sequentially on one runner. Test doubles verify that execution sequence
and late failure/cleanup rejection, not actual throughput or elapsed runtime.
The existing 60-minute measurement timeout is unchanged for this rollout. The
nominal load windows alone total 38 minutes (72 x 30 seconds + 24 x 5 seconds),
excluding request drain, builds, startup, checks, sampling and cleanup. This is
not a measured elapsed-time claim. Record the full job and per-stack elapsed
times from the official run logs, including that overhead. A timeout must fail
without publication; any later budget change needs recorded evidence, never
parallelized official measurements or changed per-stack settings.

For any future cohort rollout, keep its tracking issue open until an authorized
full run and atomic JSON/history/README/SVG publication succeed, followed by
dependent Pages and result-link checks. Record
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
set. The active cohort is `eight-stack-v1`; `four-stack-v1` remains frozen for
historical reports, including untagged schema-v1.
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
