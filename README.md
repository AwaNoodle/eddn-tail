# EDDN Tail

A KinesisTail-like TUI for monitoring the Elite Dangerous Data Network (EDDN) live stream in your terminal.

Connects to EDDN's ZeroMQ PUB/SUB relay and displays all messages flowing through the network in real-time - useful for verifying your own submissions or just watching the galaxy's data flow.

![EDDN Tail Demo](demo.gif)

## Installation

```bash
pip install eddn-tail
```

Or install from source:

```bash
pip install .
```

Or run directly without installing:

```bash
python eddn_tail.py [options]
```

## Usage

```bash
# Watch all EDDN messages
eddn-tail

# Filter to Scan events only
eddn-tail -f Scan

# Filter by system name
eddn-tail -s Sol

# Filter by station name
eddn-tail -t Jameson Memorial

# Filter by schema
eddn-tail -S commodity/3

# Combine filters (AND logic)
eddn-tail -f FSDJump -s Sol

# Limit stored events (default: 500, max: 1999)
eddn-tail -l 1000

# Connect to beta EDDN
eddn-tail --beta

# Connect to dev EDDN
eddn-tail --dev

# Show all options and examples
eddn-tail --help
```

## Keybindings

| Key | Action |
|-----|--------|
| `/` | Focus filter input (regex supported) |
| `Esc` | Clear filter |
| `p` | Pause/resume stream |
| `d` | Toggle detail pane |
| `e` | Export selected message JSON to file |
| `Alt+L` | Set event storage limit (1–1999) |
| `Ctrl+L` | Clear all received events |
| `↑/↓` | Navigate rows |
| `Enter` | Show full message detail |
| `q` | Quit |

## How it works

EDDN is a publish/subscribe message relay. When tools (like EDMC, EDDI, or Decky plugins) upload data to `https://eddn.edcd.io:4430/upload/`, the EDDN Gateway validates the message and broadcasts it over a ZeroMQ PUB socket on port 9500. This tool subscribes to that stream, decompresses the zlib-encoded JSON, and displays it in a scrollable, filterable TUI.

| Service | Upload URL | Listener (ZMQ) |
|---------|-----------|----------------|
| Live | `https://eddn.edcd.io:4430/upload/` | `tcp://eddn.edcd.io:9500` |
| Beta | `https://beta.eddn.edcd.io:4431/upload/` | `tcp://beta.eddn.edcd.io:9510` |
| Dev | `https://dev.eddn.edcd.io:4432/upload/` | `tcp://dev.eddn.edcd.io:9520` |

### About the uploaderID column

EDDN relays do not broadcast the original uploaderID. The relay hashes it with a rotating nonce every 3 minutes (`SHA-1(nonce + "-" + uploaderID)`) before broadcasting, so the values shown in the Uploader column are 40-character hex strings - not commander names. Because the hash changes every 3 minutes, there is no reliable way to filter by uploader from the CLI. Use the in-app live filter (`/`) for short-term substring matching on any visible column value.

### Event storage limit

By default, `eddn-tail` retains up to **500 events** in memory. When the limit is reached, the oldest events are dropped (FIFO). You can change this at startup with `-l`/`--limit` (range: 1–1999) or at runtime with `Alt+L`. Lowering the limit at runtime immediately prunes excess events to the new cap.

When a **live filter** (`/`) is active, messages that don't match the filter are **discarded on arrival** - they are never stored. This means the storage limit applies only to messages you're actually interested in. Messages already in memory before the filter was activated remain until they age out via FIFO.

To inspect a message's full JSON payload, select a row and press Enter, or press `e` to export it to a file.

## EDDN message format

Messages on the wire are zlib-compressed JSON with this structure:

```json
{
  "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
  "header": {
    "uploaderID": "<40-char SHA-1 hash, rotates every 3 min>",
    "softwareName": "...",
    "softwareVersion": "...",
    "gameversion": "...",
    "gamebuild": "...",
    "gatewayTimestamp": "2026-05-10T22:36:19.745292Z"
  },
  "message": {
    "event": "Scan",
    "StarSystem": "Sol",
    ...
  }
}
```

Supported schemas: `journal/1`, `commodity/3`, `outfitting/2`, `shipyard/2`.

## Development

```bash
uv sync --extra dev
uv run pytest
```

## License

MIT © AwaNoodle