# EDDN Tail Plan

## Bug Fixes & Features

### 2026-05-13 — Round 1
1. **Truncated detail view** → Removed 5000-char cap; detail now shows full JSON
2. **Detail had extra non-JSON content** → Now shows only raw JSON, no header prefix
3. **Empty event/system/station for commodity/3** → Added `SCHEMA_EVENT` mapping to derive event names from schema; moved `schema_short` computation before event derivation
4. **Export JSON feature** → Added `e` keybinding + `action_export_json()` writing to `eddn_export_*.json`

### 2026-05-13 — Round 2
5. **System/station empty for commodity/3, outfitting/2, shipyard/2** → Real EDDN messages use lowercase `systemName`/`stationName`. Added fallback chain:
   - `system`: `StarSystem` → `SystemName` → `systemName`
   - `station`: `StationName` → `stationName`

### 2026-05-13 — Round 3
6. **uploaderID is a rotating hash** → EDDN relay applies `SHA-1(nonce + "-" + uploaderID)` with a nonce that rotates every 3 minutes. This means:
   - The hash can't be reproduced from a commander name
   - A hash copied from the stream only matches for ~3 minutes
   - Removed `-u`/`--uploader` CLI flag as it's fundamentally unreliable
   - Updated help text and README to explain the situation
   - Users can still use the live filter (`/`) for short-term matching

### 2026-05-14 — Round 4 — Lint fix
8. **Ruff lint errors (unused variables)** → Removed `original_update_pane_titles` and `original_update_stats` assignments that were assigned but never used in `TestClearEvents`

### 2026-05-14 — Round 5 — Refactoring & review-driven fixes
9. **Regex recompiled every message** → Added `_live_filter_pattern` cached field and `_compile_live_filter()` method; `on_filter_changed` and `action_clear_filter` update the cached pattern; `_matches_filters` uses it instead of calling `re.compile()` per invocation
10. **Duplicated ZMQ test helpers** → Replaced `_bind_pub()` + `TestEDDNReceiver._setup_receiver()` with single `_bind_zmq_pub()` helper; `_setup_receiver` now delegates to it

### 2026-05-14 — Round 6 — Blocker fixes from code review
11. **Live filter permanently discarded messages** → Split `_matches_filters` into `_matches_cli_filters` (permanent startup filters) and `_matches_live_filter` (interactive filter). `_poll_messages` now stores all CLI-filtered messages; only skips display for live filter mismatches. Clearing/widening the live filter reveals previously hidden messages via `_refresh_table`.
12. **Auto-scroll prevented manual navigation** → Changed unconditional `move_cursor` to only auto-scroll when cursor is within 2 rows of the bottom (`cursor_row >= total_rows - 2`)
13. **`_filtered_count` never decreased** → Stats bar now dynamically computes total dropped = CLI-dropped `_filtered_count` + live-filtered messages currently in `_messages`. Clearing/widening the live filter reduces the live-dropped count immediately.
7. **Clear events feature** → Add `Ctrl+L` keybinding + `action_clear_events()` to reset all received events to a clean state:
   - Clears `_messages` dict, resets `_msg_count` and `_filtered_count` to 0
   - Resets `_app_start_time` so rate counter restarts from scratch
   - Clears `DataTable` rows and detail pane content
   - Updates pane titles and stats bar
   - Shows `notify("Events cleared")` feedback
   - No confirmation dialog (consistent with existing single-press action pattern)
   - `Ctrl+L` chosen as standard terminal clear convention; avoids existing bindings; requires Ctrl modifier so not easily triggered accidentally