# Protected-main result publication: preparation and cutover

Option C in [Issue #52](https://github.com/tappe9/simple-api-benchmark/issues/52)
was approved by the maintainer on September 16, 2026: a repository-specific
publisher App, result-only PRs, complete CI and controlled squash merges, without
any protection bypass. Implementation and live activation are separate stages.

## What this preparation provides

**No live result-PR controller is enabled by this change.** The active official
workflow still runs the existing audited, ordinary fast-forward publisher. All
four workflow files, CI job names, measured inputs and published results remain
unchanged. This is a foundation, not completion of #52 or the live handoff proof
in #59. No App, private key, environment or ruleset has been provisioned here.

| Interface | Responsibility |
| --- | --- |
| `publish.prepare_publication(..., for_pr=True)` | Validate the exact report context and raw evidence, require a clean measured-source checkout, generate the seven allowed paths, and create a deterministic candidate commit. It writes local Git objects only, never refs, the normal index, working files or a remote. |
| `PublicationCandidate` | Immutable source/commit/tree/producer/report-digest identifiers, with a deterministic branch name and strict serialization. Serialization is not authentication. |
| `publish.verify_candidate(...)` | Rebuild from the trusted source and original raw-audited report before accepting a stored candidate identity. |
| `result_pr.plan_merge(...)` | Validate an exact candidate PR, its single-parent Git transaction, complete successful CI and explicit strict/no-bypass policy snapshots. Return a head-bound squash request; do not execute it. |
| `result_pr.reconcile_publication(...)` | Inspect a confirmed merged PR and the actual merge commit after a lost response. Emit existing Pages output fields only when parent/tree/head identities match. Never retry or undo a write. |

PR candidates contain no `[skip ci]` marker. Their author/committer dates are fixed
to the verified report's completion timestamp, so rebuilding the same candidate
on a later retry preserves its SHA. The branch is derived from the original run
ID, original producer attempt and full measured-source SHA; do not choose it from
an untrusted PR title, label, arbitrary user input or changed run context.

The old `publish.publish(...)` path shares candidate generation but retains its
existing commit message, main freshness check and non-force fast-forward update.
Its remote update is still the sole publication commit point. A race that advances
main still rejects the update; no fallback rebase or forced push is introduced.

## Trust and snapshot contracts

Before preflight, obtain/rebuild the candidate using controller code from the
trusted measured-source revision, not by checking out or executing a submitted PR.
The proposed tree must be generated from the original audited raw artifact. The
seven paths remain README.md, README.ja.md, latest JSON, one new immutable history
JSON and three charts; README text outside the generated section is preserved.

The preflight accepts **raw REST-shaped snapshots**, not shortened connector
summaries. The future transport/controller must fetch all pages, reject transport
or permission failures, and re-read run/head/main identity around snapshot assembly:

- The PR is in this repository, open and non-draft, with the deterministic head
  branch, exact candidate SHA, one commit and main at the measured-source SHA.
- The run is this repository's `CI` workflow (`.github/workflows/ci.yml`, current
  workflow ID `350921839`), `pull_request` event, the exact head and exactly the
  expected PR association. Repository ID `1356993741` is also bound. Deliberately
  recreating the workflow/repository requires a reviewed identity update.
- The job and check inventories must be complete and unique. Every registered
  implementation is required, including inactive cohort members, along with
  `plan`, `shared`, `smoke` and `required`. Their conclusions must be literally
  `success`, not neutral, skipped or merely mergeable. Job/run/attempt/check-suite
  identities and GitHub Actions issuer `15368` must all match.
- Retrieve jobs for the selected exact run attempt, and checks for that suite.
  A re-requested run or newer CI supersedes an older successful snapshot. Selecting
  the latest applicable run, pagination, bounded polling and final re-reads are
  future transport responsibilities, not implemented by the pure verifier.
- Policy input must describe the reviewed active repository ruleset for exactly
  `refs/heads/main`, no exclusions/bypass, required PR/squash/conversation
  resolution, strict `required` from Actions, and blocked force pushes/deletion.
  The complete effective branch rules must match that inspected ruleset. Unknown
  or additional rules require review rather than silent acceptance.

**A preflight plan is not a lock.** GitHub's merge API `sha` precondition protects
PR head, not base. Fresh client-side checks alone cannot guarantee the measured
parent during a concurrent main update. Before enabling a live merge caller,
prove Strict-base rejection under the actual effective policy, including the
race between the final read and the merge request. Never claim these unit tests
exercise GitHub's live enforcement, and never enable the caller on that basis.

### Policy visibility must be resolved without broadening the publisher

GitHub documents that `bypass_actors` is returned only to a reader with write
access to the ruleset. A Metadata-readable ruleset response can omit it. Omission
is **unknown**, not an empty bypass list, and this verifier rejects it. Do not add
Administration permissions to the publisher or pass an administrator token to PR
code to work around this boundary.

