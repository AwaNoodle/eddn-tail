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
      the publish step runs. A single cache-busted read; no retry needed
      since a stale "not present" here only mislabels a real publish as a
      skip in the summary, which is cosmetic, not a failure.

  check_pypi_publish.py post <version>
      Re-checks PyPI after the publish step and reports, via
      $GITHUB_STEP_SUMMARY and stdout, whether this run actually published
      <version> or found it already there. PyPI's JSON API sits behind a
      CDN and does not update instantaneously after an upload, so this
      polls with a bounded retry (cache-busted on every attempt) before
      declaring failure - a single stale read here would otherwise report
      a successful publish as a failure, which is worse than the silent
      success this script exists to fix. Fails only if the version never
      appears within the timeout.

Project name is fixed to "eddn-tail"; pass a different one via
$PYPI_PROJECT_NAME if ever needed.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

PROJECT_NAME = os.environ.get("PYPI_PROJECT_NAME", "eddn-tail")
ENV_VAR = "PYPI_HAD_VERSION_BEFORE_PUBLISH"

# Bounded retry for the post-publish check: PyPI's JSON endpoint is served
# through a CDN, so a freshly-published version can briefly read back as
# missing. ~80s total, polled every 8s, gives the CDN time to catch up
# without hanging the job for long on a genuine failure.
POST_RETRY_ATTEMPTS = 10
POST_RETRY_INTERVAL_SECONDS = 8


def version_on_pypi(version: str, *, cache_bust: bool = True) -> bool:
    url = f"https://pypi.org/pypi/{PROJECT_NAME}/json"
    if cache_bust:
        # A throwaway query parameter plus explicit no-cache headers, so a
        # retry cannot just be served the same cached (possibly stale) 404
        # or response by the CDN in front of pypi.org.
        url += f"?_cache_bust={time.time_ns()}"
    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
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


def wait_for_version_on_pypi(version: str) -> tuple[bool, int]:
    """Poll PyPI for `version`, returning (found, attempts_made)."""
    for attempt in range(1, POST_RETRY_ATTEMPTS + 1):
        print(f"Checking PyPI for {version} (attempt {attempt}/{POST_RETRY_ATTEMPTS})...")
        if version_on_pypi(version):
            print(f"{version} appeared on PyPI on attempt {attempt}.")
            return True, attempt
        if attempt < POST_RETRY_ATTEMPTS:
            time.sleep(POST_RETRY_INTERVAL_SECONDS)
    return False, POST_RETRY_ATTEMPTS


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("pre", "post"):
        print("usage: check_pypi_publish.py <pre|post> <version>", file=sys.stderr)
        return 2

    mode, version = sys.argv[1], sys.argv[2]

    if mode == "pre":
        had_before = version_on_pypi(version)
        write_github_env(ENV_VAR, "true" if had_before else "false")
        print(f"Before publish: {version} {'already exists' if had_before else 'is not yet'} on PyPI.")
        return 0

    # mode == "post"
    had_before = os.environ.get(ENV_VAR, "false") == "true"
    has_now, attempts = wait_for_version_on_pypi(version)

    if not has_now:
        timeout_seconds = POST_RETRY_ATTEMPTS * POST_RETRY_INTERVAL_SECONDS
        print(
            f"{version} did not show up on PyPI within {timeout_seconds}s of polling "
            f"({attempts} attempts) after the publish step. This usually means the publish "
            "genuinely did not work, but PyPI's JSON API can lag behind a real upload - "
            "check https://pypi.org/project/eddn-tail/ by hand before concluding the "
            "version is spent and burning the next one.",
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
            f"`{version}` was uploaded to PyPI by this run (confirmed on attempt {attempts})."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
