---
name: releasing
description: Use when cutting, tagging, or publishing a release of eddn-tail - bumping the version, creating the release PR, tagging, or diagnosing a Release workflow run that failed, published the wrong version, or produced no PyPI upload or GitHub Release.
---

# Releasing

How to cut a release of eddn-tail. The version is `version` in `pyproject.toml` and nothing else
hardcodes it. Everything after the tag push is automated by `.github/workflows/release.yml`:
sdist + wheel to PyPI via trusted publishing, a GitHub Release, then one-file PyInstaller binaries
for Linux, macOS, and Windows attached to that Release.

## Quick reference

| Step | Command |
|---|---|
| Verify | `python3 -m pytest -q` · `ruff check .` |
| Branch | `git checkout -b <version>-release` |
| Bump | edit `version` in `pyproject.toml` |
| Commit | `git add pyproject.toml && git commit -m "chore: release v<version>"` |
| PR | `gh pr create --title "chore: release v<version>"` |
| Gate | Wait for the Build workflow to pass on the PR |
| Merge | Merge into `main` |
| Tag the merged commit | `git checkout main && git pull --ff-only && git tag v<version>` |
| Publish | `git push --tags` |

## Preconditions

- Every change intended for this release is already merged into `main`.
- `main` is pulled and the working tree is clean.
- `python3 -m pytest -q` and `ruff check .` both pass locally. CI re-runs the tests on 3.9 through
  3.13, so a version-specific failure can still surface there.
- The `release` environment exists on the repo with PyPI trusted publishing configured for the
  `eddn-tail` project. Without it the publish step fails at OIDC, after the tag exists.
- Nothing else needs bumping. `version` in `pyproject.toml` is the only place the number lives.

## Choosing the version

Semver `x.y.z`, judged from what has landed since the last tag (`git log v<previous>..main
--oneline`): breaking user-visible behaviour (a removed CLI flag, a changed keybinding, a dropped
Python version) is major, new flags or UI features are minor, fixes only are patch.

The tag pattern in `release.yml` is `v[0-9]+.[0-9]+.[0-9]+`, so pre-release and suffixed tags
(`v1.0.0rc1`, `v1.0.0-beta`) do not trigger anything at all. There is no pre-release path today.

## Cutting the release

1. Branch off up-to-date `main`: `git checkout -b <version>-release`.

2. Edit `version` in `pyproject.toml`. Change nothing else in the commit.

3. Commit: `git add pyproject.toml && git commit -m "chore: release v<version>"`.

4. Open the PR (`chore: release v<version>`). Body should state the version bump, a one-line
   summary of what is in the release, and the local verification results.

   **Wait for the Build workflow to go green before merging.** `.github/workflows/build.yml` runs
   pytest on Python 3.9 to 3.13 and ruff on 3.13 for every PR to `main`. It is the only automated
   gate before the tag, and it does not exercise the release path at all: it never runs
   `python -m build`, never touches PyPI, and never runs PyInstaller. A packaging break passes
   Build clean and only surfaces after the tag is pushed.

   Direct-to-main is possible but gives up the gate - Build then runs after the push, so a red
   result arrives with the commit already on `main`.

5. Merge. If you squash, the branch commit is discarded, so tag the commit that actually lands on
   `main`, not the branch. Nothing enforces this: a tag on any commit will build and publish.
   Let Build go green on the merge push before tagging.

## Publishing

```
git checkout main && git pull --ff-only
git tag v<version>
git push --tags
```

`git push` alone does not push tags. Without `--tags` nothing runs and there is no failure to see.

The tag triggers `release.yml`, which builds the sdist and wheel, publishes to PyPI, creates the
GitHub Release with **auto-generated notes from commit subjects**, then runs the `pyinstaller` job
(`needs: release`) to attach the three binaries. Because the notes come from commit subjects,
sloppy subjects since the last tag become the public release notes; skim
`git log v<previous>..main --oneline` before tagging and be ready to edit the notes afterwards with
`gh release edit`.

Watch the run: `gh run watch` or `gh run list --workflow=release.yml`.

## Verifying

The wheel and the binaries come from two independent build paths that share only the source: the
wheel is `python -m build` in the `release` job, the binaries are a separate `pip install .` plus
PyInstaller in the `pyinstaller` job. A working binary is not evidence the wheel is good, and a
successful PyPI upload is not evidence the binaries are good - a packaging error affecting only one
path (a hatchling include/exclude mistake in the wheel, say) leaves the other looking fine. Check
both.

- `gh release view v<version>` - notes read sensibly, and three binaries are attached
  (`eddn-tail-linux`, `eddn-tail-macos`, `eddn-tail-windows.exe`). The binaries come from the
  second job, so a Release with no binaries means `pyinstaller` failed after the PyPI upload
  already succeeded.
- Wheel: `pip install eddn-tail==<version>` in a throwaway venv, then `eddn-tail --help`. This
  covers the wheel only, not the binaries.
- Binary: download the one for your platform from the Release and run `--help` on it (`chmod +x`
  first on Linux/macOS). A one-file PyInstaller binary missing a bundled dependency typically dies
  on import at startup, so this catches that. You can only check the platform you're on; the other
  two stay unverified by a human.
- The PyPI project page shows `<version>` as the current release.
- Nothing in CI checks that the tag matches `pyproject.toml`, so confirm by eye that the published
  version is the one you meant.

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

**Run failed after PyPI but before or during the GitHub Release / binaries.** The number is spent.
Do not retag: anyone who fetched the tag keeps the old commit, and a moved tag is worse than a
skipped number. Re-running the workflow is safe for the PyPI step specifically, because
`skip-existing: true` makes a duplicate upload a no-op - but see the trap below.

**Uncertain how far it got:** check the PyPI project page first, then `gh release view v<version>`.
PyPI is the irreversible half, so it decides whether the number is spent.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Tagging without bumping `pyproject.toml` | Not caught - no guard compares the tag to the version. The wheel publishes under the *old* version, and with `skip-existing: true` the run goes green having uploaded nothing |
| Re-tagging after a failed release, assuming the retry republishes | Not caught - `skip-existing: true` means an already-present version is skipped silently and the run is green. Always confirm the PyPI page, not the workflow status |
| Tagging on the release branch after a squash merge | Not caught - it builds and publishes from a commit that is not on `main` |
| A pre-release-style tag (`v1.0.0rc1`) | Not caught as a failure - the tag pattern simply does not match, so no workflow runs at all |
| Pushing with `git push` only | Not caught - tags are not pushed by default, so nothing runs |
| Merging the release PR on a red Build | Not caught - the same failure recurs on the tag, after the tag exists |
| Assuming Build validates packaging | Not caught - Build never runs `python -m build` or PyInstaller, so packaging breaks surface only post-tag |
| Untidy commit subjects since the last tag | Not caught - they become the release notes verbatim. Edit afterwards with `gh release edit --notes` |
| Creating the GitHub Release by hand, then pushing the tag | The workflow's `softprops/action-gh-release` step will overwrite it |

## Known gaps

These are unguarded today. If a release ever goes wrong in one of these ways, the durable fix is a
CI check, not more care:

- No tag-vs-`pyproject.toml` version check before the build.
- `skip-existing: true` turns "already published" into a silent green, which hides a botched retry.
- No changelog. Notes are generated from commit subjects, so note quality tracks commit hygiene.
- No CI smoke test that the PyInstaller binaries actually start - Verifying above covers this
  manually, and only for whichever platform the releaser is on.
