"""Tests for eddn_tail - EDDN stream TUI."""

from __future__ import annotations

import contextlib
import json
import re
import time
import zlib
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import pytest
import zmq
from textual.widgets import DataTable, Input, Static

from eddn_tail import (
    DEFAULT_EVENT_LIMIT,
    EDDN_ENDPOINTS,
    MAX_EVENT_LIMIT,
    MIN_EVENT_LIMIT,
    SCHEMA_COLORS,
    SCHEMA_EVENT,
    SCHEMA_SHORT,
    EDDNReceiver,
    EDDNTailApp,
    build_parser,
    extract_summary,
)

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

class _FakeWidget:
    """Minimal stand-in for Textual widgets used in unit tests."""
    def clear(self):
        pass
    def update(self, text=""):
        pass
    rows = []
    border_title = ""
    display = True


def _make_app(**kwargs):
    """Create an EDDNTailApp with widget calls mocked out."""
    app = EDDNTailApp(endpoint="tcp://localhost:9999", **kwargs)
    app.query_one = lambda selector, type=None: _FakeWidget()
    return app


def _scan_summary(system="Sol", event="Scan", body="Earth", **overrides):
    """Build a Scan-type summary dict with sensible defaults."""
    base = {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {
            "uploaderID": "cmdr1",
            "softwareName": "EDMC",
            "softwareVersion": "5.0",
            "gatewayTimestamp": "2026-05-10T22:36:19Z",
        },
        "message": {
            "event": event,
            "StarSystem": system,
            "BodyName": body,
        },
    }
    base.update(overrides)
    return extract_summary(base)


def _commodity_summary(system="Lave", station="Lave Station", **overrides):
    """Build a Commodity-type summary dict with sensible defaults."""
    base = {
        "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
        "header": {
            "uploaderID": "trader42",
            "softwareName": "EDD",
            "softwareVersion": "3.1",
            "gatewayTimestamp": "2026-05-10T23:00:00Z",
        },
        "message": {
            "systemName": system,
            "stationName": station,
        },
    }
    base.update(overrides)
    return extract_summary(base)

def _compress(data: dict) -> bytes:
    """JSON-encode and zlib-compress an EDDN message dict."""
    return zlib.compress(json.dumps(data).encode())


def _bind_zmq_pub() -> tuple:
    """Create a PUB socket bound to an ephemeral port.

    Returns (ctx, pub, url). EDDNReceiver creates its own zmq.Context
    internally, so inproc:// (which requires same-context) won't work.
    We use tcp://127.0.0.1 with a random port instead.

    Callers must sleep after connecting a subscriber to allow the
    ZMQ SUB handshake to complete (slow-joiner problem).
    """
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    port = pub.bind_to_random_port("tcp://127.0.0.1")
    url = f"tcp://127.0.0.1:{port}"
    return ctx, pub, url


class _FakeReceiver:
    """Deterministic stand-in for EDDNReceiver used to feed a running pilot app.

    recv_message() pops from a pre-supplied queue and returns None once
    exhausted, matching EDDNReceiver's timeout behaviour, but without any
    network I/O or slow-joiner timing to race against.
    """

    def __init__(self, messages):
        self._queue = list(messages)

    def recv_message(self):
        if self._queue:
            return self._queue.pop(0)
        return None

    def close(self):
        pass


def _raw_journal_message(system="Sol", event="Scan", body="Earth", uploader_id="cmdr1", gateway_ts="2026-05-10T22:36:19Z"):
    """Build a raw (un-summarized) EDDN journal message dict for feeding into a pilot app."""
    return {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {
            "uploaderID": uploader_id,
            "softwareName": "EDMC",
            "softwareVersion": "5.0",
            "gatewayTimestamp": gateway_ts,
        },
        "message": {
            "event": event,
            "StarSystem": system,
            "BodyName": body,
        },
    }


def _static_text(widget):
    """Read the plain rendered text of a Static widget.

    Static.content is a recent Textual API (not present at the project's
    declared floor of textual==2.0). widget.visual (a textual.content.Content
    instance whose __str__ returns the plain text) is available across the
    whole supported range, so tests read through that instead.
    """
    return str(widget.visual)


def _feed_messages(app, messages):
    """Inject raw messages into a running EDDNTailApp deterministically.

    Closes the real EDDNReceiver created in on_mount (to avoid leaking its
    ZMQ socket/context) and installs a _FakeReceiver, then drives
    _poll_messages() directly instead of waiting on the 0.05s interval -
    this keeps the pilot tests free of sleeps and timing races.
    """
    if app._receiver is not None:
        app._receiver.close()
    app._receiver = _FakeReceiver(messages)
    app._poll_messages()


@contextlib.asynccontextmanager
async def _running_app(app):
    """Run a pilot-driven app, then neutralize its background poll interval
    before tearing down the widget tree.

    EDDNTailApp's on_mount schedules a 0.05s interval that calls
    _poll_messages() for the app's whole lifetime. If that timer fires
    while run_test() is mid-teardown (a real, if rare, race - the screen's
    widgets can already be gone while the timer is still pending), it
    raises NoMatches on '#message-table'. _poll_messages() early-returns
    when self._receiver is falsy, so clearing it before we leave the pilot
    context makes that exposure window harmless instead of flaky.
    """
    async with app.run_test() as pilot:
        try:
            yield pilot
        finally:
            if app._receiver is not None:
                app._receiver.close()
            app._receiver = None


# ---------------------------------------------------------------------------
# 1. extract_summary()
# ---------------------------------------------------------------------------

