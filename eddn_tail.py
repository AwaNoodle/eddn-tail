#!/usr/bin/env python3
"""
EDDN Tail — A KinesisTail-like TUI for monitoring the EDDN live stream.

Connects to the EDDN ZeroMQ PUB/SUB relay, decompresses messages,
and displays them in a filterable terminal UI.

Usage:
    eddn_tail.py                    # Watch all messages
    eddn_tail.py -f Scan            # Filter to Scan events
    eddn_tail.py -f FSDJump         # Filter to FSDJump events
    eddn_tail.py -u myuploaderid    # Filter by uploaderID
    eddn_tail.py -s Sol             # Filter by system name
    eddn_tail.py --beta             # Connect to beta EDDN

Requirements:
    pip install pyzmq textual rich
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import zlib
from datetime import datetime, timezone
from typing import Optional

import zmq

try:
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Footer, Header, Input, Static, DataTable
    from textual.widgets.data_table import RowKey
except ImportError:
    print("eddn_tail requires textual and rich: pip install textual rich", file=sys.stderr)
    sys.exit(1)

# EDDN endpoints
EDDN_ENDPOINTS = {
    "live": "tcp://eddn.edcd.io:9500",
    "beta": "tcp://beta.eddn.edcd.io:9510",
    "dev": "tcp://dev.eddn.edcd.io:9520",
}

# Schema short names for display
SCHEMA_SHORT = {
    "https://eddn.edcd.io/schemas/journal/1": "journal/1",
    "https://eddn.edcd.io/schemas/commodity/3": "commodity/3",
    "https://eddn.edcd.io/schemas/outfitting/2": "outfitting/2",
    "https://eddn.edcd.io/schemas/shipyard/2": "shipyard/2",
}

# Color map for schemas
SCHEMA_COLORS = {
    "journal/1": "cyan",
    "commodity/3": "green",
    "outfitting/2": "yellow",
    "shipyard/2": "magenta",
}


class EDDNReceiver:
    """ZeroMQ SUB socket that receives and decompresses EDDN messages."""

    def __init__(self, endpoint: str, topic_filter: str = ""):
        self._ctx = zmq.Context()
        self._sock = self._ctx.socket(zmq.SUB)
        self._sock.connect(endpoint)
        self._sock.setsockopt_string(zmq.SUBSCRIBE, topic_filter)
        self._sock.RCVTIMEO = 100  # ms — short timeout for responsive cancellation

    def recv_message(self) -> Optional[dict]:
        """Receive a single message. Returns None on timeout."""
        try:
            raw = self._sock.recv()
            decompressed = zlib.decompress(raw)
            return json.loads(decompressed)
        except zmq.Again:
            return None
        except (zlib.error, json.JSONDecodeError) as e:
            return {"_error": str(e)}

    def close(self):
        self._sock.close(linger=0)
        self._ctx.term()


def extract_summary(msg: dict) -> dict:
    """Extract key fields from an EDDN message for display."""
    header = msg.get("header", {})
    message = msg.get("message", {})
    schema_ref = msg.get("$schemaRef", "")

    # Extract event type
    event = message.get("event", "")

    # Extract system/station
    system = message.get("StarSystem", message.get("SystemName", ""))
    station = message.get("StationName", "")

    # For Scan events, use BodyName
    body = message.get("BodyName", "")

    # For FSDJump, show StarClass and jumps count
    star_class = message.get("StarClass", "")

    # Uploader info
    uploader_id = header.get("uploaderID", "")
    software = header.get("softwareName", "")
    sw_version = header.get("softwareVersion", "")

    # Timestamp
    gateway_ts = header.get("gatewayTimestamp", "")
    journal_ts = message.get("timestamp", "")

    # Schema short name
    schema_short = SCHEMA_SHORT.get(schema_ref, schema_ref.rsplit("/", 1)[-1] if "/" in schema_ref else schema_ref)

    return {
        "schema": schema_short,
        "event": event,
        "system": system,
        "station": station,
        "body": body,
        "star_class": star_class,
        "uploader_id": uploader_id,
        "software": f"{software} {sw_version}".strip(),
        "gateway_ts": gateway_ts,
        "journal_ts": journal_ts,
        "raw": msg,
    }


class EDDNTailApp(App):
    """A KinesisTail-like TUI for the EDDN stream."""

    TITLE = "EDDN Tail"
    CSS = """
    #detail-pane {
        height: 40%;
        border: solid $primary;
    }
    #message-table {
        height: 60%;
    }
    #filter-bar {
        height: 3;
        margin: 0 1;
    }
    #filter-input {
        width: 1fr;
    }
    #stats-bar {
        height: 1;
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("slash", "focus_filter", "Filter", show=True),
        Binding("escape", "clear_filter", "Clear Filter", show=True),
        Binding("p", "toggle_pause", "Pause/Resume", show=True),
        Binding("d", "toggle_detail", "Toggle Detail", show=True),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
    ]

    def __init__(
        self,
        endpoint: str = EDDN_ENDPOINTS["live"],
        event_filter: str = "",
        uploader_filter: str = "",
        system_filter: str = "",
        station_filter: str = "",
        schema_filter: str = "",
    ):
        super().__init__()
        self._endpoint = endpoint
        self._event_filter = event_filter.lower()
        self._uploader_filter = uploader_filter.lower()
        self._system_filter = system_filter.lower()
        self._station_filter = station_filter.lower()
        self._schema_filter = schema_filter.lower()
        self._receiver: Optional[EDDNReceiver] = None
        self._paused = False
        self._show_detail = True
        self._msg_count = 0
        self._filtered_count = 0
        self._start_time = datetime.now(timezone.utc)
        self._live_filter = ""
        self._messages: list[dict] = []  # ring buffer
        self._max_messages = 1000

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="filter-bar"):
            yield Input(
                placeholder="Filter: event, system, station, uploader, schema (regex supported)...",
                id="filter-input",
            )
        yield DataTable(id="message-table")
        with Vertical(id="detail-pane"):
            yield Static("", id="detail-content")
        yield Static("", id="stats-bar")
        yield Footer()

    def on_mount(self) -> None:
        # Set up the table
        table = self.query_one("#message-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "Time", "Schema", "Event", "System", "Station/Body", "Uploader", "Software"
        )
        table.zebra_stripes = True

        # Start the receiver
        self._receiver = EDDNReceiver(self._endpoint)
        self.set_interval(0.05, self._poll_messages)

        # Update stats
        self.set_interval(1.0, self._update_stats)

    def on_unmount(self) -> None:
        if self._receiver:
            self._receiver.close()

    def _matches_filters(self, summary: dict) -> bool:
        """Check if a message matches all configured filters."""
        if self._event_filter and self._event_filter not in summary["event"].lower():
            return False
        if self._uploader_filter and self._uploader_filter not in summary["uploader_id"].lower():
            return False
        if self._system_filter and self._system_filter not in summary["system"].lower():
            return False
        if self._station_filter and self._station_filter not in summary["station"].lower():
            return False
        if self._schema_filter and self._schema_filter not in summary["schema"].lower():
            return False
        # Live filter (from input box) — match against multiple fields
        if self._live_filter:
            import re
            try:
                pattern = re.compile(self._live_filter, re.IGNORECASE)
            except re.error:
                pattern = None
            haystack = " ".join([
                summary["event"], summary["system"], summary["station"],
                summary["body"], summary["uploader_id"], summary["schema"],
                summary["software"],
            ]).lower()
            if pattern:
                if not pattern.search(haystack):
                    return False
            elif self._live_filter.lower() not in haystack:
                return False
        return True

    def _poll_messages(self) -> None:
        """Poll for new messages and add them to the table."""
        if self._paused or not self._receiver:
            return

        table = self.query_one("#message-table", DataTable)

        # Batch: receive up to 50 messages per poll
        for _ in range(50):
            msg = self._receiver.recv_message()
            if msg is None:
                break
            if "_error" in msg:
                continue

            self._msg_count += 1
            summary = extract_summary(msg)

            if not self._matches_filters(summary):
                self._filtered_count += 1
                continue

            # Store for detail view
            self._messages.append(summary)
            if len(self._messages) > self._max_messages:
                self._messages.pop(0)

            # Format time
            ts = summary["gateway_ts"]
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                time_str = dt.strftime("%H:%M:%S")
            except (ValueError, AttributeError):
                time_str = ts[:8] if ts else "??"

            # Schema with color label
            schema_label = summary["schema"]
            color = SCHEMA_COLORS.get(schema_label, "white")

            # Station/body display
            location = summary["station"] or summary["body"]
            if summary["star_class"] and summary["event"] == "FSDJump":
                location = f"[{summary['star_class']}]"

            row_key = RowKey(self._msg_count)
            table.add_row(
                time_str,
                f"[{color}]{schema_label}[/{color}]",
                summary["event"],
                summary["system"],
                location,
                summary["uploader_id"][:12],
                summary["software"][:20],
                key=row_key,
            )

            # Auto-scroll: move cursor to latest row
            try:
                table.move_cursor(row=len(table.rows) - 1)
            except Exception:
                pass

    def _update_stats(self) -> None:
        """Update the stats bar."""
        elapsed = (datetime.now(timezone.utc) - self._start_time).total_seconds()
        rate = self._msg_count / elapsed if elapsed > 0 else 0
        stats = self.query_one("#stats-bar", Static)
        shown = self._msg_count - self._filtered_count
        status = "⏸ PAUSED" if self._paused else "▶ LIVE"
        filter_info = ""
        if any([self._event_filter, self._uploader_filter, self._system_filter,
                self._station_filter, self._schema_filter, self._live_filter]):
            filter_info = f" | Filters: {self._filtered_count} dropped"
        endpoint_name = [k for k, v in EDDN_ENDPOINTS.items() if v == self._endpoint]
        endpoint_name = endpoint_name[0] if endpoint_name else self._endpoint
        stats.update(
            f"{status} │ {endpoint_name} │ "
            f"Total: {self._msg_count} │ Shown: {shown} │ "
            f"Rate: {rate:.1f}/s{filter_info}"
        )

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Show detail for selected row."""
        if not self._show_detail:
            return
        # Find the message by row index
        table = self.query_one("#message-table", DataTable)
        row_index = event.cursor_row
        if 0 <= row_index < len(self._messages):
            summary = self._messages[row_index]
            detail = self.query_one("#detail-content", Static)
            raw_json = json.dumps(summary["raw"], indent=2, ensure_ascii=False)
            # Truncate very long messages
            if len(raw_json) > 5000:
                raw_json = raw_json[:5000] + "\n... (truncated)"
            detail.update(f"[bold]Detail:[/bold] {summary['event']} — {summary['system']}\n\n{raw_json}")

    @on(Input.Changed)
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Update live filter from input."""
        self._live_filter = event.value.strip()

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_clear_filter(self) -> None:
        inp = self.query_one("#filter-input", Input)
        inp.value = ""
        self._live_filter = ""
        self.query_one("#message-table", DataTable).focus()

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused

    def action_toggle_detail(self) -> None:
        self._show_detail = not self._show_detail
        detail = self.query_one("#detail-pane", Vertical)
        detail.display = self._show_detail

    def action_cursor_up(self) -> None:
        table = self.query_one("#message-table", DataTable)
        try:
            table.move_cursor(row=max(0, table.cursor_row - 1))
        except Exception:
            pass

    def action_cursor_down(self) -> None:
        table = self.query_one("#message-table", DataTable)
        try:
            table.move_cursor(row=min(len(table.rows) - 1, table.cursor_row + 1))
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="EDDN Tail — monitor the EDDN live stream in your terminal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  eddn_tail.py                          Watch all EDDN messages
  eddn_tail.py -f Scan                  Filter to Scan events only
  eddn_tail.py -f FSDJump               Filter to FSDJump events
  eddn_tail.py -u my_uploader_id        Filter by uploaderID
  eddn_tail.py -s Sol                   Filter by system name
  eddn_tail.py --beta                   Connect to beta EDDN
  eddn_tail.py -f Scan -s Sol           Combine filters (AND logic)

