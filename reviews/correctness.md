# Correctness Review: eddn-tail

**Date:** 2026-05-15  
**Scope:** `eddn_tail.py` (lines 1–634) and `tests/test_eddn_tail.py`  
**Tests:** 97/97 passing  
**Previous review issues:** All 9 items from prior review addressed (FIFO DataTable sync, limit-mode corruption, Unicode digits, etc.)

---

## Correct

- **FIFO eviction is now sound.** `_poll_messages` removes rows from both `_messages` (via `OrderedDict.popitem(last=False)`) and `DataTable` (via `table.remove_row(oldest_key)`) in one atomic step. O(1) eviction. (lines 381–385)
- **Limit input mode prevents filter corruption.** `_limit_input_mode` flag gates `on_filter_changed` (line 429), so pre-filling `inp.value = str(self._max_event_limit)` no longer clobbers the live filter. (lines 531–537, 429–431)
- **CLI filters use substring matching intentionally** and are tested as such (test_event_filter_substring). The docstring on `_matches_cli_filters` documents permanent discard behavior. (lines 308–319, docstring lines 308–313)
- **ZMQ error handling** gracefully returns `None` on timeout/disconnect and `{"_error": ...}` on decompression/parse failures. Error messages are never added to the table (line 370). (lines 55–64)
- **Live filter regex compilation** is cached in `_live_filter_pattern` and recompiled on every change. Invalid regex falls back to substring match. (lines 284–288, 348–351)

---

## Blocker

### 1. Live filter permanently discards non-matching messages — clearing filter doesn't recover them

**File:** `eddn_tail.py`, lines 376–379

```python
# --- Live filter: discard non-matching messages on arrival ---
if self._live_filter and not self._matches_live_filter(summary):
    self._filtered_count += 1
    continue
```

When a live filter is active, messages that don't match are **never stored** in `_messages`. When the user clears the filter (`Esc`), `_refresh_table()` rebuilds from `_messages` — but those discarded messages are gone forever. The `Dropped: N` counter only grows, never shrinks.

The docstring on `_matches_live_filter` (lines 338–345) acknowledges this, but from a user's perspective it's confusing: type `/Sol`, see only Sol messages, press `Esc`, and the table only shows Sol-era messages that happened to match "Sol". All other messages received during that window are permanently lost.

**Impact:** Users who temporarily filter to narrow their view will lose messages they might want to see after clearing the filter. This is a design choice but is the kind of behavior that causes real user surprise — especially since the app is described as a "tail" (implying you can scroll back).

**Suggested fix:** Instead of discarding on arrival, store all messages in `_messages` and only use the live filter to control _visibility_. `_poll_messages` would always store; `_refresh_table` would filter for display. The `Dropped` counter would track CLI-filtered messages only (which are intentionally permanent).

---

## Bug

### 2. `_refresh_table` computes `live_filtered` but never uses it

**File:** `eddn_tail.py`, lines 389–396

```python
def _refresh_table(self) -> None:
    table = self.query_one("#message-table", DataTable)
    table.clear()

    live_filtered = 0               # ← computed but never read
    for msg_key, summary in self._messages.items():
        if not self._matches_filters(summary):
            live_filtered += 1      # ← never used
            continue
        table.add_row(*self._format_row(summary), key=msg_key)
```

`live_filtered` is incremented but never returned, stored, or referenced. Either remove it or use it to update `_filtered_count`/stats.

### 3. Auto-scroll runs per-message inside the batch loop

**File:** `eddn_tail.py`, lines 391–396

```python
# Inside: for _ in range(50): ...
    table.add_row(*self._format_row(summary), key=msg_key)
    total_rows = len(table.rows)
    if total_rows > 0:
        try:
            if table.cursor_row >= total_rows - 2:
                table.move_cursor(row=total_rows - 1)
        except Exception:
            pass
```

`move_cursor` is called up to 50 times per 50ms poll cycle (once per message in the batch). Moving the cursor on every row is unnecessary since the final `move_cursor` after the batch would suffice. This is wasteful but not incorrect — the `>= total_rows - 2` guard prevents most redundant moves. Still, it could cause visual jitter during high-throughput bursts.

### 4. `_filtered_count` is monotonically increasing, never adjusted on filter change

**File:** `eddn_tail.py`, lines 374, 378, 415

