#!/usr/bin/env python3
"""Fail loudly if the git tag that triggered a release does not match the
version in pyproject.toml.

Usage: check_release_version.py <tag>

<tag> is expected to look like "v0.4.0" (a leading "v" is stripped before
comparing). Exits non-zero with a message naming both values on mismatch.
"""

from __future__ import annotations

import pathlib
import sys

import tomllib


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_release_version.py <tag>", file=sys.stderr)
        return 2

    tag = sys.argv[1]
    tag_version = tag[1:] if tag.startswith("v") else tag

    pyproject_path = pathlib.Path("pyproject.toml")
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    pyproject_version = data["project"]["version"]

    if tag_version != pyproject_version:
        print(
            f"Version mismatch: tag '{tag}' implies version '{tag_version}', "
            f"but pyproject.toml has version '{pyproject_version}'. "
            "Refusing to build or publish.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: tag '{tag}' matches pyproject.toml version '{pyproject_version}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
