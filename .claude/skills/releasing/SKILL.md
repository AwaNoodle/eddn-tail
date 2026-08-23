---
name: releasing
description: Use when cutting, tagging, or publishing a release of eddn-tail - bumping the version, creating the release PR, tagging, or diagnosing a Release workflow run that failed, published the wrong version, or produced no PyPI upload or GitHub Release.
---

# Releasing

How to cut a release of eddn-tail. The version is `version` in `pyproject.toml` and nothing else
hardcodes it. **Releasing is triggered by merging the version bump to `main` - there is no manual
tag or push step.** `.github/workflows/release.yml` runs on every push to `main`, decides whether
the pushed commit represents an unreleased version, and if so does everything itself: creates and
pushes the `v<version>` tag, builds sdist + wheel, publishes to PyPI via trusted publishing, and
creates a GitHub Release with those two files attached. That is the whole distribution surface:
users install with `uvx eddn-tail`, `pip install eddn-tail`, or by running `eddn_tail.py` from a
checkout. No standalone binaries are built or shipped.

`release.yml` has two jobs. `check` runs on *every* push to `main`, unconditionally and ungated -
it reads `version` from `pyproject.toml` (`scripts/check_release_needed.py`) and checks whether tag
`v<version>` already exists. Most pushes are not releases, so this is meant to be cheap and to say
so plainly in the log ("`vX.Y.Z` already released, nothing to do"). Only when the tag does not yet
exist does the `release` job run. That job sits in the `release` GitHub environment, which pauses
for human approval before anything publishes (required reviewers on that environment - see
Preconditions). It then, in order: extracts the changelog section (fails before anything
irreversible if missing), creates and pushes the tag, builds, publishes to PyPI, and creates the
GitHub Release. `scripts/check_pypi_publish.py` reports in the job summary whether the run actually
uploaded the version or found it already there.

There used to be a step that verified the tag matched `pyproject.toml`'s version
(`scripts/check_release_version.py`). It is gone: the tag is now *derived* from the version rather
than pushed independently, so the two cannot disagree, and the check became a tautology.

## Quick reference

| Step | Command |
|---|---|
| Verify | `uv run --extra dev pytest -q` · `uv run --extra dev ruff check .` |
| Branch | `git checkout -b <version>-release` |
| Bump | edit `version` in `pyproject.toml` |
| Roll up changelog | rename `## [Unreleased]` to `## [<version>] - <date>` in `CHANGELOG.md`, add a fresh empty `## [Unreleased]` above it |
| Commit | `git add pyproject.toml CHANGELOG.md && git commit -m "chore: release v<version>"` |
| PR | `gh pr create --title "chore: release v<version>"` |
| Gate | Wait for the Build workflow to pass on the PR |
| Merge | Merge into `main` - this is what triggers the release |
| Approve | Approve the `release` environment deployment when prompted (required reviewer gate) |
| Watch | `gh run watch` on the `Release` workflow run triggered by the merge |

There is no tag or push step left to run by hand - merging the PR is the release trigger.

## Preconditions

- Every change intended for this release is already merged into `main`.
- `main` is pulled and the working tree is clean.
- `uv run --extra dev pytest -q` and `uv run --extra dev ruff check .` both pass locally. The build workflow
  re-runs the tests on 3.9 through 3.13, so a version-specific failure can still surface there.
- The `release` environment exists on the repo with PyPI trusted publishing configured for the
  `eddn-tail` project, and with required reviewers configured so the publish step pauses for human
  approval before it runs. Without trusted publishing, the publish step fails at OIDC, after the tag
  exists. Without a reviewer, the release job runs unattended the moment the merge lands.
- Nothing else needs bumping. `version` in `pyproject.toml` is the only place the number lives.
- `CHANGELOG.md` has something under `## [Unreleased]` to roll up. If it is empty, the changelog
  guard fails the release before it builds anything - after the merge, before the tag is created.

## Choosing the version

Semver `x.y.z`, judged from what has landed since the last tag (`git log v<previous>..main
--oneline`): breaking user-visible behaviour (a removed CLI flag, a changed keybinding, a dropped
Python version) is major, new flags or UI features are minor, fixes only are patch.

The tag `release.yml` creates is always `v<version>` straight from `pyproject.toml`, so there is no
separate tag pattern to match and no way for a tag to disagree with the version. There is no
pre-release path today - `check_release_needed.py` only ever compares against a plain `x.y.z`.

## Cutting the release

