#!/usr/bin/env python3
"""Decide whether a push to `main` should trigger a release.

`release.yml` runs this on every push to `main`. A release is needed only
when the tag implied by `pyproject.toml`'s version (`v<version>`) does not
already exist - most pushes are not releases, so this must be cheap and its
verdict unambiguous in the log.

Usage: check_release_needed.py [version]

If <version> is omitted, it is read from pyproject.toml. Passing it
explicitly is for local dry runs (e.g. a fake version to exercise the
"release needed" branch without touching pyproject.toml).

Tag existence is checked against the local git repository, so the caller
must have fetched tags first (`actions/checkout` with `fetch-depth: 0` does
this). Writes `release_needed`, `version`, and `tag` to $GITHUB_OUTPUT when
running in GitHub Actions; otherwise prints them to stdout.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import tomllib


def get_pyproject_version(path: pathlib.Path = pathlib.Path("pyproject.toml")) -> str:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def tag_exists(tag: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def write_github_output(name: str, value: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        print(f"{name}={value}")
        return
    with open(github_output, "a") as f:
        f.write(f"{name}={value}\n")


def main() -> int:
    if len(sys.argv) not in (1, 2):
        print("usage: check_release_needed.py [version]", file=sys.stderr)
        return 2

    version = sys.argv[1] if len(sys.argv) == 2 else get_pyproject_version()
    tag = f"v{version}"
    needed = not tag_exists(tag)

    write_github_output("version", version)
    write_github_output("tag", tag)
    write_github_output("release_needed", "true" if needed else "false")

    if needed:
        print(f"{tag} not yet released; release needed for version {version}.")
    else:
        print(f"{tag} already released, nothing to do.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
