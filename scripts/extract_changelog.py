#!/usr/bin/env python3
"""Extract one version's section body from CHANGELOG.md (Keep a Changelog
format) and print it to stdout.

Usage: extract_changelog.py <version> [changelog_path]

<version> has no leading "v" (e.g. "0.4.0"). Looks for a heading line of the
form "## [<version>] ..." and prints everything up to (not including) the
next "## [" heading, or end of file. Exits non-zero with a message on
stderr if the section is missing or its body is empty, since a release
must not go out with no notes.
"""

from __future__ import annotations

import pathlib
import re
import sys


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("usage: extract_changelog.py <version> [changelog_path]", file=sys.stderr)
        return 2

    version = sys.argv[1]
    changelog_path = pathlib.Path(sys.argv[2] if len(sys.argv) == 3 else "CHANGELOG.md")

    if not changelog_path.exists():
        print(f"{changelog_path} does not exist.", file=sys.stderr)
        return 1

    lines = changelog_path.read_text().splitlines()

    heading_re = re.compile(r"^## \[" + re.escape(version) + r"\]")
    any_heading_re = re.compile(r"^## \[")

    start = None
    for i, line in enumerate(lines):
        if heading_re.match(line):
            start = i + 1
            break

    if start is None:
        print(
            f"No '## [{version}]' section found in {changelog_path}. "
            "Add a changelog entry for this version before releasing.",
            file=sys.stderr,
        )
        return 1

    end = len(lines)
    for i in range(start, len(lines)):
        if any_heading_re.match(lines[i]):
            end = i
            break

    body = "\n".join(lines[start:end]).strip()

    if not body:
        print(
            f"The '## [{version}]' section in {changelog_path} is empty. "
            "Add release notes before releasing.",
            file=sys.stderr,
        )
        return 1

    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