1. Branch off up-to-date `main`: `git checkout -b <version>-release`.

2. Edit `version` in `pyproject.toml`.

3. Roll up `CHANGELOG.md`: rename `## [Unreleased]` to `## [<version>] - <date>` and add a fresh
   empty `## [Unreleased]` above it. Write the entries in Keep a Changelog style, user-facing and
   brief - this section's body is what `release.yml` extracts verbatim as the GitHub Release notes,
   so it is read by users, not just contributors. A missing or empty section for the tagged version
   fails the release before it builds anything.

4. Commit: `git add pyproject.toml CHANGELOG.md && git commit -m "chore: release v<version>"`.

5. Open the PR (`chore: release v<version>`). Body should state the version bump, a one-line
   summary of what is in the release, and the local verification results.

   **Wait for the Build workflow to go green before merging.** `.github/workflows/build.yml` runs
   pytest on Python 3.9 to 3.13 and ruff on 3.13 for every PR to `main`. It is the only gate before
   the merge, and it does not exercise the release path at all: it never runs `uv build` and never
   touches PyPI. A packaging break passes Build clean and only surfaces after the merge, in the
   `release` job.

   There is no direct-to-main option worth taking here: `main` is protected, so every change,
   including this one, goes through a PR regardless.

6. Merge. **The merge push is what triggers the release** - `release.yml`'s `check` job runs
   immediately, sees that `v<version>` does not exist yet, and the gated `release` job starts.
   Unlike the old flow, there is no separate "tag the right commit" step to get wrong: the workflow
   tags whatever commit its own push event points at, which is by construction the commit that just
   landed on `main` - squash or merge commit, it doesn't matter, there's no branch commit to
   mis-tag.

## Publishing

Nothing to run by hand. Once the merge in step 6 lands:

1. The `check` job (ungated, runs on every push to `main`) reads `version` from `pyproject.toml`
   and finds `v<version>` does not exist yet (`scripts/check_release_needed.py`) - so the `release`
   job proceeds.
2. The `release` job sits in the `release` GitHub environment, which pauses for a required
   reviewer's approval before it runs anything. **Approve that deployment** (repo's Actions tab, or
   `gh run watch` will surface it) to let the release proceed.
3. Extracts the `## [<version>]` section from `CHANGELOG.md` (`scripts/extract_changelog.py`) -
   fails in seconds if that section is missing or empty, before the tag is created.
4. Creates and pushes the `v<version>` tag.
5. Builds the sdist and wheel (`uv build`).
6. Publishes to PyPI (`skip-existing: true`, so a retry of a partially-failed release is not a hard
   error), then runs `scripts/check_pypi_publish.py`, which polls PyPI's JSON API (cache-busted,
   up to ~80s) until the version appears, and reports in the job summary whether this run actually
   uploaded the version or found it already there. The poll exists because PyPI's API is served
   through a CDN and does not reflect a fresh upload instantly - a single read right after
   publishing can wrongly say "not there yet".
7. Creates the GitHub Release, attaching the sdist and wheel (`files: dist/*`), using the extracted
   changelog section as the release body - no more auto-generated notes from commit subjects.

Watch the run: `gh run watch` or `gh run list --workflow=release.yml`. The job summary is the
fastest way to see whether PyPI actually got a new upload. A push to `main` that is not a version
bump also triggers this workflow, but only the cheap `check` job runs for it - look for
"`vX.Y.Z` already released, nothing to do" in its log and move on.

## Verifying

- `gh release view v<version>` - notes read sensibly, and the sdist and wheel are attached.
- `uvx eddn-tail@<version> --help` in a clean shell, or `pip install eddn-tail==<version>` in a
  throwaway venv followed by `eddn-tail --help`. This is the install path users actually take, and
  it is the only check that the published wheel is importable and its entry point resolves.
- The PyPI project page shows `<version>` as the current release.
- The job summary for the release run states plainly whether it published `<version>` or found it
  already on PyPI (see Recovery below) - check it before assuming a green run means an upload
  happened.

## Recovery

**A version published to PyPI is spent.** PyPI does not allow re-uploading a filename, even after
deletion. Fix forward with the next patch version. If the bad release is actively harmful, yank it
on the PyPI web UI (yanking hides it from resolution while leaving existing pins working) and
optionally mark the GitHub Release as a pre-release: `gh release edit v<version> --prerelease`.