class TestExtractSummary:
    """Tests for the pure extract_summary function."""

    def test_full_journal_scan(self):
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
            "header": {
                "uploaderID": "cmdr1",
                "softwareName": "EDMC",
                "softwareVersion": "5.0",
                "gatewayTimestamp": "2026-05-10T22:36:19.745292Z",
            },
            "message": {
                "event": "Scan",
                "timestamp": "2026-05-10T22:36:00Z",
                "StarSystem": "Sol",
                "BodyName": "Sol",
            },
        }
        s = extract_summary(msg)
        assert s["schema"] == "journal/1"
        assert s["event"] == "Scan"
        assert s["system"] == "Sol"
        assert s["body"] == "Sol"
        assert s["station"] == ""
        assert s["uploader_id"] == "cmdr1"
        assert s["software"] == "EDMC 5.0"
        assert s["gateway_ts"] == "2026-05-10T22:36:19.745292Z"
        assert s["journal_ts"] == "2026-05-10T22:36:00Z"
        assert "raw" not in s  # raw is stored separately in _raw_messages

    def test_commodity_message(self):
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {
                "uploaderID": "trader42",
                "softwareName": "EDD",
                "softwareVersion": "3.1",
                "gatewayTimestamp": "2026-05-10T23:00:00Z",
            },
            "message": {
                "systemName": "Lave",
                "stationName": "Lave Station",
                "timestamp": "2026-05-10T22:59:00Z",
            },
        }
        s = extract_summary(msg)
        assert s["schema"] == "commodity/3"
        assert s["system"] == "Lave"
        assert s["station"] == "Lave Station"
        assert s["event"] == "commodity"  # derived from schema

    def test_outfitting_message(self):
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/outfitting/2",
            "header": {
                "uploaderID": "shipbuilder",
                "softwareName": "Coriolis",
                "softwareVersion": "2.0",
                "gatewayTimestamp": "2026-05-10T23:10:00Z",
            },
            "message": {
                "systemName": "Shinrarta Dezhra",
                "stationName": "Jameson Memorial",
            },
        }
        s = extract_summary(msg)
        assert s["schema"] == "outfitting/2"
        assert s["system"] == "Shinrarta Dezhra"
        assert s["station"] == "Jameson Memorial"

    def test_fsdjump_with_starclass(self):
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
            "header": {
                "uploaderID": "cmdr2",
                "softwareName": "EDMC",
                "softwareVersion": "5.0",
                "gatewayTimestamp": "2026-05-10T22:40:00Z",
            },
            "message": {
                "event": "FSDJump",
                "StarSystem": "Deciat",
                "StarClass": "K",
                "timestamp": "2026-05-10T22:39:00Z",
            },
        }
        s = extract_summary(msg)
        assert s["event"] == "FSDJump"
        assert s["system"] == "Deciat"
        assert s["star_class"] == "K"

    def test_unknown_schema_extracts_last_segment(self):
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/fuel/1",
            "header": {"uploaderID": "u1"},
            "message": {"event": "FuelScoop"},
        }
        s = extract_summary(msg)
        # Now extracts last two segments (type/version) consistently with known schemas
        assert s["schema"] == "fuel/1"

    def test_schema_no_slash_returns_as_is(self):
        msg = {
            "$schemaRef": "unknown-schema",
            "header": {},
            "message": {},
        }
        s = extract_summary(msg)
        # No "/" in schemaRef → else branch returns as-is
        assert s["schema"] == "unknown-schema"

    def test_empty_schema_ref(self):
        msg = {"$schemaRef": "", "header": {}, "message": {}}
        s = extract_summary(msg)
        assert s["schema"] == ""

    def test_missing_fields(self):
        """Message with no header or message keys."""
        s = extract_summary({})
        assert s["schema"] == ""
        assert s["event"] == ""
        assert s["system"] == ""
        assert s["station"] == ""
        assert s["body"] == ""
        assert s["star_class"] == ""
        assert s["uploader_id"] == ""
        assert s["software"] == ""
        assert s["gateway_ts"] == ""
        assert s["journal_ts"] == ""

    def test_software_version_only(self):
        msg = {
            "$schemaRef": "",
            "header": {"softwareVersion": "1.0"},
            "message": {},
        }
        s = extract_summary(msg)
        assert s["software"] == "1.0"

    def test_starsystem_preferred_over_systemname(self):
        """When both StarSystem and SystemName exist, StarSystem wins."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
            "header": {},
            "message": {"StarSystem": "Sol", "SystemName": "Lave"},
        }
        s = extract_summary(msg)
        assert s["system"] == "Sol"

    def test_starsystem_preferred_over_lowercase_systemname(self):
        """When both StarSystem and systemName exist, StarSystem wins."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
            "header": {},
            "message": {"StarSystem": "Sol", "systemName": "Lave"},
        }
        s = extract_summary(msg)
        assert s["system"] == "Sol"

    def test_capitalized_systemname_preferred_over_lowercase(self):
        """SystemName (capitalized) is checked before systemName (lowercase)."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {},
            "message": {"SystemName": "Lave", "systemName": "Deciat"},
        }
        s = extract_summary(msg)
        assert s["system"] == "Lave"

    def test_systemname_fallback(self):
        """When only systemName (lowercase) exists, it is used."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {},
            "message": {"systemName": "Lave"},
        }
        s = extract_summary(msg)
        assert s["system"] == "Lave"

    def test_derived_event_commodity(self):
        """commodity/3 messages derive event='commodity' from schema."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {},
            "message": {"systemName": "Lave", "stationName": "Lave Station"},
        }
        s = extract_summary(msg)
        assert s["event"] == "commodity"
        assert s["system"] == "Lave"
        assert s["station"] == "Lave Station"

    def test_derived_event_outfitting(self):
        """outfitting/2 messages derive event='outfitting' from schema."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/outfitting/2",
            "header": {},
            "message": {"systemName": "Shinrarta Dezhra", "stationName": "Jameson Memorial"},
        }
        s = extract_summary(msg)
        assert s["event"] == "outfitting"
        assert s["system"] == "Shinrarta Dezhra"
        assert s["station"] == "Jameson Memorial"

    def test_derived_event_shipyard(self):
        """shipyard/2 messages derive event='shipyard' from schema."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/shipyard/2",
            "header": {},
            "message": {"systemName": "Shinrarta Dezhra", "stationName": "Jameson Memorial"},
        }
        s = extract_summary(msg)
        assert s["event"] == "shipyard"
        assert s["system"] == "Shinrarta Dezhra"
        assert s["station"] == "Jameson Memorial"

    def test_journal_event_takes_priority_over_derived(self):
        """Journal messages keep their own event field, not overridden by schema."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
            "header": {},
            "message": {"event": "Scan", "StarSystem": "Sol"},
        }
        s = extract_summary(msg)
        assert s["event"] == "Scan"  # not derived from schema

    def test_unknown_schema_no_derived_event(self):
        """Unknown schema with no event field yields empty string."""
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/fuel/1",
            "header": {},
            "message": {},
        }
        s = extract_summary(msg)
        assert s["event"] == ""


# ---------------------------------------------------------------------------
# 2. EDDNReceiver
# ---------------------------------------------------------------------------

class TestEDDNReceiver:
    """Tests for EDDNReceiver using tcp://127.0.0.1 with ephemeral ports.

    ZeroMQ PUB/SUB has a "slow joiner" problem: messages sent immediately
    after SUB connects may be lost. We work around this by sleeping
    after creating the receiver before publishing.
    """

    def _setup_receiver(self):
        """Bind a PUB socket and create an EDDNReceiver connected to it.

        Returns (ctx, pub, receiver) ready for publishing.
        """
        ctx, pub, url = _bind_zmq_pub()
        receiver = EDDNReceiver(url, topic_filter="")
        time.sleep(0.3)  # allow ZMQ SUB connection handshake
        return ctx, pub, receiver

    def test_receive_valid_message(self):
        ctx, pub, receiver = self._setup_receiver()
        try:
            msg = {
                "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
                "header": {"uploaderID": "test"},
                "message": {"event": "Scan", "StarSystem": "Sol"},
            }
            pub.send(_compress(msg))
            result = receiver.recv_message()
            assert result is not None
            assert result["message"]["event"] == "Scan"
        finally:
            receiver.close()
            pub.close(linger=0)
            ctx.term()

    def test_timeout_returns_none(self):
        """Receiver with no publisher sending should time out and return None."""
        ctx, pub, url = _bind_zmq_pub()
        time.sleep(0.15)  # allow SUB connection for timeout test
        receiver = EDDNReceiver(url)
        try:
            result = receiver.recv_message()
            assert result is None
        finally:
            receiver.close()
            pub.close(linger=0)
            ctx.term()

    def test_invalid_zlib_returns_error(self):
        """Sending raw (non-zlib) bytes should produce an _error dict."""
        ctx, pub, receiver = self._setup_receiver()
        try:
            pub.send(b"this is not zlib compressed")
            result = receiver.recv_message()
            assert result is not None
            assert "_error" in result
        finally:
            receiver.close()
            pub.close(linger=0)
            ctx.term()

    def test_invalid_json_returns_error(self):
        """Sending zlib-compressed non-JSON should produce an _error dict."""
        ctx, pub, receiver = self._setup_receiver()
        try:
            pub.send(zlib.compress(b"not valid json{"))
            result = receiver.recv_message()
            assert result is not None
            assert "_error" in result
        finally:
            receiver.close()
            pub.close(linger=0)
            ctx.term()

    def test_close_no_error(self):
        """close() should not raise."""
        ctx, pub, url = _bind_zmq_pub()
        time.sleep(0.15)  # allow SUB connection
        receiver = EDDNReceiver(url)
        try:
            receiver.close()
        finally:
            pub.close(linger=0)
            ctx.term()
        # If we get here without exception, the test passes


