# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