In-app keybindings:
  /       Focus the filter input (live regex filter)
  Esc     Clear filter
  p       Pause/resume stream
  d       Toggle detail pane
  ↑/↓     Navigate rows
  Enter   Show message detail
  q       Quit
""",
    )
    parser.add_argument("-f", "--event", default="", help="Filter by journal event name (e.g. Scan, FSDJump)")
    parser.add_argument("-u", "--uploader", default="", help="Filter by uploaderID")
    parser.add_argument("-s", "--system", default="", help="Filter by system name")
    parser.add_argument("-t", "--station", default="", help="Filter by station name")
    parser.add_argument("-S", "--schema", default="", help="Filter by schema (e.g. journal/1, commodity/3)")
    parser.add_argument("--beta", action="store_true", help="Connect to beta EDDN endpoint")
    parser.add_argument("--dev", action="store_true", help="Connect to dev EDDN endpoint")
    args = parser.parse_args()

    if args.beta:
        endpoint = EDDN_ENDPOINTS["beta"]
    elif args.dev:
        endpoint = EDDN_ENDPOINTS["dev"]
    else:
        endpoint = EDDN_ENDPOINTS["live"]

    app = EDDNTailApp(
        endpoint=endpoint,
        event_filter=args.event,
        uploader_filter=args.uploader,
        system_filter=args.system,
        station_filter=args.station,
        schema_filter=args.schema,
    )
    app.run()


if __name__ == "__main__":
    main()