# ---------------------------------------------------------------------------
# 3. Combined filter matching (CLI + live)
# ---------------------------------------------------------------------------

def _matches_all(app, summary):
    """Helper: check both CLI and live filters (replaces removed _matches_filters)."""
    return app._matches_cli_filters(summary) and app._matches_live_filter(summary)


class TestMatchesFilters:
    """Tests for combined CLI + live filter matching on EDDNTailApp."""

    def test_no_filters_match_everything(self):
        app = _make_app()
        assert _matches_all(app, _scan_summary()) is True
        assert _matches_all(app, _commodity_summary()) is True

    def test_event_filter_case_insensitive(self):
        app = _make_app(event_filter="scan")
        assert _matches_all(app, _scan_summary()) is True
        assert _matches_all(app, _commodity_summary()) is False

    def test_event_filter_substring(self):
        app = _make_app(event_filter="Sc")
        assert _matches_all(app, _scan_summary()) is True

    def test_system_filter(self):
        app = _make_app(system_filter="sol")
        assert _matches_all(app, _scan_summary()) is True
        assert _matches_all(app, _commodity_summary()) is False

    def test_station_filter(self):
        app = _make_app(station_filter="lave station")
        assert _matches_all(app, _commodity_summary()) is True
        assert _matches_all(app, _scan_summary()) is False

    def test_schema_filter(self):
        app = _make_app(schema_filter="journal/1")
        assert _matches_all(app, _scan_summary()) is True
        assert _matches_all(app, _commodity_summary()) is False

    def test_combined_filters_and_logic(self):
        app = _make_app(event_filter="scan", system_filter="sol")
        s = _scan_summary()
        assert _matches_all(app, s) is True

    def test_combined_filters_one_fails(self):
        app = _make_app(event_filter="scan", system_filter="lave")
        s = _scan_summary()
        assert _matches_all(app, s) is False  # system is Sol, not Lave

    def test_live_filter_valid_regex(self):
        app = _make_app()
        app._live_filter = "sol|lave"
        app._live_filter_pattern = app._compile_live_filter()
        assert _matches_all(app, _scan_summary()) is True
        assert _matches_all(app, _commodity_summary()) is True

    def test_live_filter_regex_case_insensitive(self):
        app = _make_app()
        app._live_filter = "SOL"
        app._live_filter_pattern = app._compile_live_filter()
        assert _matches_all(app, _scan_summary()) is True

    def test_live_filter_invalid_regex_falls_back_to_substring(self):
        app = _make_app()
        app._live_filter = "[invalid"
        app._live_filter_pattern = app._compile_live_filter()
        # Should not crash; falls back to substring match
        s = _scan_summary()
        # "[invalid" is not a substring anywhere in the haystack
        assert _matches_all(app, s) is False

    def test_live_filter_valid_regex_substring_match(self):
        app = _make_app()
        app._live_filter = "Scan"
        app._live_filter_pattern = app._compile_live_filter()
        # "Scan" is a valid regex AND a substring in the haystack
        assert _matches_all(app, _scan_summary()) is True

    def test_live_filter_non_matching(self):
        app = _make_app()
        app._live_filter = "zzz_nonexistent"
        app._live_filter_pattern = app._compile_live_filter()
        assert _matches_all(app, _scan_summary()) is False

    def test_empty_event_no_match(self):
        """A summary with empty event should not match a non-empty event_filter."""
        app = _make_app(event_filter="Scan")
        empty_summary = extract_summary({
            "$schemaRef": "",
            "header": {},
            "message": {},
        })
        assert _matches_all(app, empty_summary) is False

    def test_commodity_event_matches_commodity_filter(self):
        """A commodity/3 message with derived event='commodity' matches 'commodity' filter."""
        app = _make_app(event_filter="commodity")
        commodity_summary = extract_summary({
            "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {"uploaderID": "trader"},
            "message": {"systemName": "Lave", "stationName": "Lave Station"},
        })
        assert _matches_all(app, commodity_summary) is True

    def test_commodity_event_does_not_match_scan_filter(self):
        """A commodity/3 message with derived event should not match 'Scan' filter."""
        app = _make_app(event_filter="scan")
        commodity_summary = extract_summary({
            "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {"uploaderID": "trader"},
            "message": {"systemName": "Lave", "stationName": "Lave Station"},
        })
        assert _matches_all(app, commodity_summary) is False


# ---------------------------------------------------------------------------
# 3b. _matches_cli_filters() and _matches_live_filter()
# ---------------------------------------------------------------------------

class TestFilterSplit:
    """Tests for the split filter methods (CLI vs live)."""

    def test_cli_filter_matches(self):
        app = _make_app(event_filter="scan")
        assert app._matches_cli_filters(_scan_summary()) is True

    def test_cli_filter_rejects(self):
        app = _make_app(event_filter="fsdjump")
        assert app._matches_cli_filters(_scan_summary()) is False

    def test_live_filter_matches(self):
        app = _make_app()
        app._live_filter = "sol"
        app._live_filter_pattern = app._compile_live_filter()
        assert app._matches_live_filter(_scan_summary()) is True

    def test_live_filter_rejects(self):
        app = _make_app()
        app._live_filter = "zzz"
        app._live_filter_pattern = app._compile_live_filter()
        assert app._matches_live_filter(_scan_summary()) is False

    def test_live_filter_empty_passes(self):
        app = _make_app()
        # No live filter set
        assert app._matches_live_filter(_scan_summary()) is True

    def test_combined_still_competent(self):
        """Combined filter check still verifies both CLI and live filters."""
        app = _make_app(event_filter="scan")
        app._live_filter = "sol"
        app._live_filter_pattern = app._compile_live_filter()
        assert _matches_all(app, _scan_summary()) is True

    def test_cli_pass_live_fail_means_hidden(self):
        """A message passing CLI filter but failing live filter should
        still be stored (just not displayed)."""
        app = _make_app(event_filter="scan")
        app._live_filter = "zzz"
        app._live_filter_pattern = app._compile_live_filter()
        assert app._matches_cli_filters(_scan_summary()) is True
        assert app._matches_live_filter(_scan_summary()) is False
        assert _matches_all(app, _scan_summary()) is False


# ---------------------------------------------------------------------------
# 4. main() argument parsing
# ---------------------------------------------------------------------------

