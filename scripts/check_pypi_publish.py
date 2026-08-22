#!/usr/bin/env python3
"""Make `skip-existing: true` publishes distinguishable from real ones.

`pypa/gh-action-pypi-publish` with `skip-existing: true` reports success both
when it uploads a new version and when the version was already on PyPI and it
skipped the upload. Both outcomes are needed (a retry of a partially-failed
release must not be a hard failure), but they must be visibly different to a
human reading the run.

Usage:
  check_pypi_publish.py pre <version>
      Records (via $GITHUB_ENV) whether <version> is already on PyPI before
      the publish step runs.

  check_pypi_publish.py post <version>
      Re-checks PyPI after the publish step and reports, via
      $GITHUB_STEP_SUMMARY and stdout, whether this run actually published
      <version> or found it already there. Fails if the version is still
      missing after the publish step (the publish silently did not work).

Project name is fixed to "eddn-tail"; pass a different one via
$PYPI_PROJECT_NAME if ever needed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PROJECT_NAME = os.environ.get("PYPI_PROJECT_NAME", "eddn-tail")
ENV_VAR = "PYPI_HAD_VERSION_BEFORE_PUBLISH"


def version_on_pypi(version: str) -> bool:
    url = f"https://pypi.org/pypi/{PROJECT_NAME}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Project itself has never been published.
            return False
        raise
    releases = data.get("releases", {})
    return version in releases and len(releases[version]) > 0


def write_github_env(name: str, value: str) -> None:
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        # Not running in GitHub Actions (e.g. local dry run); just print.
        print(f"{name}={value}")
        return
    with open(github_env, "a") as f:
        f.write(f"{name}={value}\n")


def write_summary(text: str) -> None:
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    print(text)
    if github_summary:
        with open(github_summary, "a") as f:
            f.write(text + "\n")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("pre", "post"):
        print("usage: check_pypi_publish.py <pre|post> <version>", file=sys.stderr)
        return 2

    mode, version = sys.argv[1], sys.argv[2]

    if mode == "pre":
        had_before = version_on_pypi(version)
        write_github_env(ENV_VAR, "true" if had_before else "false")
        print(
            f"Before publish: {version} "
            f"{'already exists' if had_before else 'is not yet'} on PyPI."
        )
        return 0

    # mode == "post"
    had_before = os.environ.get(ENV_VAR, "false") == "true"
    has_now = version_on_pypi(version)

    if not has_now:
        print(
            f"{version} is still not on PyPI after the publish step. "
            "The publish did not take effect.",
            file=sys.stderr,
        )
        return 1

    if had_before:
        write_summary(
            f"### PyPI publish: skipped\n\n"
            f"`{version}` already existed on PyPI before this run. "
            f"`skip-existing` left it untouched - **nothing new was uploaded**."
        )
    else:
        write_summary(
            f"### PyPI publish: published\n\n"
            f"`{version}` was uploaded to PyPI by this run."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
