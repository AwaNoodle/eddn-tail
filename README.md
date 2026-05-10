# EDDN Tail

A KinesisTail-like TUI for monitoring the Elite Dangerous Data Network (EDDN) live stream in your terminal.

Connects to EDDN's ZeroMQ PUB/SUB relay and displays all messages flowing through the network in real-time — useful for verifying your own submissions or just watching the galaxy's data flow.

## Requirements

```
pip install pyzmq textual rich
```

## Usage

```bash
# Watch all EDDN messages
python eddn_tail.py

# Filter to Scan events only
python eddn_tail.py -f Scan

# Filter to your uploaderID (see your own submissions)
python eddn_tail.py -u <your_uploader_id>

# Filter by system name
python eddn_tail.py -s Sol

# Filter by station name
python eddn_tail.py -t Jameson Memorial

# Filter by schema
python eddn_tail.py -S commodity/3

# Combine filters (AND logic)
python eddn_tail.py -f FSDJump -s Sol

# Connect to beta EDDN
python eddn_tail.py --beta

# Connect to dev EDDN
python eddn_tail.py --dev
```

## Keybindings

| Key | Action |
|-----|--------|
| `/` | Focus filter input (regex supported) |
| `Esc` | Clear filter |
| `p` | Pause/resume stream |
| `d` | Toggle detail pane |
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

### Verifying your own submissions

1. Start `eddn_tail.py -u <your_uploader_id>` on any machine with internet access
2. Run your EDDN sender tool (EDMC, Decky plugin, etc.)
3. Watch the TUI — your submissions appear in real-time
4. Select any row to inspect the full JSON payload

This confirms **end-to-end delivery**: your tool → EDDN upload → EDDN relay → your listener.

## EDDN message format

Messages on the wire are zlib-compressed JSON with this structure:

```json
{
  "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
  "header": {
    "uploaderID": "...",
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

## License

MIT