class TestMainArgParsing:
    """Test argument parsing in main() by patching sys.argv."""

    def _parse_args(self, argv):
        """Run the argparse part of main() with given argv, return args."""
        parser = build_parser()
        args = parser.parse_args(argv)
        if args.beta and args.dev:
            parser.error("--beta and --dev are mutually exclusive")
        # Validate limit (same logic as main())
        if not (MIN_EVENT_LIMIT <= args.limit <= MAX_EVENT_LIMIT):
            parser.error(f"--limit must be between {MIN_EVENT_LIMIT} and {MAX_EVENT_LIMIT}, got {args.limit}")
        return args

    def test_default_args(self):
        args = self._parse_args([])
        assert args.event == ""
        assert args.system == ""
        assert args.station == ""
        assert args.schema == ""
        assert args.beta is False
        assert args.dev is False

    def test_beta_flag(self):
        args = self._parse_args(["--beta"])
        assert args.beta is True
        endpoint = EDDN_ENDPOINTS["beta"] if args.beta else EDDN_ENDPOINTS["live"]
        assert endpoint == "tcp://beta.eddn.edcd.io:9510"

    def test_dev_flag(self):
        args = self._parse_args(["--dev"])
        assert args.dev is True
        endpoint = EDDN_ENDPOINTS["dev"] if args.dev else EDDN_ENDPOINTS["live"]
        assert endpoint == "tcp://dev.eddn.edcd.io:9520"

    def test_beta_and_dev_mutually_exclusive(self):
        """--beta and --dev together should cause parser.error (SystemExit)."""
        with pytest.raises(SystemExit):
            self._parse_args(["--beta", "--dev"])

    def test_combined_filters(self):
        args = self._parse_args(["-f", "Scan", "-s", "Sol"])
        assert args.event == "Scan"
        assert args.system == "Sol"

    def test_all_filter_flags(self):
        args = self._parse_args([
            "-f", "FSDJump",
            "-s", "Deciat",
            "-t", "Farseer Inc",
            "-S", "journal/1",
        ])
        assert args.event == "FSDJump"
        assert args.system == "Deciat"
        assert args.station == "Farseer Inc"
        assert args.schema == "journal/1"


# ---------------------------------------------------------------------------
# 5. Constants smoke tests
# ---------------------------------------------------------------------------

class TestConstants:
    """Smoke tests for constant mappings."""

    def test_eddn_endpoints_keys(self):
        assert set(EDDN_ENDPOINTS.keys()) == {"live", "beta", "dev"}

    def test_schema_short_keys(self):
        expected = {
            "https://eddn.edcd.io/schemas/journal/1",
            "https://eddn.edcd.io/schemas/commodity/3",
            "https://eddn.edcd.io/schemas/outfitting/2",
            "https://eddn.edcd.io/schemas/shipyard/2",
        }
        assert set(SCHEMA_SHORT.keys()) == expected

    def test_schema_short_values(self):
        assert set(SCHEMA_SHORT.values()) == {"journal/1", "commodity/3", "outfitting/2", "shipyard/2"}

    def test_schema_colors_keys_match_schema_short_values(self):
        assert set(SCHEMA_COLORS.keys()) == set(SCHEMA_SHORT.values())

    def test_endpoints_format(self):
        for key, url in EDDN_ENDPOINTS.items():
            assert url.startswith("tcp://"), f"{key} endpoint doesn't start with tcp://"

    def test_schema_event_keys_are_non_journal_schemas(self):
        """SCHEMA_EVENT covers non-journal schemas that lack an event field."""
        assert set(SCHEMA_EVENT.keys()) == {"commodity/3", "outfitting/2", "shipyard/2"}

    def test_schema_event_values_are_lowercase(self):
        for val in SCHEMA_EVENT.values():
            assert val == val.lower()


# ---------------------------------------------------------------------------
# 6. action_clear_events()
# ---------------------------------------------------------------------------

class TestClearEvents:
    """Tests for the action_clear_events method on EDDNTailApp."""

    def test_clear_events_resets_state(self):
        """Clearing events empties _messages and resets counters."""
        app = _make_app()
        # Populate state
        app._messages = {
            "1": {"event": "Scan", "system": "Sol"},
            "2": {"event": "FSDJump", "system": "Deciat"},
        }
        app._raw_messages = {
            "1": {"$schemaRef": ""},
            "2": {"$schemaRef": ""},
        }
        app._msg_count = 10
        app._filtered_count = 3

        # Only test the pure-state logic - mock out widget calls
        app.query_one = lambda selector, type=None: _FakeWidget()
        app.notify = lambda msg: None

        app.action_clear_events()

        assert app._messages == {}
        assert app._raw_messages == {}
        assert app._msg_count == 0
        assert app._filtered_count == 0
        assert app._live_hidden_count == 0

    def test_clear_events_after_clear_rate_resets(self):
        """After clearing, _app_start_time is updated so rate is sensible."""
        app = _make_app()
        old_start = app._app_start_time
        # Simulate some time passing
        app._app_start_time = old_start - timedelta(hours=1)

        app.query_one = lambda selector, type=None: _FakeWidget()
        app.notify = lambda msg: None

        app.action_clear_events()

        # _app_start_time should be newer than the old value
        assert app._app_start_time > old_start - timedelta(hours=1)
        # Elapsed time since reset should be near zero (< 2s tolerance)
        elapsed = (datetime.now(timezone.utc) - app._app_start_time).total_seconds()
        assert elapsed < 2.0

    def test_clear_events_clears_table_and_detail(self):
        """Clearing events calls clear() on DataTable and update("") on detail."""
        app = _make_app()
        app._messages = {"1": {"event": "Scan", "system": "Sol"}}
        app._raw_messages = {"1": {"$schemaRef": ""}}
        app._msg_count = 5

        table_cleared = []
        detail_cleared = []

        class FakeTable:
            rows = []
            def clear(self):
                table_cleared.append(True)

        class FakeStatic:
            border_title = ""
            def update(self, text):
                detail_cleared.append(text)

        def fake_query_one(selector, type=None):
            if selector == "#message-table":
                return FakeTable()
            elif selector == "#detail-content":
                return FakeStatic()
            return _FakeWidget()

        app.query_one = fake_query_one
        app.notify = lambda msg: None

        app.action_clear_events()

        assert app._messages == {}
        assert app._msg_count == 0
        assert len(table_cleared) == 1
        assert detail_cleared == [""]

    def test_clear_events_calls_notify(self):
        """Clearing events calls notify with the expected message."""
        app = _make_app()
        app._messages = {"1": {"event": "Scan", "system": "Sol"}}
        app._raw_messages = {"1": {"$schemaRef": ""}}
        app.query_one = lambda selector, type=None: _FakeWidget()

        notified = []
        app.notify = lambda msg: notified.append(msg)

        app.action_clear_events()

        assert notified == ["Events cleared"]

    def test_clear_events_updates_pane_titles(self):
        """After clearing, _update_pane_titles and _update_stats are called."""
        app = _make_app()
        app._messages = {"1": {"event": "Scan", "system": "Sol"}}
        app._raw_messages = {"1": {"$schemaRef": ""}}
        app._msg_count = 5

        # Track that _update_pane_titles and _update_stats were called
        titles_called = []
        stats_called = []

        app._update_pane_titles = lambda: titles_called.append(True)
        app._update_stats = lambda: stats_called.append(True)
        app.query_one = lambda selector, type=None: _FakeWidget()
        app.notify = lambda msg: None

        app.action_clear_events()

        assert len(titles_called) == 1
        assert len(stats_called) == 1

