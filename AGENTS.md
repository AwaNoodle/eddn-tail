# AGENTS.md

TUI (Textual) that tails the EDDN ZeroMQ stream. Single-module app.

## Layout

```
eddn_tail.py              # entire application (~700 lines)
tests/test_eddn_tail.py   # entire test suite (125 tests, pytest)
pyproject.toml            # hatchling build, deps, console script `eddn-tail`
.github/workflows/        # build.yml (test + lint), release.yml (tag -> PyPI + binaries)
demo.tape / demo.gif      # VHS demo recording (GIF is Git LFS)
```

## App structure (`eddn_tail.py`)

- Module constants: `EDDN_ENDPOINTS` (live/beta/dev), `SCHEMA_SHORT`, `SCHEMA_EVENT`, `SCHEMA_COLORS`, `MIN/MAX/DEFAULT_EVENT_LIMIT`.
- `EDDNReceiver` - ZMQ SUB socket, 100 ms RCVTIMEO; `recv_message()` zlib-decompresses and JSON-parses, returns `None` on timeout or `{"_error": ...}` on bad payloads.
- `extract_summary(msg)` - flattens an EDDN message into the display dict used by every filter and by `_format_row`.
- `EDDNTailApp(App)` - the UI. Key points:
  - Two parallel `OrderedDict`s keyed by stringified message counter: `_messages` (summaries) and `_raw_messages` (full JSON for the detail pane / export). Keep them in sync in any change.
  - `_poll_messages()` runs on a 0.05 s interval, drains up to 50 messages, applies CLI filters then the live filter (non-matching messages are discarded, never stored), enforces the FIFO limit, appends a row, then auto-scrolls once per batch.
  - Filters: CLI filters (`_matches_cli_filters`, substring, lowercased at construction) vs. the live `/` filter (`_matches_live_filter`, regex via cached `_live_filter_pattern`). They are separate on purpose - CLI drops increment `_filtered_count`, live-hidden rows are counted in `_refresh_table`.
  - `_refresh_table()` rebuilds the table from `_messages`; `_update_stats()` and `_update_pane_titles()` run on a 1 s interval.
- `build_parser()` / `main()` - argparse; `--beta`/`--dev` are mutually exclusive; `--limit` validated against MIN/MAX.

Conventions: no runtime config files, no logging framework, no async beyond Textual's own loop. Rich markup goes into table cells, so escape any user/wire-derived string with `rich_escape`.

## Build & test

```bash
pip install -e ".[dev]"
python3 -m pytest        # 125 tests, ~2s, no network required (tests bind a local ZMQ PUB socket)
ruff check .             # must be clean; CI runs it with default rules (no config in pyproject)
python3 eddn_tail.py     # run from source
python3 -m build         # sdist + wheel into dist/
```

CI (`build.yml`) runs pytest on Python 3.9-3.13 and ruff on 3.13, for pushes and PRs to `main`. `requires-python = ">=3.9"`, so no 3.10+ syntax (`match`, `X | Y` annotations at runtime; `from __future__ import annotations` is already imported).

## Release

1. Bump `version` in `pyproject.toml` (single source of truth; nothing else hardcodes it).
2. Commit on `main`, ensure CI is green.
3. Tag `vX.Y.Z` (must match `v[0-9]+.[0-9]+.[0-9]+`) and push the tag.

`release.yml` then builds the sdist/wheel, publishes to PyPI via trusted publishing (OIDC, `release` environment, `skip-existing`), creates a GitHub Release with generated notes, and attaches PyInstaller one-file binaries for Linux/macOS/Windows.
