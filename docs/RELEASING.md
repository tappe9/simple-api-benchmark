# Maintainer product release procedure

Product releases, verified benchmark result publication and Pages deployment are
three separate operations. Neither `pages.yml` nor `pages-deploy.yml` creates or
looks up releases. Routine Pages has no `contents: write` permission. Official
result publication retains its existing audited publisher; it does not choose a
product version. No release workflow or additional credential is introduced.

The existing **v0.1.0** release is the original four-stack snapshot. Preserve its
tag at `962e1454e51d60d4e24cddd9126e4d6b35b80716` and release ID `384397012` unchanged.
Current `main` is not a claim that these later changes are part of v0.1.0. Never
move, delete or recreate a published tag/release to repair documentation or Pages.

## 1. Choose the version and immutable source

This is a manual procedure for an explicitly approved **new** release, not a
command to run after every merge. The maintainer chooses the version, target
40-character commit SHA, release notes, prerelease status and whether to mark it
Latest. No next version is prescribed here. Use a reviewed commit reachable from
main whose full exact-SHA CI has succeeded, not an arbitrary workflow SHA.

Prerequisites: Bash, Git, authenticated GitHub CLI with write access to this
repository, and the pinned tools from [Contributing](../CONTRIBUTING.md). Use the
maintainer's existing authorized authentication; do not add a PAT/App secret to
Pages, widen workflow permissions, or change repository protection for this step.

Set `RELEASE_TAG`, `RELEASE_SHA`, `RELEASE_NOTES` (a nonempty local notes file), and
`CI_RUN_ID` (the successful main push CI for that exact SHA) deliberately in the
same shell. The following commands do not choose defaults for those values:

```bash
set -euo pipefail
REPO=tappe9/simple-api-benchmark
REMOTE="https://github.com/$REPO.git"
: "${RELEASE_TAG:?Set the approved new version tag}"
: "${RELEASE_SHA:?Set the reviewed full commit SHA}"
: "${RELEASE_NOTES:?Set the release notes file path}"
: "${CI_RUN_ID:?Set the exact-SHA main push CI run ID}"
[[ "$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$CI_RUN_ID" =~ ^[0-9]+$ ]]
test "$RELEASE_TAG" != v0.1.0
test -s "$RELEASE_NOTES"
test -z "$(git status --porcelain)"
gh auth status
gh api "repos/$REPO" --jq '{full_name, permissions}'
git fetch --no-tags "$REMOTE" refs/heads/main
git cat-file -e "$RELEASE_SHA^{commit}"
git merge-base --is-ancestor "$RELEASE_SHA" FETCH_HEAD
```

The canonical remote prevents an unrelated local `origin` from receiving a tag.
The selected source must remain fixed throughout validation and release creation.
Do not change `RELEASE_SHA` just to match a failed or incomplete check.

## 2. Check existing releases and exact-source validation

```bash
remote_tags=$(git ls-remote --tags "$REMOTE" "refs/tags/$RELEASE_TAG" "refs/tags/$RELEASE_TAG^{}")
local_tags=$(git tag --list "$RELEASE_TAG")
test -z "$remote_tags"
test -z "$local_tags"
gh api --paginate "repos/$REPO/releases?per_page=100" \
  --jq '.[] | {id, tag_name, draft, target_commitish}'
gh api "repos/$REPO/actions/runs/$CI_RUN_ID" \
  --jq '{id, name, path, event, head_branch, head_sha, status, conclusion, run_attempt}'
gh api --paginate "repos/$REPO/actions/runs/$CI_RUN_ID/jobs?per_page=100" \
  --jq '.jobs[] | {name, head_sha, status, conclusion}'
```

Review this output before the write commands below. The authenticated release
listing must succeed and contain no published **or draft** release with the chosen
tag. Any API, authentication or network error is a stop condition, not evidence
that a release is missing. Never use `if ! gh release view ...; then create ...`
as a fallback. An existing tag/release requires investigation, not replacement.