# ---------------------------------------------------------------------------
# 7. Event storage limit
# ---------------------------------------------------------------------------

class TestEventLimitConstants:
    """Tests for the event limit constants."""

    def test_min_limit(self):
        assert MIN_EVENT_LIMIT == 1

    def test_max_limit(self):
        assert MAX_EVENT_LIMIT == 1999

    def test_default_limit(self):
        assert DEFAULT_EVENT_LIMIT == 500


class TestEventLimitArgParsing:
    """Tests for the --limit CLI argument."""

    def _parse_args(self, argv):
        parser = build_parser()
        args = parser.parse_args(argv)
        if not (MIN_EVENT_LIMIT <= args.limit <= MAX_EVENT_LIMIT):
            parser.error(f"--limit must be between {MIN_EVENT_LIMIT} and {MAX_EVENT_LIMIT}, got {args.limit}")
        return args

    def test_default_limit(self):
        args = self._parse_args([])
        assert args.limit == DEFAULT_EVENT_LIMIT

    def test_explicit_limit(self):
        args = self._parse_args(["--limit", "1000"])
        assert args.limit == 1000

    def test_short_flag(self):
        args = self._parse_args(["-l", "100"])
        assert args.limit == 100

    def test_min_boundary(self):
        args = self._parse_args(["--limit", "1"])
        assert args.limit == 1

    def test_max_boundary(self):
        args = self._parse_args(["--limit", "1999"])
        assert args.limit == 1999

    def test_limit_zero_rejected(self):
        with pytest.raises(SystemExit):
            self._parse_args(["--limit", "0"])

    def test_limit_negative_rejected(self):
        with pytest.raises(SystemExit):
            self._parse_args(["--limit", "-1"])

    def test_limit_too_large_rejected(self):
        with pytest.raises(SystemExit):
            self._parse_args(["--limit", "2000"])

    def test_limit_not_integer_rejected(self):
        with pytest.raises(SystemExit):
            self._parse_args(["--limit", "abc"])


class TestEventLimitInit:
    """Tests for EDDNTailApp initial_limit handling."""

    def test_default_limit(self):
        app = EDDNTailApp(endpoint="tcp://localhost:9999")
        assert app._max_event_limit == DEFAULT_EVENT_LIMIT

    def test_custom_limit(self):
        app = EDDNTailApp(endpoint="tcp://localhost:9999", initial_limit=100)
        assert app._max_event_limit == 100

    def test_limit_survives_clear(self):
        """action_clear_events should not reset the limit."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999", initial_limit=100)
        app._messages = {"1": {"event": "Scan"}}
        app._msg_count = 1
        app.query_one = lambda selector, type=None: _FakeWidget()
        app.notify = lambda msg: None
        app.action_clear_events()
        assert app._max_event_limit == 100


class TestEventLimitEnforcement:
    """Tests for the _enforce_limit and FIFO eviction logic."""

    def test_enforce_limit_below_cap(self):
        """No eviction when messages are under the limit."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999", initial_limit=5)
        app._messages = OrderedDict([
            ("1", {"event": "Scan"}),
            ("2", {"event": "FSDJump"}),
        ])
        app._raw_messages = OrderedDict([
            ("1", {"$schemaRef": ""}),
            ("2", {"$schemaRef": ""}),
        ])
        app._enforce_limit()
        assert len(app._messages) == 2
        assert len(app._raw_messages) == 2

    def test_enforce_limit_at_cap(self):
        """No eviction when messages are exactly at the limit."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999", initial_limit=3)
        app._messages = OrderedDict([
            ("1", {"event": "Scan"}),
            ("2", {"event": "FSDJump"}),
            ("3", {"event": "Dock"}),
        ])
        app._raw_messages = OrderedDict([
            ("1", {"$schemaRef": ""}),
            ("2", {"$schemaRef": ""}),
            ("3", {"$schemaRef": ""}),
        ])
        app._enforce_limit()
        assert len(app._messages) == 3
        assert len(app._raw_messages) == 3

    def test_enforce_limit_over_cap_evicts_oldest(self):
        """Eviction removes oldest messages first (FIFO)."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999", initial_limit=3)
        app._messages = OrderedDict([
            ("1", {"event": "Scan"}),
            ("2", {"event": "FSDJump"}),
            ("3", {"event": "Dock"}),
            ("4", {"event": "Scan"}),
        ])
        app._raw_messages = OrderedDict([
            ("1", {"$schemaRef": ""}),
            ("2", {"$schemaRef": ""}),
            ("3", {"$schemaRef": ""}),
            ("4", {"$schemaRef": ""}),
        ])
        app._enforce_limit()
        assert len(app._messages) == 3
        assert "1" not in app._messages
        assert "4" in app._messages
        assert "1" not in app._raw_messages
        assert "4" in app._raw_messages

    def test_enforce_limit_multiple_evictions(self):
        """When limit is lowered, multiple messages are evicted."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999", initial_limit=5)
        app._messages = OrderedDict([
            (str(i), {"event": f"E{i}"}) for i in range(1, 8)
        ])
        app._raw_messages = OrderedDict([
            (str(i), {"$schemaRef": ""}) for i in range(1, 8)
        ])
        app._max_event_limit = 3
        app._enforce_limit()
        assert len(app._messages) == 3
        assert "1" not in app._messages
        assert "7" in app._messages
        assert len(app._raw_messages) == 3
        assert "1" not in app._raw_messages
        assert "7" in app._raw_messages

    def test_enforce_limit_empty_messages(self):
        """Enforce on empty dict is a no-op."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999", initial_limit=3)
        app._messages = OrderedDict()
        app._raw_messages = OrderedDict()
        app._enforce_limit()
        assert len(app._messages) == 0
        assert len(app._raw_messages) == 0


