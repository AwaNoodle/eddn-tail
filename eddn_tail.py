#!/usr/bin/env python3
"""
EDDN Tail - A KinesisTail-like TUI for monitoring the EDDN live stream.

Connects to the EDDN ZeroMQ PUB/SUB relay, decompresses messages,
and displays them in a filterable terminal UI.

Usage:
    eddn-tail                        # Watch all messages
    eddn-tail -f Scan                # Filter to Scan events
    eddn-tail -f FSDJump             # Filter to FSDJump events
    eddn-tail -s Sol                 # Filter by system name
    eddn-tail --beta                 # Connect to beta EDDN

Requirements:
    pip install .
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zlib
from collections import OrderedDict
from datetime import datetime, timezone

import zmq

try:
    from rich.markup import escape as rich_escape
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.css.query import NoMatches
    from textual.timer import Timer
    from textual.widgets import DataTable, Footer, Header, Input, Static
except ImportError:
    print("eddn_tail requires pyzmq, textual, and rich: pip install .", file=sys.stderr)
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

# Derived event names for non-journal schemas (they lack an "event" field)
SCHEMA_EVENT = {
    "commodity/3": "commodity",
    "outfitting/2": "outfitting",
    "shipyard/2": "shipyard",
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
        self._sock.RCVTIMEO = 100  # ms - short timeout for responsive cancellation

    def recv_message(self) -> dict | None:
        """Receive a single message. Returns None on timeout."""
        try:
            raw = self._sock.recv()
            decompressed = zlib.decompress(raw)
            return json.loads(decompressed)
        except zmq.Again:
            return None
        except zmq.ZMQError:
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

    # Schema short name (needed for derived event names)
    schema_short = SCHEMA_SHORT.get(schema_ref, "/".join(schema_ref.rsplit("/", 2)[-2:]) if schema_ref.count("/") >= 2 else schema_ref)

    # Extract event type - for journal schemas, use the event field;
    # for non-journal schemas, derive from schema name
    event = message.get("event", "") or SCHEMA_EVENT.get(schema_short, "")

    # Extract system/station - journal uses StarSystem/StationName (capitalized),
    # non-journal schemas use systemName/stationName (lowercase)
    system = message.get("StarSystem", message.get("SystemName", message.get("systemName", "")))
    station = message.get("StationName", message.get("stationName", ""))

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
    }


# Event storage limit constants
MIN_EVENT_LIMIT = 1
MAX_EVENT_LIMIT = 1999
DEFAULT_EVENT_LIMIT = 500


class EDDNTailApp(App):
    """A KinesisTail-like TUI for the EDDN stream."""

    TITLE = "EDDN Tail"
    CSS = """
    #message-pane {
        height: 1fr;
        border: solid $primary;
        border-title-align: center;
    }
    #message-pane:focus-within {
        border: heavy $accent;
    }
    #message-table {
        height: 1fr;
    }
    #detail-pane {
        height: 1fr;
        max-height: 40%;
        border: solid $primary;
        border-title-align: center;
    }
    #detail-pane:focus-within {
        border: heavy $accent;
    }
    #filter-bar {
        dock: top;
        height: auto;
        padding: 0 2;
        background: $surface;
        border: solid $accent;
        display: none;
    }
    #filter-input {
        width: 1fr;
    }
    #detail-content {
        height: auto;
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
        Binding("e", "export_json", "Export JSON", show=True),
        Binding("ctrl+l", "clear_events", "Clear Events", show=True),
        Binding("alt+l", "set_limit", "Set Limit", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
    ]

    def __init__(
        self,
        endpoint: str = EDDN_ENDPOINTS["live"],
        event_filter: str = "",
        system_filter: str = "",
        station_filter: str = "",
        schema_filter: str = "",
        initial_limit: int = 500,
    ):
        super().__init__()
        self._endpoint = endpoint
        self._endpoint_name = next(
            (k for k, v in EDDN_ENDPOINTS.items() if v == endpoint), endpoint
        )
        self._event_filter = event_filter.lower()
        self._system_filter = system_filter.lower()
        self._station_filter = station_filter.lower()
        self._schema_filter = schema_filter.lower()
        self._max_event_limit = initial_limit
        self._limit_input_mode = False
        self._receiver: EDDNReceiver | None = None
        self._poll_timer: Timer | None = None
        self._stats_timer: Timer | None = None
        self._paused = False
        self._show_detail = True
        self._msg_count = 0
        self._filtered_count = 0
        self._app_start_time = datetime.now(timezone.utc)
        self._live_filter = ""
        self._live_filter_pattern: re.Pattern | None = None
        self._messages: OrderedDict[str, dict] = OrderedDict()
        self._raw_messages: OrderedDict[str, dict] = OrderedDict()
        self._live_hidden_count = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="filter-bar"):
            yield Input(
                placeholder="Filter: event, system, station, uploader, schema (regex supported)...",
                id="filter-input",
            )
        with Vertical(id="message-pane"):
            yield DataTable(id="message-table")
        with VerticalScroll(id="detail-pane"):
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
        table.focus()

        # Filter input should only be reachable via /, not Tab
        self.query_one("#filter-input", Input).can_focus = False

        # Set initial border titles
        self._update_pane_titles()

        # Start the receiver
        self._receiver = EDDNReceiver(self._endpoint)
        self._poll_timer = self.set_interval(0.05, self._poll_messages)

        # Update stats and pane titles
        self._stats_timer = self.set_interval(1.0, self._update_stats)

    def on_unmount(self) -> None:
        # Stop the timers before the widget tree goes away. A tick that lands
        # mid-teardown would query widgets that no longer exist and raise
        # NoMatches.
        for timer in (self._poll_timer, self._stats_timer):
            if timer is not None:
                timer.stop()
        self._poll_timer = None
        self._stats_timer = None

        if self._receiver:
            self._receiver.close()
            self._receiver = None

    def _compile_live_filter(self) -> re.Pattern | None:
        """Compile the live filter string into a regex pattern, or None if invalid."""
        if not self._live_filter:
            return None
        try:
            return re.compile(self._live_filter, re.IGNORECASE)
        except re.error:
            return None

    @staticmethod
    def _format_row(summary: dict) -> tuple:
        """Format a message summary into a tuple of row values for DataTable."""
        ts = summary["gateway_ts"]
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M:%S")
        except (ValueError, AttributeError):
            time_str = ts[:8] if ts else "??"

        schema_label = summary["schema"]
        color = SCHEMA_COLORS.get(schema_label, "white")

        location = summary["station"] or summary["body"]
        if summary["star_class"] and summary["event"] == "FSDJump":
            location = f"[{summary['star_class']}]"

        return (
            time_str,
            f"[{color}]{schema_label}[/{color}]",
            summary["event"],
            summary["system"],
            location,
            summary["uploader_id"][:12],
            summary["software"][:20],
        )

    def _matches_cli_filters(self, summary: dict) -> bool:
        """Check if a message matches the CLI filters (--event, --system, etc.).

        These are static filters set at startup - messages that fail
        are permanently discarded and never stored.
        """
        if self._event_filter and self._event_filter not in summary["event"].lower():
            return False
        if self._system_filter and self._system_filter not in summary["system"].lower():
            return False
        if self._station_filter and self._station_filter not in summary["station"].lower():
            return False
        if self._schema_filter and self._schema_filter not in summary["schema"].lower():
            return False
        return True

    def _matches_live_filter(self, summary: dict) -> bool:
        """Check if a message matches the live (interactive) filter.

        The live filter changes at runtime. When a live filter is active,
        non-matching messages are discarded on arrival (never stored),
        so the storage pool only contains messages that matched the filter
        at the time they arrived. Existing messages from before a filter
        change remain in storage until evicted by FIFO or a filter change.
        """
        if not self._live_filter:
            return True
        haystack = " ".join([
            summary["event"], summary["system"], summary["station"],
            summary["body"], summary["uploader_id"], summary["schema"],
            summary["software"],
        ]).lower()
        if self._live_filter_pattern:
            return self._live_filter_pattern.search(haystack) is not None
        return self._live_filter.lower() in haystack

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

            if not self._matches_cli_filters(summary):
                self._filtered_count += 1
                continue

            # --- Live filter: discard non-matching messages on arrival ---
            if self._live_filter and not self._matches_live_filter(summary):
                continue

            # --- Limit enforcement (FIFO): drop oldest if at capacity ---
            while len(self._messages) >= self._max_event_limit:
                oldest_key, _ = self._messages.popitem(last=False)
                self._raw_messages.pop(oldest_key, None)
                try:
                    table.remove_row(oldest_key)
                except Exception:
                    pass  # row may have been live-filtered out of the table

            # Store for detail view (keyed by string for DataTable lookup)
            msg_key = str(self._msg_count)
            self._messages[msg_key] = summary
            self._raw_messages[msg_key] = msg

            table.add_row(*self._format_row(summary), key=msg_key)

        # Auto-scroll: move cursor once after the batch if near the bottom
        total_rows = len(table.rows)
        if total_rows > 0:
            try:
                if table.cursor_row >= total_rows - 2:
                    table.move_cursor(row=total_rows - 1)
            except Exception:
                pass

    def _refresh_table(self) -> None:
        """Rebuild the table from stored messages, applying current filters."""
        table = self.query_one("#message-table", DataTable)
        table.clear()

        live_hidden = 0
        for msg_key, summary in self._messages.items():
            if not self._matches_cli_filters(summary) or not self._matches_live_filter(summary):
                live_hidden += 1
                continue

            table.add_row(*self._format_row(summary), key=msg_key)
        self._live_hidden_count = live_hidden

    def _update_pane_titles(self) -> None:
        """Update border titles on both panes to reflect state."""
        msg_pane = self.query_one("#message-pane", Vertical)
        status_icon = "⏸" if self._paused else "▶"
        has_filter = any([self._event_filter, self._system_filter,
                         self._station_filter, self._schema_filter, self._live_filter])
        filter_tag = " [dim]\\[filtered][/dim]" if has_filter else ""
        msg_pane.border_title = f"{status_icon} Messages - {'Paused' if self._paused else self._endpoint_name.title()}{filter_tag}"

        detail_pane = self.query_one("#detail-pane", VerticalScroll)
        detail_pane.border_title = "Message Detail"

    def _update_stats(self) -> None:
        """Update the stats bar."""
        elapsed = (datetime.now(timezone.utc) - self._app_start_time).total_seconds()
        rate = self._msg_count / elapsed if elapsed > 0 else 0
        try:
            stats = self.query_one("#stats-bar", Static)
            table = self.query_one("#message-table", DataTable)
        except NoMatches:
            # The interval can tick while the app is tearing down, after the
            # widgets have gone. Nothing to update in that case.
            return
        shown = len(table.rows)
        status = "⏸ PAUSED" if self._paused else "▶ LIVE"
        total_dropped = self._filtered_count + self._live_hidden_count
        filter_info = ""
        if any([self._event_filter, self._system_filter,
                self._station_filter, self._schema_filter, self._live_filter]) or total_dropped > 0:
            filter_info = f" | Dropped: {total_dropped}"
        stats.update(
            f"{status} │ {self._endpoint_name} │ "
            f"Total: {self._msg_count} │ Shown: {shown} │ "
            f"Limit: {len(self._messages)}/{self._max_event_limit} │ "
            f"Rate: {rate:.1f}/s{filter_info}"
        )
        self._update_pane_titles()

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Show detail for selected row."""
        if not self._show_detail:
            return
        # Look up the message by its row key string
        msg_key = event.row_key.value
        if msg_key is not None and msg_key in self._raw_messages:
            raw = self._raw_messages[msg_key]
            detail = self.query_one("#detail-content", Static)
            # Escape Rich markup in JSON (brackets are interpreted as tags)
            raw_json = self._format_raw_json(raw)
            # Show only the raw JSON - no header, no truncation
            detail.update(rich_escape(raw_json))
            # Scroll detail pane back to top for new selection
            self.query_one("#detail-pane", VerticalScroll).scroll_home(animate=False)

    @on(Input.Changed)
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Update live filter from input and re-apply to displayed messages."""
        if self._limit_input_mode:
            return  # Don't filter while user is typing a limit value
        self._live_filter = event.value.strip()
        self._live_filter_pattern = self._compile_live_filter()
        self._refresh_table()
        self._update_pane_titles()

    @on(Input.Blurred)
    def on_filter_blur(self, event: Input.Blurred) -> None:
        """When filter input loses focus, hide the filter bar and remove from Tab cycle."""
        if event.input.id == "filter-input":
            self._limit_input_mode = False
            event.input.placeholder = "Filter: event, system, station, uploader, schema (regex supported)..."
            event.input.can_focus = False
            self.query_one("#filter-bar").display = False

    @on(Input.Submitted)
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        """When Enter is pressed in the filter input, apply and close the popup."""
        if event.input.id == "filter-input":
            if self._limit_input_mode:
                value = event.input.value.strip()
                self._apply_limit_from_input(value)
                event.input.value = ""
                event.input.placeholder = "Filter: event, system, station, uploader, schema (regex supported)..."
                self._limit_input_mode = False
            # else: normal filter - value already applied via Input.Changed
            event.input.can_focus = False
            self.query_one("#filter-bar").display = False
            self.query_one("#message-table", DataTable).focus()

    def action_focus_filter(self) -> None:
        filter_bar = self.query_one("#filter-bar")
        filter_bar.display = True
        inp = self.query_one("#filter-input", Input)
        inp.can_focus = True
        inp.focus()

    def action_clear_filter(self) -> None:
        self._live_filter = ""
        self._live_filter_pattern = None
        self.query_one("#filter-input", Input).value = ""
        self.query_one("#filter-bar").display = False
        # Note: setting inp.value fires Input.Changed which calls _refresh_table
        self._update_pane_titles()
        self.query_one("#message-table", DataTable).focus()

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        self._update_pane_titles()

    def action_toggle_detail(self) -> None:
        self._show_detail = not self._show_detail
        detail = self.query_one("#detail-pane", VerticalScroll)
        detail.display = self._show_detail
        # When detail is hidden, let messages pane take the full height
        msg_pane = self.query_one("#message-pane", Vertical)
        if self._show_detail:
            msg_pane.styles.height = "1fr"
            detail.styles.max_height = "40%"
        else:
            msg_pane.styles.height = "1fr"
            detail.styles.max_height = "0%"

    def action_clear_events(self) -> None:
        """Clear all received events and reset the app to a clean state."""
        self._messages.clear()
        self._raw_messages.clear()
        self._msg_count = 0
        self._filtered_count = 0
        self._live_hidden_count = 0
        self._app_start_time = datetime.now(timezone.utc)
        self.query_one("#message-table", DataTable).clear()
        self.query_one("#detail-content", Static).update("")
        self._update_pane_titles()
        self._update_stats()
        self.notify("Events cleared")

    def _enforce_limit(self) -> None:
        """Evict oldest messages if storage exceeds the configured limit."""
        while len(self._messages) > self._max_event_limit:
            self._messages.popitem(last=False)
            self._raw_messages.popitem(last=False)

    def action_set_limit(self) -> None:
        """Prompt the user to set a new event storage limit via the filter bar."""
        self._limit_input_mode = True
        filter_bar = self.query_one("#filter-bar")
        filter_bar.display = True
        inp = self.query_one("#filter-input", Input)
        inp.can_focus = True
        inp.placeholder = f"Enter new limit ({MIN_EVENT_LIMIT}-{MAX_EVENT_LIMIT}), then press Enter..."
        inp.value = str(self._max_event_limit)
        inp.focus()

    def _apply_limit_from_input(self, value: str) -> None:
        """Validate and apply a new limit from the input bar."""
        try:
            new_limit = int(value)
            if MIN_EVENT_LIMIT <= new_limit <= MAX_EVENT_LIMIT:
                self._max_event_limit = new_limit
                self._enforce_limit()
                self._refresh_table()
                self.notify(f"Limit updated to {new_limit}")
            else:
                self.notify(f"Limit must be {MIN_EVENT_LIMIT}-{MAX_EVENT_LIMIT}", severity="error")
        except ValueError:
            self.notify("Invalid limit: must be an integer", severity="error")

    @staticmethod
    def _format_raw_json(raw: dict) -> str:
        """Format raw message dict as pretty-printed JSON."""
        return json.dumps(raw, indent=2, ensure_ascii=False)

    def action_export_json(self) -> None:
        """Export the currently selected message's JSON to a file."""
        table = self.query_one("#message-table", DataTable)
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
            msg_key = cell_key.row_key.value
        except Exception:
            self.notify("No row selected", severity="warning")
            return
        if msg_key is not None and msg_key in self._raw_messages:
            raw = self._raw_messages[msg_key]
            raw_json = self._format_raw_json(raw)
            # Write to eddn_export_<timestamp>.json in current directory
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"eddn_export_{ts}.json"
            filepath = os.path.join(os.getcwd(), filename)
            try:
                with open(filepath, "w") as f:
                    f.write(raw_json)
                self.notify(f"Exported to {filepath}")
            except OSError as exc:
                self.notify(f"Export failed: {exc}", severity="error")
        else:
            self.notify("No message at selected row", severity="warning")

    def action_cursor_up(self) -> None:
        table = self.query_one("#message-table", DataTable)
        try:
            table.move_cursor(row=max(0, table.cursor_row - 1))
        except Exception:
            pass

    def action_cursor_down(self) -> None:
        table = self.query_one("#message-table", DataTable)
        if len(table.rows) == 0:
            return
        try:
            table.move_cursor(row=min(len(table.rows) - 1, table.cursor_row + 1))
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for eddn-tail."""
    parser = argparse.ArgumentParser(
        description="EDDN Tail - monitor the EDDN live stream in your terminal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  eddn-tail                            Watch all EDDN messages
  eddn-tail -f Scan                    Filter to Scan events only
  eddn-tail -f FSDJump                 Filter to FSDJump events
  eddn-tail -s Sol                     Filter by system name
  eddn-tail --beta                     Connect to beta EDDN
  eddn-tail -f Scan -s Sol             Combine filters (AND logic)

Note on uploaderID:
  EDDN relays hash uploaderID values before broadcast (SHA-1 with a
  rotating nonce that changes every 3 minutes), so the Uploader column
  shows 40-character hex strings - not commander names. Since the hash
  rotates, -u filtering is unreliable and has been removed. Use the
  live filter (/) for short-term matching on any column value.

In-app keybindings:
  /       Focus the filter input (live regex filter)
  Esc     Clear filter
  p       Pause/resume stream
  d       Toggle detail pane
  e       Export selected message JSON to file
  Ctrl+L  Clear all received events
  ↑/↓     Navigate rows
  Enter   Show message detail
  q       Quit
""",
    )
    parser.add_argument("-f", "--event", default="", help="Filter by journal event name using substring matching (e.g. Scan matches Scan and ScanBaryCentre)")
    parser.add_argument("-s", "--system", default="", help="Filter by system name")
    parser.add_argument("-t", "--station", default="", help="Filter by station name")
    parser.add_argument("-S", "--schema", default="", help="Filter by schema (e.g. journal/1, commodity/3)")
    parser.add_argument("-l", "--limit", default=DEFAULT_EVENT_LIMIT, type=int,
                        help=f"Maximum events to store ({MIN_EVENT_LIMIT}-{MAX_EVENT_LIMIT}, default: {DEFAULT_EVENT_LIMIT})")
    parser.add_argument("--beta", action="store_true", help="Connect to beta EDDN endpoint")
    parser.add_argument("--dev", action="store_true", help="Connect to dev EDDN endpoint")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.beta and args.dev:
        parser.error("--beta and --dev are mutually exclusive")

    if args.beta:
        endpoint = EDDN_ENDPOINTS["beta"]
    elif args.dev:
        endpoint = EDDN_ENDPOINTS["dev"]
    else:
        endpoint = EDDN_ENDPOINTS["live"]

    limit = args.limit
    if not (MIN_EVENT_LIMIT <= limit <= MAX_EVENT_LIMIT):
        parser.error(f"--limit must be between {MIN_EVENT_LIMIT} and {MAX_EVENT_LIMIT}, got {limit}")

    app = EDDNTailApp(
        endpoint=endpoint,
        event_filter=args.event,
        system_filter=args.system,
        station_filter=args.station,
        schema_filter=args.schema,
        initial_limit=limit,
    )
    app.run()


if __name__ == "__main__":
    main()
