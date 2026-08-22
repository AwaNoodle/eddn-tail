---
name: releasing
description: Use when cutting, tagging, or publishing a release of eddn-tail - bumping the version, creating the release PR, tagging, or diagnosing a Release workflow run that failed, published the wrong version, or produced no PyPI upload or GitHub Release.
---

# Releasing

How to cut a release of eddn-tail. The version is `version` in `pyproject.toml` and nothing else
hardcodes it. Everything after the tag push is automated by `.github/workflows/release.yml`:
guard checks, then sdist + wheel to PyPI via trusted publishing, then a GitHub Release with those
two files attached. That is the whole distribution surface: users install with `uvx eddn-tail`,
`pip install eddn-tail`, or by running `eddn_tail.py` from a checkout. No standalone binaries are
built or shipped.

Before anything is built, `release.yml` runs two guard steps (`scripts/check_release_version.py`
and `scripts/extract_changelog.py`) that fail the run in seconds if the tag does not match
`pyproject.toml`'s version, or if `CHANGELOG.md` has no non-empty `## [<version>]` section for the
tag. After publishing to PyPI, `scripts/check_pypi_publish.py` reports in the job summary whether
this run actually uploaded the version or found it already there.

## Quick reference

| Step | Command |
|---|---|
| Verify | `python3 -m pytest -q` · `ruff check .` |
| Branch | `git checkout -b <version>-release` |
| Bump | edit `version` in `pyproject.toml` |
| Roll up changelog | rename `## [Unreleased]` to `## [<version>] - <date>` in `CHANGELOG.md`, add a fresh empty `## [Unreleased]` above it |
| Commit | `git add pyproject.toml CHANGELOG.md && git commit -m "chore: release v<version>"` |
| PR | `gh pr create --title "chore: release v<version>"` |
| Gate | Wait for the Build workflow to pass on the PR |
| Merge | Merge into `main` |
| Tag the merged commit | `git checkout main && git pull --ff-only && git tag v<version>` |
| Publish | `git push --tags` |

## Preconditions

- Every change intended for this release is already merged into `main`.
- `main` is pulled and the working tree is clean.
- `python3 -m pytest -q` and `ruff check .` both pass locally. The build workflow re-runs the tests on 3.9 through
  3.13, so a version-specific failure can still surface there.
- The `release` environment exists on the repo with PyPI trusted publishing configured for the
  `eddn-tail` project. Without it the publish step fails at OIDC, after the tag exists.
- Nothing else needs bumping. `version` in `pyproject.toml` is the only place the number lives.
- `CHANGELOG.md` has something under `## [Unreleased]` to roll up. If it is empty, the changelog
  guard fails the release before it builds anything.

## Choosing the version

Semver `x.y.z`, judged from what has landed since the last tag (`git log v<previous>..main
--oneline`): breaking user-visible behaviour (a removed CLI flag, a changed keybinding, a dropped
Python version) is major, new flags or UI features are minor, fixes only are patch.

The tag pattern in `release.yml` is `v[0-9]+.[0-9]+.[0-9]+`, so pre-release and suffixed tags
(`v1.0.0rc1`, `v1.0.0-beta`) do not trigger anything at all. There is no pre-release path today.

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
   pytest on Python 3.9 to 3.13 and ruff on 3.13 for every PR to `main`. It is the only automated
   gate before the tag, and it does not exercise the release path at all: it never runs
   `python -m build` and never touches PyPI. A packaging break passes
   Build clean and only surfaces after the tag is pushed.

   Direct-to-main is possible but gives up the gate - Build then runs after the push, so a red
   result arrives with the commit already on `main`.

6. Merge. If you squash, the branch commit is discarded, so tag the commit that actually lands on
   `main`, not the branch. Nothing enforces this: a tag on any commit will build and publish.
   Let Build go green on the merge push before tagging.

## Publishing

```
git checkout main && git pull --ff-only
git tag v<version>
git push --tags
```

`git push` alone does not push tags. Without `--tags` nothing runs and there is no failure to see.

The tag triggers `release.yml`, which:

1. Verifies the tag matches `pyproject.toml`'s version (`scripts/check_release_version.py`) -
   fails in seconds if not, before anything builds.
2. Extracts the `## [<version>]` section from `CHANGELOG.md` (`scripts/extract_changelog.py`) -
   fails in seconds if that section is missing or empty.
