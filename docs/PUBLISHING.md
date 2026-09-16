# Protected result-PR publishing

Status: **preparation code, not an activated or live-validated policy** (Issue #52).
The maintainer approved the result-only PR / dedicated no-bypass App design on
September 16, 2026. This preparation does not authorize creating an App, storing
credentials, applying rules or starting a new official measurement/publication.

## Controller and rollout modes

`RESULT_PUBLICATION_MODE` is a repository variable. Unset/empty or `legacy` retains
the existing direct, audited fast-forward publisher during preparation. Unknown
values fail before measurement. The selected mode is frozen as a measurement-job
output; it is not reinterpreted differently by each downstream job.

`pull-request-v1` selects this chain inside the trusted `benchmark.yml` run:

```text
measure -> propose -> wait (read-only) -> merge -> existing reusable Pages call
```

PR mode additionally requires `RESULT_PR_ROLLOUT_APPROVED=strict-main-v1` and
`RESULT_PR_RULESET_ID` identifying the approved active main ruleset. The approval
value is an operator acknowledgement of the tests below, **not evidence itself**.
Do not set it until the real policy and App tests have passed. Removing it stops
PR-mode work; an unknown/missing mode acknowledgement never enables direct-push
fallback. Keep explicit `pull-request-v1` set after cutover: clearing the mode
would select the pre-cutover legacy route, not a supported emergency recovery.

The new path builds exactly the existing transaction: README English/Japanese
result sections, latest JSON, one new history JSON and three SVG charts. Source,
source tree, original measurement run/attempt, candidate SHA/tree and PR identity
are re-derived from the original audited raw artifact in each job. Generation is
deterministic across retries and does not move a branch or change the worktree.
The candidate contains no CI-skip directive. The unfiltered `pull_request` trigger
runs the full normal CI; the existing generated-path exclusions avoid a duplicate
push-CI presentation route after merge. PR CI cannot deploy Pages.

Only the trusted measured-source checkout runs controller code. No PR checkout,
PR-provided executable, workflow, label or bot display name authorizes a write.
The existing raw/report/path/README/chart validation is reused, not replaced by
an allowlist of filenames alone. The REST client uses a fixed repository/host,
bounded JSON and pagination, no HTTP redirects, and no blind write retries.

### Complete validation before the one main write

The controller requires the exact current PR head, same repository, one audited
commit, intended main base, full exact-head PR CI and the complete registry-derived
job set. Every run/job/check must literally be completed/success. The `required`
check must come from GitHub Actions app 15368 and the corresponding CI check suite.
The newest CI run is authoritative; an older success cannot replace a newer
failure or incomplete attempt. An explicit attempt-specific jobs endpoint prevents
mixing evidence from CI reruns. The full eight-implementation CI, smoke, Axum
and existing always-running aggregate remain mandatory.

Main must still equal the measured source. The final merge calls only the normal
REST squash merge endpoint with the expected head SHA. It does not enable native
auto-merge or merge arbitrary code PRs. After success it verifies the actual merge
SHA has exactly the audited tree and the measured source as its sole parent, then
passes that actual SHA to the unchanged Pages verifier. Main advancing after a
valid publication can safely reject a stale Pages deployment.

**The head-SHA merge precondition is not a base-SHA compare-and-swap.** Strict,
no-bypass branch enforcement is what must reject a base advancement occurring
after the last read. Local Git + fake-service tests model this response but do
not prove GitHub's behavior. A real controlled stale-base race test with this App
and effective rules is a blocking prerequisite for activation. A post-merge
parent mismatch is an integrity incident detected after a write, not a substitute
for server-side rejection; stop and preserve evidence, never rewrite main.

## App and environment setup (owner administration; not performed)

Register a maintainer-owned GitHub App and install it only on
`tappe9/simple-api-benchmark`. Grant **Contents: write** and **Pull requests: write**,
with Metadata read. Do not grant Administration, Workflows, Checks write, Statuses
write, or bypass access. The separate `GITHUB_TOKEN` in controller jobs has only
the read capabilities needed to inspect PRs, CI and public metadata.

Create the `benchmark-publisher` Environment with selected deployment branches:
branch `main` only. Do not allow all branches, PR refs, wildcard branches, or tags
named main. Review who can change these restrictions. Set:

| Location | Name | Purpose |
| --- | --- | --- |
| Environment variable | `RESULT_PUBLISHER_CLIENT_ID` | Dedicated App's client ID |
| Environment secret | `RESULT_PUBLISHER_PRIVATE_KEY` | App key; never paste into chat or source |
| Repository variable | `RESULT_PR_RULESET_ID` | Approved ruleset's numeric ID |
| Repository variable | `RESULT_PR_ROLLOUT_APPROVED` | `strict-main-v1`, only after live prerequisite tests |
| Repository variable | `RESULT_PUBLICATION_MODE` | `pull-request-v1`, set last during paused cutover |

Only `propose` and `merge` request that Environment and mint installation tokens.
The SHA-pinned `actions/create-github-app-token` is explicitly restricted to this
repository and the two write permissions. Tokens are distinct for the two jobs;
normal action post-cleanup revokes each token (`skip-token-revoke: false`). A hard
runner termination can prevent cleanup, so the installation token's one-hour
expiry is still relevant. No token is an output to a later job or an artifact.
The wait job has no App/private-key access and polls within a bounded job timeout.
Measurement, PR CI and Pages never receive the App key or publisher token.

GitHub's current `GITHUB_TOKEN`-created PR behavior can produce approval-required
CI runs. App installation tokens are the documented unattended alternative;
we do not rely on pretending an internally dispatched check is PR CI.

## Effective policy and visibility

`main-ruleset.json` is a **disabled** template, not an applied setting. It targets
only `refs/heads/main`, requires PRs and strict `required` from app 15368, permits
only squash, requires resolved conversations, blocks deletion/force push and has
an empty bypass list. Zero required approving reviews deliberately preserves the
owner-authored/self-review workflow; it does not remove CI or ordinary code review.
Native auto-merge need not be enabled.

Before changing anything, an authorized owner must inventory branch protection,
repository/inherited rulesets, Actions settings, Environment restrictions and the
App installation permissions. Preserve a private settings snapshot for rollback.
A 403 or unsupported connector endpoint is an inventory gap, never empty settings.
The ChatGPT connector cannot perform Administration API operations; repository
metadata showing owner/admin status does not grant that integration this access.
Do not work around an access denial with a temporary workflow or broader token.

The controller re-reads public effective main rules and verifies the configured
ruleset, strict check policy, conversation policy, squash, deletion and force-push
rules before proposing/merging. GitHub only returns `bypass_actors` to callers with
write access to the ruleset. Its absence must **not** be interpreted as an empty
bypass list. Consequently no-bypass, Environment restrictions and administrative
changes remain an explicitly owner-audited trust boundary. No Administration
permission is added to the App merely to hide this limitation.

## Staged validation and cutover

1. Review this code and its full CI. No live mode variables or settings are
   applied by this preparation PR. Do not close #52 after just merging code.
2. With owner access, record the current settings, configure the limited App and
   main-only Environment, and create/review the disabled template. Keep normal
   publication paused for cutover and drain any in-flight legacy official run.
3. In an explicitly authorized controlled test scope, use the same effective
   rules and publisher App to prove ordinary checked code merges and valid
   result-shaped PR merges work; direct writes, force/deletion and failed,
   cancelled, skipped/neutral or missing required CI cannot bypass the policy.
   Exercise stale base before merge **and between final read and merge request**,
   using unrelated code changes to ensure freshness, not conflicts, causes refusal.
   Record exact branches, rules, actors, heads/bases, responses, runs and attempts.
   Synthetic benchmark fixtures remain confined to test repositories/refs and
   must never enter official results or Pages.
4. Apply the reviewed main policy with no bypass only after prerequisite tests
   and explicit approval. Verify effective rules and blocked direct writes using
   that same App. Verify source/CI/controller files are the approved revision.
   Set the rule ID and acknowledgement, then select PR mode last. Do not unpause
   a legacy publisher under new rules or disable rules around individual runs.
5. Separately authorize one complete current-main official run. Verify proposal
   SHA/tree, full result-PR CI, sole-parent audited squash, immutable history,
   actual publication SHA, the direct dependent Pages deployment and public file
   bytes. Retain raw evidence; do not publish fabricated test metrics. This is
   also the remaining real producer/deployment proof for #59, not a claim made
   by unit tests. Leave #52/#59 open until their respective evidence is complete.

Do not activate automatic merging if the stale-base rejection test cannot be
proved. Keep the prior verified result visible and revise the controller/policy
with the maintainer instead of silently weakening provenance or granting bypass.

## Failure, reconciliation and rollback

| Outcome | Interpretation and recovery |
| --- | --- |
| Measurement failure | No candidate publication. Diagnose workload/container/cleanup evidence. |
| Invalid report/raw/manifest | No PR/main update. Investigate original evidence; never hand-fix metrics. |
| API 401/403 or transport/push error | Permission or transport problem, not missing history. Re-read remote state with authorized access. |
| CI failed/incomplete/timed out | No merge. Keep candidate/PR and investigate exact run/attempt. |
| Main advanced before/during merge | Safe stale-source refusal, not permission failure. Do not rebase or force; a fresh latest-main measurement requires separate authorization. |
| Lost branch/PR/merge response | Reconcile exact deterministic branch, PR head and merged commit; never duplicate blindly or fall back to direct push. |
| Published but outputs/Pages failed | The result already exists. Preserve it and use the existing Pages recovery; do not remeasure just to fix presentation. |
| Unexpected merged parent/tree | Integrity incident. Stop, record identities and investigate; do not rewrite or relabel the measurement. |

Deployment-only retries preserve the original measurement attempt from the
upstream output, not the retry's new `GITHUB_RUN_ATTEMPT`. Already-merged exact
transactions are reconciled by content/parent identity without a second write.
Closed-unmerged or externally changed result PRs are rejection conditions, not
permission to reopen/reset/delete them automatically. Result branches remain
available for investigation; automatic deletion is not required for correctness.

For rollback, pause new official runs first and preserve all published objects.
Revoke the new App installation/key as appropriate. Apply a reviewed code rollback
and only the targeted saved settings through owner administration. Do not weaken
unrelated rules or clear the mode as an automatic direct-push escape. An explicit
return to the legacy policy requires its own approved settings rollback. Prefer
keeping the last verified results and read-only Pages available during recovery.

## Primary references

- [PR merge API and expected head SHA](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)
- [Effective rules and restricted bypass visibility](https://docs.github.com/en/rest/repos/rules)
- [Strict branch freshness](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [GITHUB_TOKEN event behavior](https://docs.github.com/en/actions/concepts/security/github_token)
- [Scoped token action and revocation](https://github.com/actions/create-github-app-token/tree/bcd2ba49218906704ab6c1aa796996da409d3eb1)
- [Environment restrictions](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