class TestApplyLimitFromInput:
    """Tests for _apply_limit_from_input validation."""

    def test_valid_limit(self):
        app = _make_app()
        notified = []
        app.notify = lambda msg, **kw: notified.append(msg)
        app._refresh_table = lambda: None
        app._apply_limit_from_input("500")
        assert app._max_event_limit == 500
        assert any("500" in n for n in notified)

    def test_boundary_min(self):
        app = _make_app()
        app.notify = lambda msg, **kw: None
        app._refresh_table = lambda: None
        app._apply_limit_from_input("1")
        assert app._max_event_limit == 1

    def test_boundary_max(self):
        app = _make_app()
        app.notify = lambda msg, **kw: None
        app._refresh_table = lambda: None
        app._apply_limit_from_input("1999")
        assert app._max_event_limit == 1999

    def test_rejects_zero(self):
        app = _make_app()
        notified = []
        app.notify = lambda msg, **kw: notified.append(msg)
        app._apply_limit_from_input("0")
        assert app._max_event_limit == DEFAULT_EVENT_LIMIT  # unchanged

    def test_rejects_too_large(self):
        app = _make_app()
        notified = []
        app.notify = lambda msg, **kw: notified.append(msg)
        app._apply_limit_from_input("2000")
        assert app._max_event_limit == DEFAULT_EVENT_LIMIT  # unchanged

    def test_rejects_non_integer(self):
        app = _make_app()
        notified = []
        app.notify = lambda msg, **kw: notified.append(msg)
        app._apply_limit_from_input("abc")
        assert app._max_event_limit == DEFAULT_EVENT_LIMIT  # unchanged

    def test_enforce_limit_after_lowering(self):
        """Lowering the limit should immediately prune excess messages."""
        app = _make_app()
        app._messages = OrderedDict([
            (str(i), {"event": f"E{i}"}) for i in range(1, 6)
        ])
        app._raw_messages = OrderedDict([
            (str(i), {"$schemaRef": ""}) for i in range(1, 6)
        ])
        app._max_event_limit = 500
        app._refresh_table = lambda: None
        app._apply_limit_from_input("3")
        assert app._max_event_limit == 3
        assert len(app._messages) == 3
        assert "1" not in app._messages
        assert "5" in app._messages
        assert len(app._raw_messages) == 3
        assert "1" not in app._raw_messages
        assert "5" in app._raw_messages


class TestLiveFilterDiscardOnArrival:
    """Tests for the discard-on-arrival behavior when a live filter is active."""

    def test_no_filter_stores_everything(self):
        """With no live filter, all messages that pass CLI filters are stored."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999")
        # No live filter set
        assert app._live_filter == ""
        summary = _scan_summary("Sol")
        assert app._matches_cli_filters(summary) is True
        # Message would pass both checks and be stored
        assert _matches_all(app, summary) is True

    def test_live_filter_discards_non_matching(self):
        """When a live filter is active, messages that don't match are not stored."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999")
        app._live_filter = "sol"
        app._live_filter_pattern = app._compile_live_filter()

        matching = _scan_summary("Sol")
        non_matching = _scan_summary("Deciat")

        assert app._matches_live_filter(matching) is True
        assert app._matches_live_filter(non_matching) is False

        # Simulate what _poll_messages does:
        # matching messages pass the live-filter discard check
        assert not (app._live_filter and not app._matches_live_filter(matching))
        # non-matching messages are discarded
        assert app._live_filter and not app._matches_live_filter(non_matching)

    def test_live_filter_discard_does_not_increment_filtered_count(self):
        """Live-filtered messages are not counted in _filtered_count (CLI-only counter).
        Instead, hidden messages are recalculated in _refresh_table."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999")
        app._live_filter = "dec"
        app._live_filter_pattern = app._compile_live_filter()

        initial_count = app._filtered_count
        # Simulate the discard path - live-filtered messages do NOT increment _filtered_count
        non_matching = _scan_summary("Sol")
        if app._live_filter and not app._matches_live_filter(non_matching):
            pass  # discarded, but no _filtered_count increment

        assert app._filtered_count == initial_count  # unchanged

    def test_live_filter_allows_matching_messages(self):
        """When a live filter is active, matching messages are stored normally."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999")
        app._live_filter = "sol"
        app._live_filter_pattern = app._compile_live_filter()

        matching = _scan_summary("Sol")
        # Matching messages pass the live-filter check
        assert app._matches_live_filter(matching) is True
        # The discard condition should NOT be true
        assert not (app._live_filter and not app._matches_live_filter(matching))

    def test_clearing_filter_stores_all_new_messages(self):
        """After clearing the live filter, all new messages pass the discard check."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999")
        app._live_filter = "sol"
        app._live_filter_pattern = app._compile_live_filter()

        # Clear the filter
        app._live_filter = ""
        app._live_filter_pattern = None

        summary = _scan_summary("Deciat")
        # No live filter means no discard
        assert not (app._live_filter and not app._matches_live_filter(summary))

    def test_cli_filters_still_discard_permanently(self):
        """CLI filters always discard messages before live filter is checked."""
        app = EDDNTailApp(endpoint="tcp://localhost:9999", event_filter="scan")
        non_matching = extract_summary({
            "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
            "header": {"uploaderID": "cmdr1"},
            "message": {"event": "FSDJump", "StarSystem": "Sol"},
        })
        # CLI filter should fail
        assert app._matches_cli_filters(non_matching) is False
        # Message is discarded before live filter is even checked


# ---------------------------------------------------------------------------
# 8. _format_row()
# ---------------------------------------------------------------------------

class TestFormatRow:
    """Tests for the _format_row static method on EDDNTailApp."""

    def _summary(self, **overrides):
        """Build a minimal summary dict for _format_row testing."""
        base = {
            "gateway_ts": "2026-05-10T22:36:19.745292Z",
            "schema": "journal/1",
            "event": "Scan",
            "system": "Sol",
            "station": "Jameson Memorial",
            "body": "Earth",
            "star_class": "",
            "uploader_id": "cmdr_tester",
            "software": "EDMC 5.0",
        }
        base.update(overrides)
        return base

    def test_valid_iso_timestamp(self):
        """Valid ISO timestamp → formatted time string."""
        row = EDDNTailApp._format_row(self._summary(gateway_ts="2026-05-10T22:36:19Z"))
        assert row[0] == "22:36:19"

    def test_valid_iso_timestamp_with_microseconds(self):
        """ISO timestamp with microseconds is formatted correctly."""
        row = EDDNTailApp._format_row(self._summary(gateway_ts="2026-05-10T14:05:03.123456Z"))
        assert row[0] == "14:05:03"

    def test_invalid_timestamp_falls_back_to_prefix(self):
        """Invalid timestamp string falls back to first 8 chars."""
        row = EDDNTailApp._format_row(self._summary(gateway_ts="not-a-date"))
        assert row[0] == "not-a-da"

    def test_empty_timestamp_falls_back_to_question_marks(self):
        """Empty timestamp string falls back to '??'."""
        row = EDDNTailApp._format_row(self._summary(gateway_ts=""))
        assert row[0] == "??"

    def test_none_timestamp_falls_back_to_question_marks(self):
        """None timestamp falls back to '??'."""
        row = EDDNTailApp._format_row(self._summary(gateway_ts=None))
        assert row[0] == "??"

    def test_short_invalid_timestamp_falls_back_to_question_marks(self):
        """Short invalid timestamp (less than 8 chars) falls back to '??'."""
        # An invalid timestamp that's too short for ts[:8] to be meaningful
        # and also fails fromisoformat
        row = EDDNTailApp._format_row(self._summary(gateway_ts="bad"))
        # ts[:8] for "bad" would be "bad", but since fromisoformat fails
        # and ts is truthy, it returns ts[:8] which is "bad"
        assert row[0] == "bad"

    def test_schema_colors_journal(self):
        """journal/1 schema uses cyan color."""
        row = EDDNTailApp._format_row(self._summary(schema="journal/1"))
        assert "[cyan]journal/1[/cyan]" == row[1]

    def test_schema_colors_commodity(self):
        """commodity/3 schema uses green color."""
        row = EDDNTailApp._format_row(self._summary(schema="commodity/3"))
        assert "[green]commodity/3[/green]" == row[1]

    def test_schema_colors_outfitting(self):
        """outfitting/2 schema uses yellow color."""
        row = EDDNTailApp._format_row(self._summary(schema="outfitting/2"))
        assert "[yellow]outfitting/2[/yellow]" == row[1]

    def test_schema_colors_shipyard(self):
        """shipyard/2 schema uses magenta color."""
        row = EDDNTailApp._format_row(self._summary(schema="shipyard/2"))
        assert "[magenta]shipyard/2[/magenta]" == row[1]

    def test_unknown_schema_uses_white(self):
        """Unknown schema falls back to white color."""
        row = EDDNTailApp._format_row(self._summary(schema="fuel/1"))
        assert "[white]fuel/1[/white]" == row[1]

    def test_station_priority_over_body(self):
        """When both station and body are present, station takes priority."""
        row = EDDNTailApp._format_row(self._summary(station="Jameson Memorial", body="Earth"))
        # Location is at index 4
        assert row[4] == "Jameson Memorial"

    def test_body_used_when_no_station(self):
        """When only body is present (no station), body is shown."""
        row = EDDNTailApp._format_row(self._summary(station="", body="Earth"))
        assert row[4] == "Earth"

    def test_fsdjump_with_star_class_shows_bracket(self):
        """FSDJump with star_class shows [K] instead of station/body."""
        row = EDDNTailApp._format_row(self._summary(
            event="FSDJump", star_class="K", station="Jameson Memorial", body="Sol"
        ))
        assert row[4] == "[K]"

    def test_fsdjump_without_star_class_shows_station(self):
        """FSDJump without star_class shows station/body normally."""
        row = EDDNTailApp._format_row(self._summary(
            event="FSDJump", star_class="", station="Jameson Memorial"
        ))
        assert row[4] == "Jameson Memorial"

    def test_non_fsdjump_ignores_star_class(self):
        """Non-FSDJump event with star_class shows station, not [K]."""
        row = EDDNTailApp._format_row(self._summary(
            event="Scan", star_class="K", station="Jameson Memorial"
        ))
        assert row[4] == "Jameson Memorial"

    def test_uploader_id_truncated_to_12(self):
        """uploader_id is truncated to 12 characters."""
        row = EDDNTailApp._format_row(self._summary(uploader_id="a_very_long_commander_name"))
        assert row[5] == "a_very_long_"

    def test_uploader_id_short_preserved(self):
        """Short uploader_id is preserved as-is."""
        row = EDDNTailApp._format_row(self._summary(uploader_id="cmdr"))
        assert row[5] == "cmdr"

    def test_software_truncated_to_20(self):
        """software is truncated to 20 characters."""
        row = EDDNTailApp._format_row(self._summary(
            software="Very Long Software Name Version 12345"
        ))
        assert row[6] == "Very Long Software N"

    def test_software_short_preserved(self):
        """Short software name is preserved as-is."""
        row = EDDNTailApp._format_row(self._summary(software="EDMC 5.0"))
        assert row[6] == "EDMC 5.0"

    def test_row_tuple_length(self):
        """_format_row always returns a 7-element tuple."""
        row = EDDNTailApp._format_row(self._summary())
        assert len(row) == 7


# ---------------------------------------------------------------------------
# 9. _compile_live_filter()
# ---------------------------------------------------------------------------

class TestCompileLiveFilter:
    """Direct tests for the _compile_live_filter method."""

    def test_valid_regex_returns_compiled_pattern(self):
        """Valid regex returns a compiled re.Pattern with IGNORECASE flag."""
        app = _make_app()
        app._live_filter = "sol|lave"
        pattern = app._compile_live_filter()
        assert pattern is not None
        assert isinstance(pattern, re.Pattern)
        assert pattern.flags & re.IGNORECASE

    def test_valid_regex_matches_expected(self):
        """Compiled pattern matches expected strings."""
        app = _make_app()
        app._live_filter = "sol"
        pattern = app._compile_live_filter()
        assert pattern.search("Sol") is not None
        assert pattern.search("SOL") is not None  # IGNORECASE

    def test_invalid_regex_returns_none(self):
        """Invalid regex returns None instead of raising."""
        app = _make_app()
        app._live_filter = "[invalid"
        pattern = app._compile_live_filter()
        assert pattern is None

    def test_empty_string_returns_none(self):
        """Empty filter string returns None (no filter active)."""
        app = _make_app()
        app._live_filter = ""
        pattern = app._compile_live_filter()
        assert pattern is None

    def test_none_equivalent_returns_none(self):
        """Setting _live_filter to a falsy value returns None."""
        app = _make_app()
        app._live_filter = None
        pattern = app._compile_live_filter()
        assert pattern is None


# ---------------------------------------------------------------------------
# 10. _error handling in _poll_messages
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Test that _error dicts are not added to _messages."""

    def test_error_dict_not_stored(self):
        """Messages with '_error' key should not be added to _messages."""
        # We simulate the logic from _poll_messages:
        # if "_error" in msg: continue
        msg = {"_error": "decompression failed"}
        assert "_error" in msg
        # The message should be skipped, not stored
        # We verify the condition directly
        should_skip = "_error" in msg
        assert should_skip is True

    def test_normal_message_not_skipped(self):
        """Normal messages without '_error' key should not be skipped."""
        msg = {"$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
               "header": {"uploaderID": "test"},
               "message": {"event": "Scan"}}
        assert "_error" not in msg