**Run failed before the tag was created** (changelog guard, or the environment approval was
rejected). Nothing happened at all - no tag, nothing published. Fix the cause (e.g. a changelog
edit) on a new PR and merge again; the `check` job will still see `v<version>` missing and retry
the whole flow.

**Run failed after the tag was created but before or during the PyPI publish step** (build error,
OIDC failure). Nothing was published, so the number is still reusable, but the tag now exists on
the remote and must go before re-running, or `check` will wrongly report "already released":

```
git push --delete origin v<version>
git tag -d v<version>
```

Then either re-run the failed workflow run (`gh run rerun <run-id>`, which re-executes from `check`
and will now find the tag absent again and proceed), or push a trivial commit to `main` to trigger
a fresh run.

**Run failed after PyPI but before or during the GitHub Release.** The number is spent, and the tag
exists and must stay - do not delete it, and do not retag: anyone who fetched the tag keeps the
same commit, and a moved tag is worse than a skipped number. Re-running the workflow
(`gh run rerun <run-id>`) is safe: `check` sees the tag already exists, so `release_needed` is
`false` and the `release` job (including the tag-creation step) is skipped entirely - this re-run
will *not* retry the PyPI publish or the GitHub Release. If the GitHub Release itself is what's
missing, create it by hand (`gh release create v<version> dist/* --notes-file release_notes.md`
from a local build) rather than expecting a re-run to finish the job; `skip-existing: true` only
covers the PyPI step being safe to repeat, not the workflow re-attempting steps after a run that
already exited via the "already released" path.

**Uncertain how far it got:** check the job summary for the run first - it states whether PyPI got
a new upload or already had the version - then the PyPI project page, then
`gh release view v<version>`. PyPI is the irreversible half, so it decides whether the number is
spent.

**The "Verify PyPI publish outcome" step itself failed (the run is red at or after that step).**
This does not necessarily mean the publish failed - it means the version did not show up in PyPI's
JSON API within the poll window (~80s), which can happen either because the publish genuinely
failed or because PyPI's CDN was slower than that to catch up. Before treating the version as spent
and moving to the next patch number, check `https://pypi.org/project/eddn-tail/` by hand: if
`<version>` is there, the publish worked and only the visibility check was slow - the tag and PyPI
upload both exist, so there is nothing to retry, just create the GitHub Release by hand if it's
missing (see above); if it is genuinely not there, treat it as the "run failed after the tag was
created" case above (delete the tag, fix forward) since PyPI itself was never actually populated.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Bumping `pyproject.toml` without a matching `CHANGELOG.md` section | Caught by the release workflow after merge - `scripts/extract_changelog.py` fails within seconds if the `## [<version>]` section is missing or empty, before the tag is created |
| Assuming a re-run retries a stuck PyPI publish | Not automatic - once the tag exists, `check` reports `release_needed: false` and the whole `release` job (including publish) is skipped on any later run. See Recovery above for the manual path |
| Merging the release PR on a red Build | Not caught - the same failure recurs in the `release` job, after the merge |
| Assuming Build validates packaging | Not caught - Build never runs `uv build`, so packaging breaks surface only post-merge, in `release.yml` |
| Not approving the `release` environment deployment | The `release` job sits waiting indefinitely; nothing times out on its own |
| Creating the GitHub Release by hand before the workflow runs | The workflow's `softprops/action-gh-release` step will overwrite it |
| Pushing a non-release commit to `main` and expecting nothing to happen | Correct expectation, but confirm it in the log: `check` still runs (cheap, ungated) and should report "already released, nothing to do" |

## Known gaps

These are unguarded today. If a release ever goes wrong in one of these ways, the durable fix is a
a check in the release workflow, not more care:

- No automated smoke test that the published wheel installs and runs - Verifying above covers this
  manually, after the fact.
- `scripts/check_pypi_publish.py` depends on the public `https://pypi.org/pypi/<project>/json`
  endpoint. It polls for ~80s to ride out CDN lag, but a longer outage there still fails the whole
  run even if the actual PyPI publish succeeded.
- The changelog guard only checks that the `## [<version>]` section exists and is non-empty, not
  that its content is accurate or well-written. Garbage in the changelog still ships as the release
  notes verbatim.
- `check`'s tag-existence check is intentionally the *only* signal for "already released" - it does
  not check PyPI or GitHub Releases. If the tag was created but a later step failed, a re-run takes
  the quiet "already released" path and does not retry that later step (see Recovery). This is
  deliberate - re-running must not silently repeat a tag push - but it means recovery from a
  post-tag failure is manual.
