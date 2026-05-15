# Test Quality Review: eddn_tail

**Files reviewed:** `tests/test_eddn_tail.py` (1137 lines, 97 tests), `eddn_tail.py` (698 lines)
**Test run:** 97 passed (1.46s)

---

## Correct — What's Good

- **`extract_summary` coverage is thorough** (18 tests in `TestExtractSummary`): covers journal, commodity, outfitting, shipyard, FSDJump, missing fields, empty refs, unknown schemas, field priority resolution (StarSystem > SystemName > systemName, StationName > stationName).
- **`EDDNReceiver` tests are solid** (5 tests): valid message, timeout, invalid zlib, invalid JSON, clean close — uses real ZMQ PUB/SUB with ephemeral ports.
- **`_matches_filters`/`_matches_cli_filters`/`_matches_live_filter`** (19 tests across `TestMatchesFilters` and `TestFilterSplit`): covers CLI filter AND logic, case-insensitive substring match, live regex, invalid regex fallback, combined CLI+live, empty filters.
- **`_enforce_limit` FIFO eviction** (5 tests): below cap, at cap, over cap (single eviction), multiple evictions, empty dict — tests the `OrderedDict.popitem(last=False)` behavior correctly.
- **`_apply_limit_from_input`** (7 tests): valid limits, boundary values (1, 1999), rejection of zero/too-large/non-integer, and enforcement after lowering.
- **`action_clear_events`** (5 tests): state reset, rate reset, DataTable/detail clearance, notify call, update hooks.
- **Arg parsing** (10 tests): defaults, combined flags, mutual exclusion, boundary limits.

---

## Blocker — None

---

## Missing Test Coverage — Untested Public Methods

### 1. `_format_row()` — **Zero tests**
`eddn_tail.py:298-321`

This method formats message summaries into DataTable row tuples. It contains:
- Timestamp parsing (valid ISO, invalid, empty)
- Rich markup color application from `SCHEMA_COLORS`
- Station/body display logic (prefer station over body)
- FSDJump star-class display (`[K]` override)
- String truncation (`uploader_id[:12]`, `software[:20]`)

None of these branches are tested. Example untested paths:
- Timestamp with invalid format falls back to `ts[:8]` or `"??"` (line 307-310)
- FSDJump with `star_class` shows `[K]` instead of station/body (line 315)
- Unknown schema → `"white"` color (line 312)

### 2. `_poll_messages()` — **Zero integration/simulation tests**
`eddn_tail.py:364-412`

This is the core message ingestion loop. No test verifies:
- Messages are actually added to `_messages` and the table
- `_filtered_count` increments on CLI filter discard
- `_filtered_count` increments on live filter discard
- FIFO eviction + `table.remove_row()` sync (the known bug from correctness review)
- Auto-scroll behavior (cursor near bottom vs. not)
- Paused state skips polling
- `_error` messages are skipped (`if "_error" in msg: continue`)
- Batch limit (up to 50 messages per poll)

The `TestLiveFilterDiscardOnArrival` class **only tests the `_matches_*` helper methods** — it never calls `_poll_messages` or simulates its logic. The test names suggest integration coverage ("discard_on_arrival") but only exercise predicate functions.

### 3. `_refresh_table()` — **Zero tests**
`eddn_tail.py:414-425`

This method rebuilds the DataTable from stored messages. Unverified:
- Table is cleared before re-adding rows
- Live filter is respected during rebuild
- Messages that fail `_matches_live_filter` are skipped in display
- `_filtered_count` is NOT recalculated (known bug: `_refresh_table` counts `live_filtered` but discards it)

### 4. `on_row_selected()` — **Zero tests**
`eddn_tail.py:459-474`

No test verifies that selecting a row shows the raw JSON detail, scrolls the detail pane to top, or handles missing keys gracefully.

### 5. `on_filter_changed()` — **Zero tests**
`eddn_tail.py:476-484`

No test verifies that typing in the filter input:
- Updates `_live_filter` and `_live_filter_pattern`
- Calls `_refresh_table()`
- Skips update when `_limit_input_mode` is True

### 6. `action_set_limit()` — **Zero tests**
`eddn_tail.py:559-569`

No test for:
- Setting `_limit_input_mode = True`
- Pre-filling the input with the current limit
- Showing/hiding the filter bar
- The `Input.Changed` side effect that corrupts live filter (known bug)

### 7. `on_filter_submitted()` — **Zero tests**
`eddn_tail.py:495-507`

