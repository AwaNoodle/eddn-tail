"""Tests for scripts/extract_changelog.py.

This is a standalone script (not part of the `eddn_tail` package), so it is
loaded directly from its file path rather than imported as a module, and its
tests live in their own module rather than tests/test_eddn_tail.py.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

SCRIPT_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "extract_changelog.py"

_spec = importlib.util.spec_from_file_location("extract_changelog", SCRIPT_PATH)
extract_changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_changelog)

ChangelogError = extract_changelog.ChangelogError
extract_section = extract_changelog.extract_section


def _write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(text)
    return path


class TestExtractSectionHappyPath:
    def test_extracts_the_named_versions_body(self, tmp_path):
        path = _write(
            tmp_path,
            """# Changelog

## [Unreleased]

### Changed

- Something not yet released.

## [1.2.0] - 2026-01-01

### Added

- A new thing.

### Fixed

- A bug.

## [1.1.0] - 2025-01-01

### Fixed

- An older bug.
""",
        )
        body = extract_section(path, "1.2.0")
        assert "### Added" in body
        assert "- A new thing." in body
        assert "### Fixed" in body
        assert "- A bug." in body
        assert "1.1.0" not in body
        assert "Unreleased" not in body

    def test_extracts_final_section_running_to_end_of_file(self, tmp_path):
        path = _write(
            tmp_path,
            """# Changelog

## [1.0.0] - 2025-01-01

### Added

- The first release.
""",
        )
        body = extract_section(path, "1.0.0")
        assert body == "### Added\n\n- The first release."

    def test_non_standard_subsection_heading_is_allowed_when_not_duplicated(self, tmp_path):
        path = _write(
            tmp_path,
            """## [1.0.0] - 2025-01-01

### Internal

- Refactored something.
""",
        )
        body = extract_section(path, "1.0.0")
        assert "### Internal" in body


class TestExtractSectionMissing:
    def test_missing_version_heading_raises(self, tmp_path):
        path = _write(
            tmp_path,
            """## [1.0.0] - 2025-01-01

### Added

- Something.
""",
        )
        with pytest.raises(ChangelogError, match=r"No '## \[9\.9\.9\]' section found"):
            extract_section(path, "9.9.9")

    def test_missing_file_raises(self, tmp_path):
        path = tmp_path / "does_not_exist.md"
        with pytest.raises(ChangelogError, match="does not exist"):
            extract_section(path, "1.0.0")


class TestExtractSectionEmpty:
    def test_empty_section_raises(self, tmp_path):
        path = _write(
            tmp_path,
            """## [1.0.0] - 2025-01-01

## [0.9.0] - 2024-01-01

### Added

- Something.
""",
        )
        with pytest.raises(ChangelogError, match=r"'## \[1\.0\.0\]'.*is empty"):
            extract_section(path, "1.0.0")

    def test_whitespace_only_section_raises(self, tmp_path):
        path = _write(
            tmp_path,
            """## [1.0.0] - 2025-01-01


## [0.9.0] - 2024-01-01

### Added

- Something.
""",
        )
        with pytest.raises(ChangelogError, match="is empty"):
            extract_section(path, "1.0.0")


class TestExtractSectionDuplicateSubsectionHeading:
    def test_duplicate_subsection_heading_raises_and_names_it(self, tmp_path):
        path = _write(
            tmp_path,
            """## [1.0.0] - 2025-01-01

### Fixed

- First fix, added by one PR.

### Fixed

- Second fix, added by another PR that didn't notice the first heading.
""",
        )
        with pytest.raises(ChangelogError, match="duplicated subsection heading: ### Fixed"):
            extract_section(path, "1.0.0")

    def test_multiple_distinct_duplicates_are_all_named(self, tmp_path):
        path = _write(
            tmp_path,
            """## [1.0.0] - 2025-01-01

### Added

- One.

### Fixed

- Two.

### Added

- Three.

### Fixed

- Four.
""",
        )
        with pytest.raises(ChangelogError, match="### Added, ### Fixed"):
            extract_section(path, "1.0.0")

    def test_duplicate_heading_in_a_different_version_does_not_affect_this_one(self, tmp_path):
        path = _write(
            tmp_path,
            """## [1.0.0] - 2025-01-01

### Fixed

- Only one Fixed heading here.

## [0.9.0] - 2024-01-01

### Fixed

- One.

### Fixed

- Two.
""",
        )
        body = extract_section(path, "1.0.0")
        assert body == "### Fixed\n\n- Only one Fixed heading here."


class TestExtractSectionDuplicateVersionHeading:
    def test_duplicate_version_heading_anywhere_in_file_raises(self, tmp_path):
        path = _write(
            tmp_path,
            """## [1.0.0] - 2025-01-01

### Added

- First occurrence.

## [0.9.0] - 2024-01-01

### Fixed

- Something else entirely.

## [1.0.0] - 2025-01-02

### Added

- Second occurrence, e.g. from a bad merge.
""",
        )
        with pytest.raises(ChangelogError, match=r"Found 2 '## \[1\.0\.0\]' headings"):
            extract_section(path, "1.0.0")
