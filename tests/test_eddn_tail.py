"""Tests for eddn_tail — EDDN stream TUI."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import time
import zlib

import pytest
import zmq

from eddn_tail import (
    EDDN_ENDPOINTS,
    EDDNReceiver,
    EDDNTailApp,
    SCHEMA_COLORS,
    SCHEMA_EVENT,
    SCHEMA_SHORT,
    build_parser,
    extract_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compress(data: dict) -> bytes:
    """JSON-encode and zlib-compress an EDDN message dict."""
    return zlib.compress(json.dumps(data).encode())


def _bind_pub():
    """Create a PUB socket bound to an ephemeral port, return (ctx, pub, url).

    EDDNReceiver creates its own zmq.Context internally, so inproc://
    (which requires same-context) won't work. We use tcp://127.0.0.1
    with a random port instead.
    """
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    port = pub.bind_to_random_port("tcp://127.0.0.1")
    url = f"tcp://127.0.0.1:{port}"
    time.sleep(0.15)  # allow SUB connection to establish
    return ctx, pub, url


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
        assert s["raw"] is msg

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

    @staticmethod
    def _setup_receiver():
        """Bind a PUB socket, create an EDDNReceiver connected to it, and wait.

        Returns (ctx, pub, receiver) ready for publishing.
        """
        ctx = zmq.Context()
        pub = ctx.socket(zmq.PUB)
        port = pub.bind_to_random_port("tcp://127.0.0.1")
        url = f"tcp://127.0.0.1:{port}"
        # Create receiver after PUB is bound so connection can establish
        receiver = EDDNReceiver(url, topic_filter="")
        # Sleep to allow ZMQ SUB connection handshake to complete
        time.sleep(0.3)
        return ctx, pub, receiver

    def test_receive_valid_message(self):
        ctx, pub, receiver = self._setup_receiver()
        msg = {
            "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
            "header": {"uploaderID": "test"},
            "message": {"event": "Scan", "StarSystem": "Sol"},
        }
        pub.send(_compress(msg))
        result = receiver.recv_message()
        receiver.close()
        pub.close(linger=0)
        ctx.term()
        assert result is not None
        assert result["message"]["event"] == "Scan"

    def test_timeout_returns_none(self):
        """Receiver with no publisher sending should time out and return None."""
        ctx, pub, url = _bind_pub()
        receiver = EDDNReceiver(url)
        result = receiver.recv_message()
        receiver.close()
        pub.close(linger=0)
        ctx.term()
        assert result is None

    def test_invalid_zlib_returns_error(self):
        """Sending raw (non-zlib) bytes should produce an _error dict."""
        ctx, pub, receiver = self._setup_receiver()
        pub.send(b"this is not zlib compressed")
        result = receiver.recv_message()
        receiver.close()
        pub.close(linger=0)
        ctx.term()
        assert result is not None
        assert "_error" in result

    def test_invalid_json_returns_error(self):
        """Sending zlib-compressed non-JSON should produce an _error dict."""
        ctx, pub, receiver = self._setup_receiver()
        pub.send(zlib.compress(b"not valid json{"))
        result = receiver.recv_message()
        receiver.close()
        pub.close(linger=0)
        ctx.term()
        assert result is not None
        assert "_error" in result

    def test_close_no_error(self):
        """close() should not raise."""
        ctx, pub, url = _bind_pub()
        receiver = EDDNReceiver(url)
        receiver.close()
        pub.close(linger=0)
        ctx.term()
        # If we get here without exception, the test passes


# ---------------------------------------------------------------------------
# 3. _matches_filters()
# ---------------------------------------------------------------------------

class TestMatchesFilters:
    """Tests for the _matches_filters method on EDDNTailApp."""

    def _make_app(self, **kwargs):
        app = EDDNTailApp(endpoint="tcp://localhost:9999", **kwargs)
        return app

    def _scan_summary(self):
        return extract_summary({
            "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
            "header": {
                "uploaderID": "cmdr1",
                "softwareName": "EDMC",
                "softwareVersion": "5.0",
                "gatewayTimestamp": "2026-05-10T22:36:19Z",
            },
            "message": {
                "event": "Scan",
                "StarSystem": "Sol",
                "BodyName": "Earth",
            },
        })

    def _commodity_summary(self):
        return extract_summary({
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
            },
        })

    def test_no_filters_match_everything(self):
        app = self._make_app()
        assert app._matches_filters(self._scan_summary()) is True
        assert app._matches_filters(self._commodity_summary()) is True

    def test_event_filter_case_insensitive(self):
        app = self._make_app(event_filter="scan")
        assert app._matches_filters(self._scan_summary()) is True
        assert app._matches_filters(self._commodity_summary()) is False

    def test_event_filter_substring(self):
        app = self._make_app(event_filter="Sc")
        assert app._matches_filters(self._scan_summary()) is True

    def test_system_filter(self):
        app = self._make_app(system_filter="sol")
        assert app._matches_filters(self._scan_summary()) is True
        assert app._matches_filters(self._commodity_summary()) is False

    def test_station_filter(self):
        app = self._make_app(station_filter="lave station")
        assert app._matches_filters(self._commodity_summary()) is True
        assert app._matches_filters(self._scan_summary()) is False

    def test_schema_filter(self):
        app = self._make_app(schema_filter="journal/1")
        assert app._matches_filters(self._scan_summary()) is True
        assert app._matches_filters(self._commodity_summary()) is False

    def test_combined_filters_and_logic(self):
        app = self._make_app(event_filter="scan", system_filter="sol")
        s = self._scan_summary()
        assert app._matches_filters(s) is True

    def test_combined_filters_one_fails(self):
        app = self._make_app(event_filter="scan", system_filter="lave")
        s = self._scan_summary()
        assert app._matches_filters(s) is False  # system is Sol, not Lave

    def test_live_filter_valid_regex(self):
        app = self._make_app()
        app._live_filter = "sol|lave"
        assert app._matches_filters(self._scan_summary()) is True
        assert app._matches_filters(self._commodity_summary()) is True

    def test_live_filter_regex_case_insensitive(self):
        app = self._make_app()
        app._live_filter = "SOL"
        assert app._matches_filters(self._scan_summary()) is True

    def test_live_filter_invalid_regex_falls_back_to_substring(self):
        app = self._make_app()
        app._live_filter = "[invalid"
        # Should not crash; falls back to substring match
        s = self._scan_summary()
        # "[invalid" is not a substring anywhere in the haystack
        assert app._matches_filters(s) is False

    def test_live_filter_valid_regex_substring_match(self):
        app = self._make_app()
        app._live_filter = "Scan"
        # "Scan" is a valid regex AND a substring in the haystack
        assert app._matches_filters(self._scan_summary()) is True

    def test_live_filter_non_matching(self):
        app = self._make_app()
        app._live_filter = "zzz_nonexistent"
        assert app._matches_filters(self._scan_summary()) is False

    def test_empty_event_no_match(self):
        """A summary with empty event should not match a non-empty event_filter."""
        app = self._make_app(event_filter="Scan")
        empty_summary = extract_summary({
            "$schemaRef": "",
            "header": {},
            "message": {},
        })
        assert app._matches_filters(empty_summary) is False

    def test_commodity_event_matches_commodity_filter(self):
        """A commodity/3 message with derived event='commodity' matches 'commodity' filter."""
        app = self._make_app(event_filter="commodity")
        commodity_summary = extract_summary({
            "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {"uploaderID": "trader"},
            "message": {"systemName": "Lave", "stationName": "Lave Station"},
        })
        assert app._matches_filters(commodity_summary) is True

    def test_commodity_event_does_not_match_scan_filter(self):
        """A commodity/3 message with derived event should not match 'Scan' filter."""
        app = self._make_app(event_filter="scan")
        commodity_summary = extract_summary({
            "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
            "header": {"uploaderID": "trader"},
            "message": {"systemName": "Lave", "stationName": "Lave Station"},
        })
        assert app._matches_filters(commodity_summary) is False


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

    def _make_app(self):
        return EDDNTailApp(endpoint="tcp://localhost:9999")

    def test_clear_events_resets_state(self):
        """Clearing events empties _messages and resets counters."""
        app = self._make_app()
        # Populate state
        app._messages = {
            "1": {"event": "Scan", "system": "Sol", "raw": {}},
            "2": {"event": "FSDJump", "system": "Deciat", "raw": {}},
        }
        app._msg_count = 10
        app._filtered_count = 3

        # Only test the pure-state logic — mock out widget calls
        app.query_one = lambda selector, type=None: _FakeWidget()
        app.notify = lambda msg: None

        app.action_clear_events()

        assert app._messages == {}
        assert app._msg_count == 0
        assert app._filtered_count == 0

    def test_clear_events_after_clear_rate_resets(self):
        """After clearing, _app_start_time is updated so rate is sensible."""
        app = self._make_app()
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
        app = self._make_app()
        app._messages = {"1": {"event": "Scan", "system": "Sol", "raw": {}}}
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
        app = self._make_app()
        app._messages = {"1": {"event": "Scan", "system": "Sol", "raw": {}}}
        app.query_one = lambda selector, type=None: _FakeWidget()

        notified = []
        app.notify = lambda msg: notified.append(msg)

        app.action_clear_events()

        assert notified == ["Events cleared"]

    def test_clear_events_updates_pane_titles(self):
        """After clearing, _update_pane_titles and _update_stats are called."""
        app = self._make_app()
        app._messages = {"1": {"event": "Scan", "system": "Sol", "raw": {}}}
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


class _FakeWidget:
    """Minimal stand-in for Textual widgets used in unit tests."""
    def clear(self):
        pass
    def update(self, text=""):
        pass
    rows = []
    border_title = ""
    display = True