No test for:
- Normal filter submission closing the bar
- Limit input mode applying the limit
- Restoring `can_focus = False` and hiding the bar

### 8. `action_export_json()` — **Zero tests**
`eddn_tail.py:584-607`

No test for:
- Successful export to a temp file
- "No row selected" edge case
- File write error handling
- Cursor coordinate lookup logic

### 9. `action_toggle_pause()`, `action_toggle_detail()`, `action_focus_filter()`, `action_clear_filter()`, `action_cursor_up()`, `action_cursor_down()` — **Zero tests**

### 10. `_compile_live_filter()` — **Only indirectly tested**
`eddn_tail.py:288-295`

No direct unit test. Only exercised through `_matches_filters` tests. Missing:
- `re.error` returns `None` (partially tested via `_matches_live_filter` fallback, but `_compile_live_filter` returning `None` on invalid regex is not explicitly verified)
- Empty string returns `None`
- Valid regex returns a compiled `re.Pattern` with `re.IGNORECASE`

---

## Weak Assertions & Test Quality Issues

### 11. `TestClearEvents` uses mock `query_one` that doesn't assert widget interactions
`tests/test_eddn_tail.py:703-810`

The `_FakeWidget` mock (line 813-817) has `clear()` and `update()` as no-ops. Only `test_clear_events_clears_table_and_detail` (line 742) actually tracks whether `clear()` and `update("")` were called. The other 4 tests in this class use `app.query_one = lambda selector, type=None: _FakeWidget()` which silently swallows all widget calls — verifying only state mutations, not UI side effects.

### 12. `EDDNReceiver` tests use `time.sleep(0.3)` for ZMQ handshake
`tests/test_eddn_tail.py:317`

This is fragile — on slow CI the handshake may not complete in 300ms, causing flaky test failures. No retry or exponential backoff.

### 13. `test_timeout_returns_none` creates a second EDDNReceiver
`tests/test_eddn_tail.py:343`

Line 345: `receiver = EDDNReceiver(url)` — this creates a **second** SUB socket to the same PUB endpoint, while the first receiver from `_setup_receiver` is not used. This is fine functionally, but the test creates two ZMQ contexts (one in `_setup_receiver`, one implicitly), and only closes the second. The first `ctx` leak is in the timeout test's setup helper — actually, `_bind_zmq_pub` is called directly (not `_setup_receiver`), so there's only one PUB and one SUB. However, line 346-347: the `time.sleep(0.15)` may be insufficient for the SUB handshake, potentially causing the test to receive a message instead of timing out.

### 14. `_matches_filters` tests don't test the actual storage/discard in `_poll_messages`
The `TestLiveFilterDiscardOnArrival` class tests only the predicate functions, not the actual message flow. The test names imply integration behavior ("test_no_filter_stores_everything", "test_live_filter_discards_non_matching") but they only verify `_matches_*()` returns `True`/`False`. No test verifies that `_poll_messages` actually:
- Adds matching messages to `_messages`
- Increments `_filtered_count` on discard
- Skips adding non-matching messages

### 15. No test for the `_error` dict handling in `_poll_messages`
`eddn_tail.py:372`: `if "_error" in msg: continue` — this path skips error messages. No test injects an `_error` dict and verifies it's not added to `_messages`.

---

## Untested Edge Cases

### 16. Station/body priority in `_format_row`
`eddn_tail.py:313-315`:
```python
location = summary["station"] or summary["body"]
if summary["star_class"] and summary["event"] == "FSDJump":
    location = f"[{summary['star_class']}]"
```
No test covers:
- When both `station` and `body` are present, station takes priority
- When only `body` is present (Scan events)
- When `star_class` is present but event is not FSDJump (should show station/body, not star class)
- When FSDJump has both station and star_class (star_class wins)

### 17. Timestamp edge cases in `_format_row`
`eddn_tail.py:303-310`:
- Empty timestamp string → `"??"`
- `None` timestamp → `"??"`  
- Malformed timestamp string (e.g., `"not-a-date"`) → `ts[:8]`

### 18. `EDDNReceiver.recv_message()` with `ZMQError`
`eddn_tail.py:95`: `except zmq.ZMQError: return None` — no test triggers this path.

### 19. `EDDNReceiver.__init__` topic_filter parameter
`eddn_tail.py:81`: The `topic_filter` argument is accepted but no test verifies it's set on the SUB socket or that it filters messages.