3. Builds the sdist and wheel.
4. Publishes to PyPI (`skip-existing: true`, so a retry of a partially-failed release is not a hard
   error), then runs `scripts/check_pypi_publish.py`, which polls PyPI's JSON API (cache-busted,
   up to ~80s) until the version appears, and reports in the job summary whether this run actually
   uploaded the version or found it already there. The poll exists because PyPI's API is served
   through a CDN and does not reflect a fresh upload instantly - a single read right after
   publishing can wrongly say "not there yet".
5. Creates the GitHub Release, attaching the sdist and wheel (`files: dist/*`), using the extracted
   changelog section as the release body - no more auto-generated notes from commit subjects.

Watch the run: `gh run watch` or `gh run list --workflow=release.yml`. The job summary is the
fastest way to see whether PyPI actually got a new upload.

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

**Run failed before the PyPI publish step** (build error, OIDC or environment-approval failure).
Nothing was published, so the number is still reusable:

```
git push --delete origin v<version>
git tag -d v<version>
```

Fix the cause on a new PR, merge, then tag and push again.

**Run failed after PyPI but before or during the GitHub Release.** The number is spent.
Do not retag: anyone who fetched the tag keeps the old commit, and a moved tag is worse than a
skipped number. Re-running the workflow is safe for the PyPI step specifically, because
`skip-existing: true` makes a duplicate upload a no-op, and the re-run's job summary will say
`<version>` already existed and nothing new was uploaded, so you can tell at a glance that this run
did not publish anything - it is just letting the rest of the workflow (GitHub Release) complete.

**Uncertain how far it got:** check the job summary for the run first - it states whether PyPI got
a new upload or already had the version - then the PyPI project page, then
`gh release view v<version>`. PyPI is the irreversible half, so it decides whether the number is
spent.

**The "Verify PyPI publish outcome" step itself failed (the run is red at or after that step).**
This does not necessarily mean the publish failed - it means the version did not show up in PyPI's
JSON API within the poll window (~80s), which can happen either because the publish genuinely
failed or because PyPI's CDN was slower than that to catch up. Before treating the version as spent
and moving to the next patch number, check
`https://pypi.org/project/eddn-tail/` by hand: if `<version>` is there, the publish worked and only
the visibility check was slow - re-running the workflow is safe (`skip-existing: true` makes the
publish step a no-op, and the summary will correctly say "already existed"); if it is genuinely not
there, treat it as the "run failed after PyPI" case above and fix forward with the next version.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Tagging without bumping `pyproject.toml` | Caught by the release workflow - `scripts/check_release_version.py` compares the tag to `pyproject.toml`'s version and fails within seconds, before anything builds or publishes |
| Re-tagging after a failed release, assuming the retry republishes | Still not a hard failure by design (a legitimate retry must succeed), but no longer silent - `scripts/check_pypi_publish.py` reports "published" vs "already existed, nothing uploaded" in the job summary, so you no longer have to guess |
| Tagging on the release branch after a squash merge | Not caught - it builds and publishes from a commit that is not on `main` |
| A pre-release-style tag (`v1.0.0rc1`) | Not caught as a failure - the tag pattern simply does not match, so no workflow runs at all |
| Pushing with `git push` only | Not caught - tags are not pushed by default, so nothing runs |
| Merging the release PR on a red Build | Not caught - the same failure recurs on the tag, after the tag exists |
| Assuming Build validates packaging | Not caught - Build never runs `python -m build`, so packaging breaks surface only post-tag |
| Forgetting to roll up `CHANGELOG.md` before tagging | Caught by the release workflow - `scripts/extract_changelog.py` fails within seconds if the `## [<version>]` section is missing or empty. It does not judge the *quality* of the entry, only that one exists |
| Creating the GitHub Release by hand, then pushing the tag | The workflow's `softprops/action-gh-release` step will overwrite it |

## Known gaps

These are unguarded today. If a release ever goes wrong in one of these ways, the durable fix is a
a check in the release workflow, not more care:

- Tagging a commit that is not on `main` (e.g. the release branch after a squash merge) still
  builds and publishes from it. No guard checks the tag's ancestry.
- A pre-release-style tag (`v1.0.0rc1`) does not trigger the workflow at all, silently.
- No automated smoke test that the published wheel installs and runs - Verifying above covers this
  manually, after the fact.
- `scripts/check_pypi_publish.py` depends on the public `https://pypi.org/pypi/<project>/json`
  endpoint. A transient failure or outage there fails the whole run even if the actual PyPI publish
  succeeded - it does not retry.
- The changelog guard only checks that the `## [<version>]` section exists and is non-empty, not
  that its content is accurate or well-written. Garbage in the changelog still ships as the release
  notes verbatim.
