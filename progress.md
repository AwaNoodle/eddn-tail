# Progress: eddn-tail correctness review

## Completed
- Read `eddn_tail.py` and `tests/test_eddn_tail.py`
- Ran all 57 tests (all passing)
- Wrote correctness review to `reviews/correctness.md`

## Key Findings
- **Blocker:** Live filter permanently discards messages — changing/clearing the live filter cannot reveal previously-filtered-out messages because they're never stored in `_messages`.
- **Bug:** Auto-scroll every 50ms prevents manual row navigation.
- **Bug:** `_filtered_count` never adjusted on live filter change; only increments.
- **Notes:** Substring matching on CLI filters, unbounded memory growth, duplicated FSDJump display logic, cursor edge case on empty table.

## Status
Review complete. Findings written to `reviews/correctness.md`.