# AGENTS.md

TUI (Textual) that tails the EDDN ZeroMQ stream. Single-module app.

## Layout

```
eddn_tail.py              # entire application (~700 lines)
tests/test_eddn_tail.py   # entire test suite (125 tests, pytest)
pyproject.toml            # hatchling build, deps, console script `eddn-tail`
.github/workflows/        # build.yml (test + lint), release.yml (tag -> PyPI + GitHub Release)
demo.tape / demo.gif      # VHS demo recording (GIF is Git LFS)
.claude/skills/releasing/  # release runbook (invoke with /releasing)
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

## Contributing

All work happens on a branch and reaches `main` through a pull request. `main` is protected: direct
pushes are rejected, and a PR must have the Build checks green (pytest on 3.9-3.13, ruff on 3.13)
before it can merge. Merges go through GitHub's merge queue, which re-runs those checks against the
result of the merge rather than against the branch in isolation, so a PR that was green in isolation
can still fail in the queue and be ejected. Branch naming is not enforced; keep it short and
descriptive.

This applies to release commits too - see the Release section.

## Build & test

```bash
pip install -e ".[dev]"
python3 -m pytest        # 125 tests, ~2s, no network required (tests bind a local ZMQ PUB socket)
ruff check .             # must be clean
pytest --cov=eddn_tail --cov-report=term-missing   # coverage, currently ~53%
python3 eddn_tail.py     # run from source
python3 -m build         # sdist + wheel into dist/
```

Config lives in `pyproject.toml`: `[tool.ruff]` (py39 target, line-length 160, rules `E,F,W,I,B,C4,UP`), `[tool.pytest.ini_options]` (`--strict-markers --strict-config`, `filterwarnings = ["error"]`, so any new warning fails the suite), and `[tool.coverage.*]`. Ruff is pinned exactly (`ruff==0.15.12`) in the `dev` extra and CI installs it from there, so bumping ruff is a one-line change in `pyproject.toml`. There is no coverage gate; the misses are concentrated in the Textual UI layer (`_poll_messages`, `_refresh_table`, the event and `action_*` handlers) and `main()`, none of which is driven by a real app instance today - Textual's `run_test()` pilot is the way in if that changes.

CI (`build.yml`) runs pytest with coverage on Python 3.9-3.13 and ruff on 3.13, for pushes and PRs to `main`. `requires-python = ">=3.9"`, so no 3.10+ syntax. Annotations are the exception: `X | None` is used throughout and is valid only because both `eddn_tail.py` and the test module start with `from __future__ import annotations` - do not remove that import. Pyupgrade (`UP`) will flag `Optional[X]` if you reintroduce it.

## Release

1. Bump `version` in `pyproject.toml` (single source of truth; nothing else hardcodes it).
2. Commit on `main`, ensure CI is green.
3. Tag `vX.Y.Z` (must match `v[0-9]+.[0-9]+.[0-9]+`) and push the tag with `git push --tags`.

`release.yml` then builds the sdist/wheel, publishes to PyPI via trusted publishing (OIDC, `release` environment, `skip-existing`), and creates a GitHub Release with generated notes and those two files attached. PyPI is the only distribution channel; users run the tool via `uvx eddn-tail`, a `pip install`, or straight from a checkout.

Full runbook, including the unguarded failure modes (nothing checks the tag against `pyproject.toml`, and `skip-existing` turns a botched retry into a green run), is in `.claude/skills/releasing/SKILL.md` - invoke it with `/releasing`.
