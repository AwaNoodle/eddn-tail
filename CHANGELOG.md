# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Releases are now cut by merging a version bump to `main`, instead of tagging and pushing by
  hand. `release.yml` triggers on push to `main`, checks whether the version in `pyproject.toml`
  is already tagged, and if not runs the changelog guard, creates and pushes the tag, builds,
  publishes to PyPI, and creates the GitHub Release - all in one workflow run, gated by the
  `release` environment's approval step.
- Project tooling (dev setup, `build.yml`, and the release build) now uses `uv` instead of `pip`.
  User-facing install instructions (`pip install eddn-tail`, `uvx eddn-tail`) are unchanged.

### Fixed

- The changelog guard (`scripts/extract_changelog.py`) now fails if the extracted section
  contains the same `###` subsection heading more than once, or if the changelog has more than
  one `## [<version>]` heading for the same version. Previously two PRs could each add their own
  `### Fixed` heading under the same version and the guard would pass, publishing broken-looking
  release notes with a duplicated heading.

## [0.4.0] - 2026-08-22

### Added

- The detail pane now shows the selected message's JSON with syntax
  highlighting - keys, strings, numbers, booleans, and nulls are each
  coloured distinctly, using Rich's theme-aware defaults so it reads well on
  both light and dark terminals. Exporting a message (`e`) still writes plain,
  uncoloured JSON to disk.

### Fixed

- Corrected the declared `textual` floor. The published metadata said
  `textual>=0.40`, but the app uses `Input.Blurred`, which does not exist
  before textual 2.0 - so installing alongside an older textual produced an
  `AttributeError` on import rather than a resolver error. The floor is now
  `textual>=2.0,<9`, verified by installing the floor and running the suite
  against it.
- Raised the `pyzmq` floor to 26.1, the first release with prebuilt wheels for
  Python 3.12 and 3.13; older versions forced a source build.
- Raised the `rich` floor to 13.3.3, which textual 2.0 itself requires. The
  previous combination of `rich>=13.0` with a correct textual floor was not
  resolvable.
- The stats bar refresh no longer raises when its 1 second interval ticks
  while the app is shutting down. The widgets can already be gone by then; the
  tick is now a no-op instead of an error on quit.

### Internal

- Pilot-driven tests that drive a real running Textual app, covering the
  keybindings, row selection, the live filter, and the FIFO event limit.
  Coverage rises from 53% to 89%.
- A `test-floor` build job that installs the declared dependency floors and
  runs the test suite against them, so floor drift is caught automatically.
- Release guards: the tag is checked against `pyproject.toml`, the changelog
  section must exist, and a PyPI publish is distinguished from a skip.

## [0.3.0] - 2026-05-15

### Changed

- Halved per-message memory usage by storing raw messages separately from
  their summaries instead of duplicating both.
- Auto-scroll now happens once per received batch instead of once per
  message, reducing overhead on busy streams.
- The stats bar now reports an accurate dropped-message count while a live
  filter is active.

### Fixed

- Guard against a crash when moving the table cursor while the table is
  empty.

### Documentation

- Clarified in `--event` help text that event-name matching is by
  substring.
