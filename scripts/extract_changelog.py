#!/usr/bin/env python3
"""Extract one version's section body from CHANGELOG.md (Keep a Changelog
format) and print it to stdout.

Usage: extract_changelog.py <version> [changelog_path]

<version> has no leading "v" (e.g. "0.4.0"). Looks for a heading line of the
form "## [<version>] ..." and prints everything up to (not including) the
next "## [" heading, or end of file. Exits non-zero with a message on
stderr if:

- the section is missing or its body is empty, since a release must not go
  out with no notes.
- the file has more than one "## [<version>] ..." heading for the same
  version, which is unambiguous file corruption (the script would otherwise
  silently take the first one and hide the duplicate from whoever cuts the
  release).
- the extracted section body contains the same "### " subsection heading
  (e.g. "### Fixed") more than once, which happens when two PRs each add
  their own heading of the same name under the same version instead of
  appending to the existing one. `release.yml` publishes this output
  verbatim as the GitHub Release notes, and duplicate subsection headings
  there read as broken.

This is a structural duplicate check only - it does not police which
subsection names are allowed. Non-standard headings (e.g. this project's
"### Internal") are fine as long as they are not duplicated.
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections import Counter


class ChangelogError(Exception):
    """Raised when the changelog section for a version cannot be extracted cleanly."""


VERSION_HEADING_RE_TEMPLATE = r"^## \[{}\]"
ANY_VERSION_HEADING_RE = re.compile(r"^## \[")
SUBSECTION_HEADING_RE = re.compile(r"^### .+$")


def extract_section(changelog_path: pathlib.Path, version: str) -> str:
    """Return the body text of the `## [<version>]` section in changelog_path.

    Raises ChangelogError with a human-readable message if the section is
    missing, empty, duplicated, or contains duplicate `###` subsection
    headings.
    """
    if not changelog_path.exists():
        raise ChangelogError(f"{changelog_path} does not exist.")

    lines = changelog_path.read_text().splitlines()

    heading_re = re.compile(VERSION_HEADING_RE_TEMPLATE.format(re.escape(version)))

    matches = [i for i, line in enumerate(lines) if heading_re.match(line)]

    if not matches:
        raise ChangelogError(
            f"No '## [{version}]' section found in {changelog_path}. "
            "Add a changelog entry for this version before releasing."
        )

    if len(matches) > 1:
        raise ChangelogError(
            f"Found {len(matches)} '## [{version}]' headings in {changelog_path} "
            f"(lines {', '.join(str(i + 1) for i in matches)}). "
            "There must be exactly one section per version - merge them into a single "
            "section before releasing."
        )

    start = matches[0] + 1

    end = len(lines)
    for i in range(start, len(lines)):
        if ANY_VERSION_HEADING_RE.match(lines[i]):
            end = i
            break

    section_lines = lines[start:end]
    body = "\n".join(section_lines).strip()

    if not body:
        raise ChangelogError(
            f"The '## [{version}]' section in {changelog_path} is empty. "
            "Add release notes before releasing."
        )

    subsection_headings = [line.strip() for line in section_lines if SUBSECTION_HEADING_RE.match(line)]
    counts = Counter(subsection_headings)
    duplicated = [heading for heading, count in counts.items() if count > 1]
    if duplicated:
        heading_list = ", ".join(sorted(duplicated))
        raise ChangelogError(
            f"The '## [{version}]' section in {changelog_path} has a duplicated subsection "
            f"heading: {heading_list}. This usually happens when two PRs each add their own "
            "heading of the same name instead of appending to the existing one - merge them "
            "into a single subsection before releasing."
        )

    return body


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("usage: extract_changelog.py <version> [changelog_path]", file=sys.stderr)
        return 2

    version = sys.argv[1]
    changelog_path = pathlib.Path(sys.argv[2] if len(sys.argv) == 3 else "CHANGELOG.md")

    try:
        body = extract_section(changelog_path, version)
    except ChangelogError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
