# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Added

- A `test-floor` build job that installs the declared dependency floors and
  runs the test suite against them, so floor drift is caught automatically.
- Pilot-driven tests that drive a real running Textual app, covering the
  keybindings, row selection, the live filter, and the FIFO event limit.
  Coverage rises from 53% to 89%. `pytest-asyncio` returns as a dev
  dependency (with `asyncio_mode = "auto"`), since Textual's `run_test()`
  harness is async.

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
