# Verified result-PR foundation implementation plan

> **For agentic workers:** Use superpowers:executing-plans task-by-task. Do not activate a live publisher in this preparation PR.

**Goal:** Extract audited publication candidates and implement fail-closed result-PR preflight/reconciliation contracts without changing the running official publisher.

**Architecture:** Separate local candidate creation from the existing main update. A second module validates complete GitHub snapshots and constructs a head-bound squash request, but performs no GitHub writes. Live API transport, short-lived App-token jobs, policy/race probes and workflow cutover are a separate integration gate; the snapshot verifier is not a substitute for atomic server-side protection.

**Tech Stack:** Python 3.10+ standard library, Git plumbing, unittest, existing pinned CI.

**Spec:** Issue #52 design checkpoint, option C approved by the maintainer on 2026-09-16. The approved rollout boundary is code/tests/PR first; settings, credentials and official measurement later.

## Global constraints

- Baseline: `51b16dc797f2c061bb6a4fdbb9ae74b67d3b89b6`.
- Preserve all raw-data audits, seven generated paths, source-parent/tree identity, historical reports and existing direct-push race rejection.
- Preserve all four active workflow files byte-for-byte. No new token, secret, ruleset, branch policy, release or official result.
- Never label snapshot validation or an API model as live GitHub rule-enforcement evidence.
- Use exact `success` results, registry-derived complete job inventory and GitHub Actions issuer `15368`.
- No changes to application code, pins, measured workload, generated README values or Pages authorization.

## Task 1: Audited, deterministic candidates

Files: modify `benchmark/publish.py`; create `benchmark/publication_candidate.py` and `tests/test_benchmark_publication_candidate.py`.

Interface: `prepare_publication(report, root, *, expected_context, for_pr=False, environment=None) -> PublicationCandidate`; `verify_candidate(candidate, report, root, *, expected_context) -> None`. Candidate holds source/commit/tree/run/report identities and derives its safe branch name.

- [x] Add real temporary-Git tests before implementation. Key assertions:
  ```python
  candidate = publish.prepare_publication(report, root, expected_context=context, for_pr=True)
  self.assertEqual(remote_main, source)
  self.assertNotIn('[skip ci]', git('show', '-s', '--format=%B', candidate.commit))
  self.assertEqual(candidate, publish.prepare_publication(report, root, expected_context=context, for_pr=True))
  ```
- [x] Run `python -m unittest discover -s tests -p test_benchmark_publication_candidate.py -v`; confirm failures specifically for missing candidate boundary.
- [x] Extract the existing audited generation into `prepare_publication`. Fix PR commit timestamps to report completion, retain the old direct message and push semantics. Candidate creation writes Git objects only, not refs/index/worktree.
- [x] Test untrusted serialized identities by rebuilding from the raw-audited report, not by trusting a bot label or hash field alone.
- [x] Run candidate and existing publication/manifest/handoff suites, then commit the independently testable extraction.

## Task 2: Exact PR/CI/policy preflight

Files: create `benchmark/result_pr.py` and `tests/test_benchmark_result_pr.py`.

Interface: `plan_merge(candidate, *, pull_request, candidate_commit, ci_run, jobs, checks, ruleset, effective_rules, main_sha) -> MergePlan` with immutable expected source/head/tree and a `squash` request. No network or write operation.

- [x] Add a complete synthetic API fixture and tests that separately mutate repository, PR number/ref/head/base, parent/tree, run identity/attempt, issuer, job inventory/conclusion, and strict policy/bypass scope.
- [x] Add the expected request contract before the implementation:
  ```python
  self.assertEqual(plan.request, {'sha': candidate.commit, 'merge_method': 'squash'})
  self.assertEqual(plan.expected_source, candidate.source)
  ```
- [x] Confirm RED, then implement narrow value validators, complete registry-derived CI checks and explicit policy verification. Missing fields, duplicates, truncated inventories, neutral/skipped/cancelled results, pending runs and stale main fail closed.
- [x] Keep the plan explicitly advisory: the merge API guards head only, so live Strict-base race validation remains mandatory before execution.
- [x] Run normal and optimized tests; commit the isolated preflight boundary.

## Task 3: Lost-response reconciliation and final publication identity

Files: extend `benchmark/result_pr.py` and `tests/test_benchmark_result_pr.py`.

Interface: `reconcile_publication(candidate, *, pull_request, merged_commit) -> dict[str, str]`. Returns the existing Pages output names only for a proven merged transaction.

- [x] Add tests that an already-merged PR with matching parent/tree emits the actual squash SHA and original producer attempt; an open/closed-unmerged PR, unrelated commit, multi-parent merge or mismatched tree never emits success.
- [x] Confirm RED, then implement read-only reconciliation. It must not create, retry, rebase, force or roll back a write.
- [x] Verify repetition returns the same output and allows unrelated main advancement after a valid merge without changing the publication identity.
- [x] Run both suites and commit the reconciliation contract.

## Task 4: Runbook, regression gates and PR

Files: create `docs/RESULT-PUBLICATION.md`; link it from `ROADMAP.md`; create `tests/test_benchmark_result_pr_contract.py` for documented dormant status.

- [x] Add a failing guide/link test, then document implemented contracts versus deferred App/API/workflow activation, complete-snapshot sourcing, token lifetime/cleanup, Strict race probes, pause/cutover, failure categories and rollback.
- [x] Run Ruff with the existing pinned binary/config, focused normal/optimized tests, registry/README checks and `git diff --check`.
- [x] Verify all active workflows, result bytes and generated sections equal baseline. Full container checks remain required on GitHub because this local runtime has no Docker.
- [ ] Create one English PR referencing #52 without `Closes`. Verify latest-head full CI and comments; report live integration/configuration as unperformed, not completed.