Live integration therefore needs a separately reviewed owner-admin inspection
and policy-change detection/attestation path alongside live effective-rule reads.
A fixture, manually constructed empty array, stale saved JSON, green badge, or
`admin: true` repository metadata is not sufficient evidence. This administrative
read boundary and the Strict race probe are prerequisites for activation. The
current connector's administrative-read limitation is not permission to bypass it.

## Remaining integration work before activation

Keep the following as a separate reviewed integration/rollout stage. None of these
operations is performed or automatically enabled by the helper APIs above.

1. Implement a bounded, same-repository API transport/controller. Create/reconcile
   exactly one deterministic result branch/PR, bind its number/head/tree, retrieve
   the latest complete exact-attempt CI, and execute only the audited squash request.
   On a missing response, re-read remote identities before any retry. Never update
   a modified branch, merge an arbitrary code PR, follow untrusted API URLs with a
   credential, or interpret 403/transport errors as absence.
2. Add separate trusted proposal, read-only CI-wait and final-merge jobs to the
   official workflow. Download only its own original measurement artifact. Mint
   short-lived, repository-scoped App tokens only for proposal and merge, and
   revoke them during cleanup; no write token/private key in the wait job, PR CI,
   measurement, Pages, logs or artifacts. Preserve the original producer attempt
   across deployment-only retries rather than relabeling measurements.
3. Provision the maintainer-owned App/environment after approval. Restrict the
   App to this repository with Contents/Pull requests write, no Administration,
   Workflows, Checks-write, Statuses-write or bypass. Restrict key availability
   explicitly to main (not arbitrary PR refs or similarly named tags). Never
   paste private keys into chat or commit them. Native auto-merge stays disabled.
4. With authorized owner administration, inventory and verify effective settings,
   settle policy visibility, and run controlled successful/rejected CI and stale-
   base race probes. Prove ordinary failed/cancelled/skipped code checks cannot
   pass, direct writes are denied, and the publisher has no exception. Do not use
   this stage as authorization for another official benchmark.
5. Pause publication for cutover, let a running legacy publisher finish safely,
   then apply the reviewed rules/configuration and connect the new path. Do not
   enable PR-required rules while expecting the legacy direct push to keep working,
   and do not toggle protection off around each publication. No automatic fallback
   to direct main writes is allowed after switching.
6. Run a separately authorized real official measurement/publication. Confirm
   complete CI, the returned squash SHA's sole measured-source parent and audited
   tree, existing Pages outputs/direct dependency, live served bytes and preserved
   history. Result-only push routing must not create a second deployment. Record
   source, candidate, PR, CI run/attempt, merged publication and Pages identities
   separately. Only then assess closure of #52 and #59's remaining real-run proof.

## Failure classification and recovery

`ResultPRFailure.code` separates `invalid_candidate`, `invalid_pr`, `invalid_ci`,
`ci_pending`, `ci_rejected`, `policy_unverified`, `stale_main` and `invalid_merge`.
The messages contain no arbitrary API response body or token. The pure verifier
performs no transport, so it does not pretend to classify HTTP/authentication
failures; the future API boundary must distinguish those separately.

A pending CI produces no merge plan; a rejected or incomplete inventory cannot be
replaced by one successful job. On stale main, preserve evidence and the current
public result, do not rebase/force/relabel the old measurement, and arrange a
separately authorized latest-main run when a new result is actually needed.

After a lost merge response, `reconcile_publication` requires fresh PR/commit
reads and the original rebuilt candidate. A matching merged transaction returns
its **actual** squash SHA, which may differ from the proposal SHA. Main advancing
after that valid merge does not change its identity; the existing Pages stale-main
check can refuse deployment independently. An open or closed-unmerged PR is not
success. Reconciliation does not issue another merge or delete anything.

For already-published-but-Pages-failed cases, use the existing
[Pages recovery procedure](AUTOMATION.md#github-pages), not another measurement or
product release. For rollout rollback, stop new publishing, preserve last verified
results/history, disable/revoke the new App as appropriate, and use a reviewed
code rollback plus the owner's saved targeted settings snapshot. Never weaken
unrelated rules, force a ref, or restore a legacy direct writer while PR-only
protection remains active.

## Verification

```bash
python -m unittest discover -s tests -p 'test_benchmark_publication_candidate.py' -v
python -m unittest discover -s tests -p 'test_benchmark_result_pr*.py' -v
python -O -m unittest discover -s tests -p 'test_benchmark_result_pr*.py' -v
make test-benchmark
```

Candidate tests use synthetic reports and real temporary Git repositories. API
preflight/reconciliation tests use synthetic snapshots; none is an official
measurement, a live rule probe or an API integration test. Existing full CI,
container acceptance, smoke and Axum diagnostics remain mandatory.

Primary references: [PR merge preconditions](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request),
[rules and policy visibility](https://docs.github.com/en/rest/repos/rules),
[Strict required checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets),
and [GITHUB_TOKEN event/approval behavior](https://docs.github.com/en/actions/concepts/security/github_token).