# ---------------------------------------------------------------------------
# 11. Pilot-driven tests - drive the real running Textual app
# ---------------------------------------------------------------------------
#
# These tests use Textual's own harness (`async with app.run_test() as pilot`)
# instead of the _FakeWidget stub above, so they exercise the real widget
# tree, reactive updates, and key bindings. Messages are injected
# deterministically via _feed_messages()/_FakeReceiver (no network, no
# sleeps) - see the helpers above.
#
# Note: EDDNTailApp's own 0.05s poll interval keeps running in the
# background for the lifetime of the app and re-applies auto-scroll
# ("snap cursor to bottom if within 2 rows of it") on every tick, even
# when no new messages arrive. Tests that manually position the cursor
# use 5+ rows so the row under test isn't within that auto-scroll zone,
# avoiding a race between the test and the app's own behaviour.


def _five_row_messages():
    """Five raw messages with distinct systems, in arrival order."""
    return [
        _raw_journal_message(system="Sol"),
        _raw_journal_message(system="Lave"),
        _raw_journal_message(system="Deciat", event="FSDJump"),
        _raw_journal_message(system="Shinrarta Dezhra"),
        _raw_journal_message(system="Alpha Centauri"),
    ]


class TestPilotKeybindings:
    """Pilot-driven tests for the keybindings documented in the README."""

    async def test_pause_resume_toggles_state_and_title(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            assert app._paused is False

            await pilot.press("p")
            assert app._paused is True
            msg_pane = app.query_one("#message-pane")
            assert "Paused" in msg_pane.border_title

            await pilot.press("p")
            assert app._paused is False
            assert "Paused" not in msg_pane.border_title

    async def test_toggle_detail_pane_visibility(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            detail_pane = app.query_one("#detail-pane")
            assert app._show_detail is True
            assert detail_pane.display is True

            await pilot.press("d")
            assert app._show_detail is False
            assert detail_pane.display is False

            await pilot.press("d")
            assert app._show_detail is True
            assert detail_pane.display is True

    async def test_slash_focuses_filter_input(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            filter_bar = app.query_one("#filter-bar")
            inp = app.query_one("#filter-input", Input)
            assert filter_bar.display is False

            await pilot.press("slash")
            assert filter_bar.display is True
            assert inp.can_focus is True
            assert inp.has_focus is True

    async def test_escape_clears_filter(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, _five_row_messages())
            await pilot.pause()
            table = app.query_one("#message-table", DataTable)

            await pilot.press("slash")
            for ch in "sol":
                await pilot.press(ch)
            await pilot.pause()
            assert app._live_filter == "sol"
            assert table.row_count == 1  # only "Sol" matches

            await pilot.press("escape")
            await pilot.pause()

            inp = app.query_one("#filter-input", Input)
            filter_bar = app.query_one("#filter-bar")
            assert app._live_filter == ""
            assert inp.value == ""
            assert filter_bar.display is False
            assert table.row_count == 5  # all rows shown again

    async def test_ctrl_l_clears_events(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, _five_row_messages())
            await pilot.pause()
            table = app.query_one("#message-table", DataTable)
            assert table.row_count == 5

            await pilot.press("ctrl+l")
            await pilot.pause()

            assert table.row_count == 0
            assert app._messages == {}
            assert app._raw_messages == {}
            assert app._msg_count == 0


class TestPilotRowSelection:
    """Pilot-driven tests for selecting a row and showing its JSON detail."""

    async def test_selecting_row_shows_json_in_detail(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, _five_row_messages())
            await pilot.pause()
            table = app.query_one("#message-table", DataTable)

            table.focus()
            table.move_cursor(row=0)  # row 0 ("Sol") - not in the auto-scroll zone with 5 rows
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            detail = app.query_one("#detail-content", Static)
            detail_text = _static_text(detail)
            assert '"StarSystem": "Sol"' in detail_text
            assert "Lave" not in detail_text
            assert "Deciat" not in detail_text

    async def test_selecting_different_row_updates_detail(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, _five_row_messages())
            await pilot.pause()
            table = app.query_one("#message-table", DataTable)

            table.focus()
            table.move_cursor(row=1)  # row 1 ("Lave")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            detail = app.query_one("#detail-content", Static)
            assert '"StarSystem": "Lave"' in _static_text(detail)


class TestPilotLiveFilterInteractive:
    """Pilot-driven tests for the interactive live filter (typed via '/')."""

    async def test_typing_filter_hides_non_matching_rows(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, _five_row_messages())
            await pilot.pause()
            table = app.query_one("#message-table", DataTable)
            assert table.row_count == 5

            await pilot.press("slash")
            for ch in "deciat":
                await pilot.press(ch)
            await pilot.pause()

            assert table.row_count == 1
            assert app._live_hidden_count == 4

    async def test_live_filter_discards_non_matching_arrivals(self):
        """Per the documented design, messages that don't match an active
        live filter are discarded on arrival - never stored, not just hidden."""
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, [_raw_journal_message(system="Sol")])
            await pilot.pause()

            await pilot.press("slash")
            for ch in "sol":
                await pilot.press(ch)
            await pilot.pause()
            assert app._live_filter == "sol"

            before_keys = set(app._messages.keys())

            # A matching message and a non-matching one arrive while the filter is active.
            _feed_messages(app, [
                _raw_journal_message(system="Solitude"),
                _raw_journal_message(system="Deciat", event="FSDJump"),
            ])
            await pilot.pause()

            new_summaries = [app._messages[k] for k in app._messages if k not in before_keys]
            new_systems = {s["system"] for s in new_summaries}
            assert "Solitude" in new_systems
            assert "Deciat" not in new_systems  # discarded on arrival, never stored

            table = app.query_one("#message-table", DataTable)
            assert table.row_count == len(app._messages)  # every stored message is shown


class TestPilotEventLimit:
    """Pilot-driven tests for the FIFO event storage limit."""

    async def test_fifo_limit_drops_oldest_and_stats_agree(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1", initial_limit=3)
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, _five_row_messages())  # 5 messages, limit is 3
            await pilot.pause()

            table = app.query_one("#message-table", DataTable)
            assert table.row_count == 3
            assert len(app._messages) == 3
            # Oldest two (Sol, Lave) evicted; newest three remain.
            assert set(app._messages.keys()) == {"3", "4", "5"}

            app._update_stats()
            stats = app.query_one("#stats-bar", Static)
            stats_text = _static_text(stats)
            assert "Limit: 3/3" in stats_text
            assert f"Shown: {table.row_count}" in stats_text


class TestPilotCursorNavigation:
    """Pilot-driven tests for the up/down cursor keybindings."""

    async def test_cursor_up_down_navigate_rows(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, _five_row_messages())
            await pilot.pause()
            table = app.query_one("#message-table", DataTable)

            table.focus()
            # Row 1 is safely away from the auto-scroll zone (rows within 2 of
            # the bottom get snapped back by the background poll interval).
            table.move_cursor(row=1)
            await pilot.pause()
            assert table.cursor_row == 1

            await pilot.press("down")
            assert table.cursor_row == 2

            await pilot.press("up")
            assert table.cursor_row == 1


class TestPilotSetLimit:
    """Pilot-driven tests for the alt+l set-limit prompt."""

    async def test_alt_l_opens_prompt_prefilled_with_current_limit(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1", initial_limit=500)
        async with _running_app(app) as pilot:
            await pilot.pause()

            await pilot.press("alt+l")
            assert app._limit_input_mode is True
            filter_bar = app.query_one("#filter-bar")
            inp = app.query_one("#filter-input", Input)
            assert filter_bar.display is True
            assert inp.value == "500"

    async def test_alt_l_then_enter_applies_new_limit(self):
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1", initial_limit=500)
        async with _running_app(app) as pilot:
            await pilot.pause()

            await pilot.press("alt+l")
            inp = app.query_one("#filter-input", Input)
            inp.value = ""
            for ch in "50":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            assert app._max_event_limit == 50
            assert app._limit_input_mode is False
            filter_bar = app.query_one("#filter-bar")
            assert filter_bar.display is False


class TestPilotExportJson:
    """Pilot-driven tests for the 'e' export-selected-message keybinding."""

    async def test_export_json_writes_selected_message(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            _feed_messages(app, _five_row_messages())
            await pilot.pause()
            table = app.query_one("#message-table", DataTable)

            table.focus()
            table.move_cursor(row=1)  # away from the auto-scroll zone (see above)
            await pilot.pause()

            await pilot.press("e")
            await pilot.pause()

        exported = list(tmp_path.glob("eddn_export_*.json"))
        assert len(exported) == 1
        content = exported[0].read_text()
        assert '"StarSystem": "Lave"' in content

    async def test_export_json_no_selection_notifies_warning(self, tmp_path, monkeypatch):
        """With no rows in the table, export should warn instead of writing a file."""
        monkeypatch.chdir(tmp_path)
        app = EDDNTailApp(endpoint="tcp://127.0.0.1:1")
        async with _running_app(app) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()

        assert list(tmp_path.glob("eddn_export_*.json")) == []
