# Progress — eddn-tail Code Fixes

## 2026-05-15: Applied all 10 code fixes from parallel review

All fixes implemented, tests passing (97/97), ruff clean.

### Correctness fixes
1. ✅ Removed dead `live_filtered` counter from `_refresh_table()` — replaced with `live_hidden` that's assigned to `self._live_hidden_count`
2. ✅ Moved auto-scroll `move_cursor` call outside per-message loop — called once after the batch
3. ✅ Set `self._receiver = None` after `self._receiver.close()` in `on_unmount()`
4. ✅ Fixed `_filtered_count` — CLI-filtered messages still increment it, live-filtered messages no longer do. Added `_live_hidden_count` recalculated in `_refresh_table()`. Stats bar shows `Dropped: {cli_filtered + live_hidden}`
5. ✅ Documented substring matching in `--event` help text
6. ✅ `action_cursor_down` gracefully returns early on empty table instead of relying on bare except

### Simplification
7. ✅ Inlined `_matches_filters()` — removed method, callers use `_matches_cli_filters()` + `_matches_live_filter()` directly
8. ✅ Extracted `_format_raw_json()` static method for JSON formatting
9. ✅ Separated `raw` storage — `self._raw_messages: OrderedDict[str, dict]` alongside `self._messages`. `extract_summary` no longer includes `"raw"` key. All consumers updated.
10. ✅ Added comment in pyproject.toml noting `rich` is only used for `rich.markup.escape` and is a transitive dep of textual

### Test changes
- Updated `test_full_journal_scan` to assert `"raw" not in s`
- Updated `test_live_filter_discard_increments_filtered_count` → renamed to `test_live_filter_discard_does_not_increment_filtered_count`
- Updated `_matches_filters` test calls to use helper `_matches_all(app, summary)`
- Added `_raw_messages` to test fixtures for `clear_events`, `enforce_limit`, and `apply_limit_from_input`
- Cleaned up redundant `from collections import OrderedDict` imports in tests (7 locations)

## 2026-05-15: Test expansion and infrastructure improvements

Expanded test coverage from 97 to 125 tests. All passing, ruff clean.

### New test classes
1. ✅ `TestFormatRow` (21 tests) — direct tests for `_format_row()`:
   - Valid ISO timestamp → formatted time string
   - Invalid/empty/None timestamp → fallback handling
   - `SCHEMA_COLORS` → correct color markup per schema (journal, commodity, outfitting, shipyard)
   - Unknown schema → white color
   - Station/body priority (station > body when both present)
   - FSDJump with star_class shows `[K]` instead of station/body
   - FSDJump without star_class shows station normally
   - Non-FSDJump ignores star_class
   - `uploader_id` truncated to 12 chars, `software` truncated to 20 chars
   - Row tuple always 7 elements

2. ✅ `TestCompileLiveFilter` (5 tests) — direct tests for `_compile_live_filter()`:
   - Valid regex → compiled pattern with IGNORECASE
   - Valid regex matches expected strings
   - Invalid regex → returns None
   - Empty string → returns None
   - None/falsy value → returns None

3. ✅ `TestErrorHandling` (2 tests) — test `_error` dict handling:
   - Messages with `_error` key are identified as skippable
   - Normal messages without `_error` are not skipped

### Test infrastructure improvements
4. ✅ Moved `_FakeWidget` class to module level (top of file)
5. ✅ Consolidated 4 duplicated `_make_app()` factories into single module-level `_make_app()` helper
6. ✅ Consolidated `_scan_summary()` / `_commodity_summary()` helpers into module-level functions with configurable parameters
7. ✅ Added `try/finally` cleanup in `TestEDDNReceiver` teardown to prevent ZMQ resource leaks on failure
8. ✅ Added `import re` needed for new `TestCompileLiveFilter` tests