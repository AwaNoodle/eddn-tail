# Complexity & Maintainability Review: eddn-tail

**Files inspected:** `eddn_tail.py` (639 lines), `tests/test_eddn_tail.py` (621 lines)

---

## Over-Engineering & Unnecessary Abstraction

### 1. `summary["raw"]` doubles memory for every stored message

**File:** `eddn_tail.py`, `extract_summary()` line ~107 (return dict)

Every message stored in `_messages` carries the full raw JSON dict via `summary["raw"]`. The raw dict is only used in two places: `on_row_selected` (line 466) and `action_export_json` (line 591). At limit=1999, this means ~1999 full EDDN messages kept in memory solely for detail/export—roughly doubling memory usage.

**Simpler alternative:** Store raw JSON in a separate `OrderedDict[str, dict]` keyed by `msg_key`. The summary dict would drop the `"raw"` key, saving ~50% memory per message. Lookup is by the same key either way.

---

### 2. `_matches_filters()` is a one-line delegate used once

**File:** `eddn_tail.py`, lines 360–362

```python
def _matches_filters(self, summary: dict) -> bool:
    return self._matches_cli_filters(summary) and self._matches_live_filter(summary)
```

This method is called only in `_refresh_table()` (line 421). In `_poll_messages()` (lines 378–385), the two sub-checks are called separately because they need different control flow (different `continue` branches incrementing `_filtered_count`). The wrapper adds indirection for no reuse benefit.

**Simpler alternative:** Inline `self._matches_cli_filters(s) and self._matches_live_filter(s)` in `_refresh_table()` and remove `_matches_filters()`.

---

### 3. Dual-purpose filter input requires mode flag across 5 locations

**File:** `eddn_tail.py`, `_limit_input_mode` referenced at lines 236, 478, 489, 498, 503, 561

The same `Input` widget serves as both a live filter and a limit setter. This requires a boolean `_limit_input_mode` flag checked in `on_filter_changed`, `on_filter_submitted`, and `on_filter_blur`. Additionally, the placeholder text and input value are swapped depending on mode. The branching logic is scattered and error-prone (the prior correctness review identified placeholder restoration bugs).

**Simpler alternative:** Use Textual's `InputDialog` or a separate mode-specific input widget for the limit. This eliminates the mode flag, shared state, and placeholder/value swapping entirely. Even a simple Python `input()` via `app.exit()` would be cleaner for a low-frequency operation.

---

## Redundant Code

### 4. FSDJump location display special-cased in two places

**File:** `eddn_tail.py`, lines 96–97 (extract_summary) and 260–262 (_format_row)