`_filtered_count` only increments (on CLI or live filter discard) and only resets on `action_clear_events`. When a user changes the live filter, existing stored messages may now be filtered out by `_refresh_table`, but `_filtered_count` doesn't increase to account for them. Conversely, it never decreases. This means the "Dropped: N" stat can undercount (messages hidden by live filter re-application aren't counted) and overcount (it includes messages from previous filter configurations that would match the current filter but were already permanently discarded).

**Not a crash bug**, but the stats display will be misleading after any filter change.

---

## Note

### 5. `_format_row` discards station/body for FSDJump events

**File:** `eddn_tail.py`, lines 297–299

```python
location = summary["station"] or summary["body"]
if summary["star_class"] and summary["event"] == "FSDJump":
    location = f"[{summary['star_class']}]"
```

For FSDJump events with both `StarClass` and `StationName`/`BodyName`, the station/body is overwritten by `[K]`. In practice, FSDJump events don't carry station/body, so this is a non-issue for real EDDN data, but the logic is fragile if the schema changes.

### 6. `_receiver` is never set to None after close

**File:** `eddn_tail.py`, lines 270–271

```python
def on_unmount(self) -> None:
    if self._receiver:
        self._receiver.close()
```

After `close()`, `self._receiver` still references the closed object. If `_poll_messages` fires during teardown (between `close()` and timer cancellation), it will call `recv_message()` on a closed socket. The `zmq.ZMQError` catch handles this (returns None, which breaks the batch loop), so it's not a crash — just a latent edge case. Setting `self._receiver = None` would make the `if not self._receiver` guard on line 367 effective.

### 7. CLI filter matching is substring, not exact — undocumented

**File:** `eddn_tail.py`, lines 310–317

```python
if self._event_filter and self._event_filter not in summary["event"].lower():
```

`--event Scan` matches "Scan", "ScanBaryCentre", "FSSAllBodiesFound" (no — "scan" is in "Scan" and "ScanBaryCentre" only). The CLI help says `Filter by journal event name` but doesn't mention it's a substring/contains match. The live filter explicitly says `(regex supported)` but no such note exists for CLI flags.

### 8. `action_export_json` uses `coordinate_to_cell_key` which may be fragile across Textual versions

**File:** `eddn_tail.py`, lines 513–515

```python
cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
msg_key = cell_key.row_key.value
```

This API surface is used to get the row key from the cursor position. The `row_key.value` returns the string key set via `table.add_row(..., key=msg_key)`. This works but depends on Textual's internal `RowKey` having a `.value` attribute, which is documented but could be a version-sensitive API.

### 9. `action_cursor_down` can compute `min(-1, ...)` on empty table

**File:** `eddn_tail.py`, lines 526–528

```python
def action_cursor_down(self) -> None:
    table = self.query_one("#message-table", DataTable)
    try:
        table.move_cursor(row=min(len(table.rows) - 1, table.cursor_row + 1))
```

When the table is empty, `len(table.rows) - 1 = -1`. `min(-1, cursor_row+1)` = -1. `move_cursor(row=-1)` would raise, caught by the bare `except Exception: pass`. Not a crash but the logic is misleading.

---

## Summary

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | 🔴 Blocker | Live filter permanently discards messages — clearing filter doesn't recover them | `eddn_tail.py:376-379` |
| 2 | 🟡 Bug | `_refresh_table` computes `live_filtered` but never uses it | `eddn_tail.py:390-396` |
| 3 | 🟡 Bug | Auto-scroll calls `move_cursor` per-message in batch loop (wasteful, potential jitter) | `eddn_tail.py:391-396` |
| 4 | 🟡 Bug | `_filtered_count` never adjusts on filter change — stats misleading after re-filter | `eddn_tail.py:374,378,415` |
| 5 | 🔵 Note | FSDJump `star_class` overwrites station/body display | `eddn_tail.py:297-299` |
| 6 | 🔵 Note | `_receiver` never set to `None` after close — late poll possible on closed socket | `eddn_tail.py:270-271` |
| 7 | 🔵 Note | CLI filter substring matching undocumented | `eddn_tail.py:310-317` |
| 8 | 🔵 Note | `coordinate_to_cell_key` API is version-sensitive | `eddn_tail.py:513-515` |
| 9 | 🔵 Note | `action_cursor_down` computes -1 on empty table (caught by except) | `eddn_tail.py:526-528` |