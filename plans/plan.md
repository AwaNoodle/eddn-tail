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