Confirm the CI belongs to this repository's `CI` / `.github/workflows/ci.yml`, is a
main `push`, and has exactly `RELEASE_SHA` as its head. The run and all required
jobs must be completed successfully, including the full implementation matrix,
shared checks, smoke and the stable `required` aggregate. A failed, cancelled,
missing or unexpectedly skipped job does not qualify. PR CI on another head,
a green Pages build, or one successful implementation is insufficient. A
generated-results commit with no exact-source CI does not qualify automatically;
select a separately validated code commit rather than bypassing the gate.

Validate the clean source locally with all pinned prerequisites:

```bash
git switch --detach "$RELEASE_SHA"
make test
python -m benchmark.generate_readme --check
git diff --check
test -z "$(git status --porcelain)"
```

`make test` includes non-publishing smoke and Axum diagnostics, not a new official
publication. Preserve the measured source/run identity inside existing reports;
it can legitimately precede the release source. Do not hand-edit generated values,
relabel old measurements, or run an official benchmark merely to create a release.
Review notes for changes, compatibility, limitations and links to completed work.

## 3. Push one new tag and create a draft

**These are explicit write operations.** Proceed only after the preceding review
and maintainer approval. Recheck remote tags and releases immediately before this
step if time has passed. Do not reuse v0.1.0 or force any tag update.

```bash
test "$(git rev-parse HEAD)" = "$RELEASE_SHA"
git tag -a -m "Release $RELEASE_TAG" -- "$RELEASE_TAG" "$RELEASE_SHA"
git push "$REMOTE" "refs/tags/$RELEASE_TAG:refs/tags/$RELEASE_TAG"
git fetch --no-tags "$REMOTE" "refs/tags/$RELEASE_TAG"
test "$(git rev-parse 'FETCH_HEAD^{commit}')" = "$RELEASE_SHA"
gh release create "$RELEASE_TAG" --repo "$REPO" --verify-tag --draft \
  --title "$RELEASE_TAG" --notes-file "$RELEASE_NOTES"
gh release view "$RELEASE_TAG" --repo "$REPO" \
  --json databaseId,tagName,targetCommitish,isDraft,isPrerelease,body,url
```

`--verify-tag` prevents GitHub CLI from silently creating a tag at the latest
main. The peeled remote tag is the source authority; `targetCommitish` alone is
not proof of the existing tag's target. No release assets are required for this
repository's source release. Review any proposed assets separately before upload.

## 4. Review, publish and record evidence

Open the draft in GitHub and verify the tag target, notes, intended prerelease and
Latest choices. Publish only that approved draft. For example, after approving a
release that should **not** replace Latest:

```bash
gh release edit "$RELEASE_TAG" --repo "$REPO" --verify-tag --draft=false --latest=false
gh release view "$RELEASE_TAG" --repo "$REPO" \
  --json databaseId,tagName,targetCommitish,isDraft,isPrerelease,publishedAt,url
git ls-remote --tags "$REMOTE" "refs/tags/$RELEASE_TAG" "refs/tags/$RELEASE_TAG^{}"
```

Use the GitHub draft controls for the separately chosen prerelease/Latest policy;
do not infer it from a version string. Record the published release ID/URL, exact
peeled tag SHA, CI run/attempt and approved notes in the release tracking issue.
No Pages deployment is needed to publish the release, and no product release is
needed to deploy Pages. Existing results and all historical identities stay intact.

## Failure and recovery

If tag push or release creation fails, stop and re-read remote state with working
authentication. A lost response might follow a successful write. Keep any new tag
or draft while reconciling its identity; do not blindly repeat creation, retarget,
force-push, delete or recreate published objects. After publication, fixes use a
new explicitly chosen version. Pages failures use the independent
[Pages recovery procedure](AUTOMATION.md#github-pages), never release recreation.

References: [GitHub CLI release creation](https://cli.github.com/manual/gh_release_create),
[editing and publishing drafts](https://cli.github.com/manual/gh_release_edit),
and [GitHub release permissions and API](https://docs.github.com/en/rest/releases/releases).
