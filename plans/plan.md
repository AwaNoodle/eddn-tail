# Feature Plan: Configurable Event Storage Limit + Filter-Aware Discard

**Status:** ✅ Complete — implemented, reviewed, and all 97 tests passing.

## What was done

1. **CLI Argument:** Added `-l`/`--limit` with validation (1–1999), default 500.
2. **FIFO Eviction:** `OrderedDict.popitem(last=False)` for O(1) eviction; also removes the row from `DataTable`.
3. **Runtime Configuration:** `Alt+L` binding opens filter bar in "limit input mode" (`_limit_input_mode` flag). Only this entry point routes input as a limit change.
4. **Retroactive Pruning:** `_enforce_limit()` called when lowering limit at runtime, immediately trimming excess messages.
5. **Constants:** Extracted `MIN_EVENT_LIMIT`, `MAX_EVENT_LIMIT`, `DEFAULT_EVENT_LIMIT` — used everywhere.
6. **Filter-Aware Discard (Option B):** When a live filter is active, messages that don't match are discarded on arrival (never stored). Existing messages from before the filter was activated remain until evicted by FIFO.
7. **Tests:** 97 tests (33 new for limit + 6 for discard-on-arrival).

## Review fixes applied

- **Critical:** `DataTable.remove_row()` added alongside `OrderedDict.popitem` to prevent orphaned stale rows.
- **Complexity:** Replaced `min(keys, key=int)` + bare `except Exception: pass` with `OrderedDict.popitem(last=False)` — O(1), no try/except needed.
- **Mode confusion:** Replaced `isdigit()` dispatch with `_limit_input_mode` flag — filter bar no longer steals numeric inputs.
- **Placeholder reset:** `on_filter_blur` resets `_limit_input_mode` and placeholder.
- **Retroactive pruning:** `_apply_limit_from_input()` calls `_enforce_limit()` + `_refresh_table()`.
- **Stats bar:** Simplified to `Dropped: {count}` (no longer counts stale live-filter mismatches).