`extract_summary()` extracts `star_class` for every message (most don't have it), then `_format_row()` checks `if summary["star_class"] and summary["event"] == "FSDJump"` to override `location`. The `star_class` field sits in every summary dict even though it's only meaningful for FSDJump events. Meanwhile `body` is extracted for every message but only useful for Scan events.

This is minor—it's just a few dict entries—but it establishes a pattern where each new event type that needs a special display column requires touching both `extract_summary` and `_format_row`.

---

### 5. `rich_escape` of JSON duplicated in two handlers

**File:** `eddn_tail.py`, lines 469 and 595

Both `on_row_selected` and `action_export_json` contain:

```python
raw_json = json.dumps(summary["raw"], indent=2, ensure_ascii=False)
```

The only difference is that `on_row_selected` also calls `rich_escape()` on it. A small helper like `_get_raw_json(summary, escape=False)` would remove the duplication and centralize formatting.

---

## Convoluted Control Flow

### 6. Live filter discard makes `_refresh_table` live-filter check mostly dead code

**File:** `eddn_tail.py`, lines 378–385 (_poll_messages) and 418–423 (_refresh_table)

In `_poll_messages`, non-matching messages are discarded on arrival when a live filter is active. They are never stored in `_messages`. So when `_refresh_table` iterates over `_messages` and checks `self._matches_filters(summary)`, the live-filter check can never reject a stored message—those messages already passed the live filter when they arrived. Only the CLI filter check is meaningful in `_refresh_table` (and even that is always True since CLI rejection also discards on arrival).

The `live_filtered` counter (line 419) in `_refresh_table` will always be 0. The `_matches_filters` call there serves no practical purpose.

---

### 7. `Esc` key interacts with limit mode in a confusing way

**File:** `eddn_tail.py**, `action_clear_filter()` (line 519)

`Esc` is bound to `clear_filter`, which unconditionally resets `self._live_filter = ""` and sets `inp.value = ""` (which fires `Input.Changed` → `_refresh_table`). If the user canceled out of limit mode via blur/escape, this also clears any existing live filter—a side-effect the user wouldn't expect from "cancel limit input."

---

## Naming Clarity

### 8. `_msg_count` suggests "stored messages" but counts all received

**File:** `eddn_tail.py`, line 240 (`self._msg_count = 0`) and line 379

The name suggests "how many messages are stored," but it's a monotonically increasing counter of every message received (including those later filtered). The stats bar uses it as "Total:" which is accurate, but the underscore-prefixed name reads like "messages currently held." A name like `_total_received` would be unambiguous.

---

### 9. `initial_limit` parameter name implies immutability

**File:** `eddn_tail.py**, line 229

The `__init__` parameter is `initial_limit`, stored as `self._max_event_limit`. The "initial" prefix suggests it's a starting value that may change, which is fine—but `_max_event_limit` uses "max" instead, creating a mismatch. Either `_initial_limit → _max_event_limit` or `_event_limit → _event_limit` would be consistent.

---

### 10. `_poll_messages` does more than poll

**File:** `eddn_tail.py**, line 364

The method polls for messages **and** filters, stores, formats, and renders them. A name like `_process_incoming` or `_receive_and_display` would better describe its scope.

---

## Unnecessary Dependencies

### 11. `rich` is a direct dependency but only used for `rich_escape`

**File:** `eddn_tail.py`, line 29: `from rich.markup import escape as rich_escape`

`rich` is listed as a direct dependency in `pyproject.toml`, but the only direct usage is `rich_escape()` applied to JSON in the detail pane. Since `textual` already depends on `rich`, this works in practice, but the explicit dependency in `pyproject.toml` suggests it's a first-class requirement. The project could either:
- Remove `rich` from explicit dependencies (it's transitively guaranteed by `textual`), or
- Keep it and acknowledge it's only for the escape function.

Not a real bug, but a dependency clarity issue.

---

## Test Maintainability

### 12. `_FakeWidget` class defined in the middle of test file

**File:** `tests/test_eddn_tail.py**, class `_FakeWidget` (around line 470, between `TestClearEvents` and `TestEventLimitConstants`)

This class is a test helper but is placed in the middle of the file between two test classes. It should be either at the top (near other helpers like `_compress` and `_bind_zmq_pub`) or at the bottom—not sandwiched between test classes.

---

### 13. `_make_app` helper duplicated across test classes

**File:** `tests/test_eddn_tail.py**, in `TestMatchesFilters`, `TestFilterSplit`, `TestClearEvents`, `TestApplyLimitFromInput`

The same `_make_app` factory (`EDDNTailApp(endpoint="tcp://localhost:9999", **kwargs)`) is defined in at least 4 test classes. Similarly, `_scan_summary` and `_commodity_summary` helpers are duplicated. These could be module-level fixtures or conftest.py fixtures.

---

## Summary

| # | Category | Severity | Finding |
|---|----------|----------|---------|
| 1 | Over-engineering | 🟡 Medium | `summary["raw"]` doubles memory; separate store would be leaner |
| 2 | Over-engineering | 🔵 Low | `_matches_filters()` is a one-line delegate used once |
| 3 | Over-engineering | 🟡 Medium | Dual-purpose input + `_limit_input_mode` flag across 5 sites; modal or separate widget would simplify |
| 4 | Redundancy | 🔵 Low | FSDJump location logic split across extract/format; mild pattern concern |
| 5 | Redundancy | 🔵 Low | `json.dumps(summary["raw"])` duplicated in two handlers |
| 6 | Dead code | 🟡 Medium | `_refresh_table` live-filter check cannot reject stored messages; `live_filtered` counter always 0 |
| 7 | Control flow | 🟡 Medium | `Esc` in limit mode destroys existing live filter |
| 8 | Naming | 🔵 Low | `_msg_count` reads as stored count but is total received |
| 9 | Naming | 🔵 Low | `initial_limit` → `_max_event_limit` name mismatch |
| 10 | Naming | 🔵 Low | `_poll_messages` name understates scope |
| 11 | Dependency | 🔵 Low | `rich` is direct dependency but only used for `rich_escape` |
| 12 | Test hygiene | 🔵 Low | `_FakeWidget` sandwiched between test classes |
| 13 | Test hygiene | 🔵 Low | `_make_app` and summary helpers duplicated across 4+ test classes |

**Most impactful to address:** #3 (mode flag complexity), #6 (dead filter logic in refresh), #1 (memory doubling from raw storage). These three have the highest cost-to-value ratio in the current design.