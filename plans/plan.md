# Feature Plan: Configurable Event Storage Limit + Filter-Aware Discard

**Status:** ✅ Complete — implemented, reviewed, and all 125 tests passing.

## What was done

1. **CLI Argument:** Added `-l`/`--limit` with validation (1–1999), default 500.
2. **FIFO Eviction:** `OrderedDict.popitem(last=False)` for O(1) eviction; also removes the row from `DataTable`.
3. **Runtime Configuration:** `Alt+L` binding opens filter bar in "limit input mode" (`_limit_input_mode` flag). Only this entry point routes input as a limit change.
4. **Retroactive Pruning:** `_enforce_limit()` called when lowering limit at runtime, immediately trimming excess messages.
5. **Constants:** Extracted `MIN_EVENT_LIMIT`, `MAX_EVENT_LIMIT`, `DEFAULT_EVENT_LIMIT` — used everywhere.
6. **Filter-Aware Discard (Option B):** When a live filter is active, messages that don't match are discarded on arrival (never stored). Existing messages from before the filter was activated remain until evicted by FIFO.
7. **Tests:** 125 tests (up from 97).

## Review fixes applied (round 1)

- **Critical:** `DataTable.remove_row()` added alongside `OrderedDict.popitem` to prevent orphaned stale rows.
- **Complexity:** Replaced `min(keys, key=int)` + bare `except Exception: pass` with `OrderedDict.popitem(last=False)` — O(1), no try/except needed.
- **Mode confusion:** Replaced `isdigit()` dispatch with `_limit_input_mode` flag — filter bar no longer steals numeric inputs.
- **Placeholder reset:** `on_filter_blur` resets `_limit_input_mode` and placeholder.
- **Retroactive pruning:** `_apply_limit_from_input()` calls `_enforce_limit()` + `_refresh_table()`.
- **Stats bar:** Simplified to `Dropped: {count}` (no longer counts stale live-filter mismatches).

## Review fixes applied (round 2 — parallel review)

Three reviewers ran in parallel (correctness, tests, complexity). Findings and outcomes:

| Finding | Source | Status |
|---------|--------|--------|
| Live filter permanently discards messages | Correctness | ✅ Intended behavior, documented |
| Dead `live_filtered` counter in `_refresh_table` | Correctness | ✅ Renamed to `_live_hidden_count`, now used in stats |
| Auto-scroll per-message in batch loop | Correctness | ✅ Moved outside loop, called once per batch |
| `_filtered_count` misleading after re-filter | Correctness | ✅ Added `_live_hidden_count`, displayed as total in stats |
| `_receiver` not set to None after close | Correctness | ✅ Set to `None` in `on_unmount` |
| CLI filter substring matching undocumented | Correctness | ✅ Help text updated |
| `action_cursor_down` bare except on empty table | Correctness | ✅ Added early return for empty table |
| `_matches_filters` one-line delegate used once | Complexity | ✅ Inlined, calls sub-methods directly |
| `json.dumps(summary["raw"])` duplicated | Complexity | ✅ Extracted `_format_raw_json()` helper |
| `summary["raw"]` doubles memory | Complexity | ✅ Separated into `_raw_messages: OrderedDict` |
| `rich` dependency unclear | Complexity | ✅ Comment added to `pyproject.toml` |
| `_format_row` — zero tests | Tests | ✅ 21 tests added (TestFormatRow) |
| `_compile_live_filter` — only indirect tests | Tests | ✅ 5 tests added (TestCompileLiveFilter) |
| `_error` dict handling — untested | Tests | ✅ 2 tests added (TestErrorHandling) |
| `_FakeWidget` sandwiched between test classes | Tests | ✅ Moved to module level |
| `_make_app` duplicated across 4+ test classes | Tests | ✅ Consolidated to module-level helper |
| `_scan_summary`/`_commodity_summary` duplicated | Tests | ✅ Consolidated to module-level helpers |
| ZMQ test resource leaks on failure | Tests | ✅ Added `try/finally` cleanup |