# Issue #22 Red Expectations

Before implementation, the focused workflow contract is expected to fail because current `ci.yml` still contains only the monolithic `quality` job and `benchmark.ci` has no matrix or aggregate implementation yet.

Expected failing areas:

- missing `plan`, `shared`, `implementation`, `smoke`, and `required` jobs;
- no registry-derived matrix output;
- no per-implementation Compose ownership;
- no stable fail-closed aggregate result;
- missing `matrix_payload()` / `require_success()` CI helper behavior.

The draft PR CI run after this commit is the remote Red evidence. It must fail for these expected assertions rather than infrastructure/setup reasons before Green implementation proceeds.