### 20. `_matches_live_filter` with regex that matches empty string
A pattern like `.*` or `(|)` would match everything, but no edge-case tests verify this. Similarly, patterns with `^`/`$` anchors are untested.

### 21. `_apply_limit_from_input` with whitespace-only input
`eddn_tail.py:570`: `value = event.input.value.strip()` happens in the caller, but `_apply_limit_from_input("  ")` would hit `ValueError` and show an error notification. Not tested.

### 22. `_enforce_limit` called from `_apply_limit_from_input` but `popitem` order not tested against `_refresh_table`
`eddn_tail.py:554-557`: After enforcement, `_refresh_table` is called, but no test verifies that the table state and `_messages` dict stay in sync after limit lowering.

---

## Test Isolation Issues

### 23. `TestEDDNReceiver` doesn't clean up PUB socket on failure
`tests/test_eddn_tail.py:317-330`

If `recv_message()` raises an unexpected exception, `pub.close()` and `ctx.term()` never execute. The `receiver.close()` call also may not execute. Should use `try/finally` or a fixture.

### 24. ZMQ context leaks in timeout test
`tests/test_eddn_tail.py:343-353`

`test_timeout_returns_none` creates `ctx, pub, url = _bind_zmq_pub()` but then creates a **new** `EDDNReceiver(url)` with its own internal context. The PUB context is properly cleaned up, but the test would be cleaner with a fixture managing lifecycle.

### 25. Tests share no fixtures for app construction
Multiple test classes define `_make_app()` independently (lines 383, 530, 700, 976). The app construction pattern is repeated 4 times. Should be a shared fixture or factory.

---

## Mocking Gaps

### 26. No Textual app testing infrastructure
None of the integration tests mount a real Textual `App`. All widget interactions are mocked with `_FakeWidget` or monkeypatched (`app.query_one = lambda ...`). This means:
- CSS layout behavior is untested
- Binding actions are untested (no `action_*` method is tested through the framework)
- `compose()` is never called in tests
- `on_mount()` scheduler setup (`set_interval`) is never tested
- Message handlers (`on_row_selected`, `on_filter_changed`, etc.) are never tested

### 27. `_poll_messages` cannot be tested without Textual app
The method directly calls `self.query_one("#message-table", DataTable)` which requires a mounted app. No test infrastructure exists to simulate this, so the entire message flow is untested.

---

## Summary

| # | Severity | Finding |
|---|----------|---------|
| 1 | 🔴 Major | `_format_row()` — zero tests for timestamp parsing, color markup, FSDJump star_class, truncation |
| 2 | 🔴 Major | `_poll_messages()` — zero tests for message ingestion, batch processing, error skipping, auto-scroll |
| 3 | 🔴 Major | `_refresh_table()` — zero tests; rebuild logic unverified |
| 4 | 🟡 Medium | `on_row_selected`, `on_filter_changed`, `on_filter_submitted`, `action_set_limit`, `action_export_json`, and 5 other action methods — zero tests |
| 5 | 🟡 Medium | `_compile_live_filter()` — only indirectly tested |
| 6 | 🟡 Medium | `TestLiveFilterDiscardOnArrival` tests only predicates, not actual message flow; test names misleading |
| 7 | 🟡 Medium | Station/body/star_class priority in `_format_row` untested |
| 8 | 🟡 Medium | Timestamp edge cases untested (None, empty, malformed) |
| 9 | 🟡 Medium | `EDDNReceiver` `ZMQError` path untested; `topic_filter` parameter untested |
| 10 | 🟡 Medium | Regex edge cases untested (empty-string match, anchors) |
| 11 | 🟡 Medium | No Textual app test infrastructure; all widget methods untested through framework |
| 12 | 🔵 Minor | `TestClearEvents` mock swallows widget calls in 4/5 tests |
| 13 | 🔵 Minor | `time.sleep(0.3)` in ZMQ tests — fragile on slow CI |
| 14 | 🔵 Minor | ZMQ resource cleanup gaps on test failure |
| 15 | 🔵 Minor | Duplicated `_make_app()` factory across 4 test classes |
| 16 | 🔵 Minor | `_error` dict handling in `_poll_messages` untested |

**Overall:** The pure-function layer (`extract_summary`, `_matches_*`, `_enforce_limit`, arg parsing) is well-tested with 97 tests. The UI layer (`_format_row`, `_poll_messages`, all action handlers, all event handlers) has virtually no test coverage. The test suite covers ~30% of the codebase's behavioral surface.