"""Console parsing, SSE framing and the stream line reader (no Qt, no network)."""
import json

import pytest
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.console import (
    ConsoleApi, Gap, Reset, iter_sse, parse_entry, parse_snapshot,
)

ENTRY = {"id": 7, "timestamp": "2026-10-13T08:00:00.123+00:00", "level": "WARNING",
         "category": "API", "message": "GET /api/x -> 404"}


def sse(*blocks):
    return "".join(blocks).encode()


def block(event, payload, id_=None):
    head = f"id: {id_}\n" if id_ is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(payload)}\n\n"


def stream_response(body: bytes):
    return FakeResponse(body, content_type="text/event-stream")


def test_parse_entry_normalises_and_bounds():
    e = parse_entry(ENTRY)
    assert (e.id, e.level, e.category) == (7, "warning", "api")
    assert parse_entry({**ENTRY, "level": "fatal"}).level == "critical"
    assert parse_entry({**ENTRY, "level": "weird"}).level == "info"
    assert parse_entry({**ENTRY, "category": "bad cat!"}).category == "runtime"
    assert len(parse_entry({**ENTRY, "message": "x" * 9000}).message) == 4000
    for bad in ({}, [], {**ENTRY, "id": -1}, {**ENTRY, "id": "7"}):
        with pytest.raises(BackendError):
            parse_entry(bad)


def test_parse_snapshot_skips_bad_and_reads_boot():
    entries, boot = parse_snapshot({"events": [ENTRY, {"id": "x"}, "junk"], "boot_id": "abc123"})
    assert [e.id for e in entries] == [7] and boot == "abc123"
    assert parse_snapshot({"events": [], "boot_id": "bad id!"})[1] is None
    with pytest.raises(BackendError):
        parse_snapshot({"nope": 1})


def test_iter_sse_groups_events_and_skips_heartbeats():
    lines = [": heartbeat", "", "id: 1", "event: console", 'data: {"a":1}', "",
             "data: one", "data: two", "", "event: orphan", ""]
    assert list(iter_sse(iter(lines))) == [("console", '{"a":1}'), ("message", "one\ntwo")]


def test_iter_sse_bounds_event_data():
    lines = ["event: console"] + ["data: " + "x" * 9000] * 5 + [""]
    (_, data), = list(iter_sse(iter(lines)))
    assert len(data) <= 16_384


def test_snapshot_request_and_limits():
    opener = FakeOpener([FakeResponse({"events": [ENTRY], "boot_id": "b1"})])
    api = ConsoleApi(BackendClient("http://localhost", "t", opener=opener))
    entries, boot = api.snapshot(5_000_000, 9999)
    url = opener.requests[0][0].full_url
    assert "after_id=5000000" in url and "limit=1500" in url and boot == "b1" and len(entries) == 1


def test_stream_yields_entries_gaps_and_resets():
    body = sse(": heartbeat\n\n", block("console", ENTRY, 7),
               block("console_gap", {"first_available": 40}),
               block("console_reset", {"reason": "backend_restarted"}),
               "event: console\ndata: not json\n\n", block("console", {"id": "bad"}))
    opener = FakeOpener([stream_response(body)])
    api = ConsoleApi(BackendClient("http://localhost", "t", opener=opener))
    out = list(api.stream(6, "boot1", lambda: False))
    assert out[0].id == 7 and out[1] == Gap(40) and isinstance(out[2], Reset) and len(out) == 3
    req = opener.requests[0][0]
    assert "after_id=6" in req.full_url and "boot_id=boot1" in req.full_url
    assert req.get_header("Accept") == "text/event-stream" and req.get_header("Authorization") == "Bearer t"


def test_stream_stops_on_request():
    body = sse(block("console", ENTRY, 7), block("console", {**ENTRY, "id": 8}, 8))
    api = ConsoleApi(BackendClient("http://localhost", opener=FakeOpener([stream_response(body)])))
    flags = iter([False, False, True, True, True, True, True, True])
    out = list(api.stream(0, None, lambda: next(flags)))
    assert len(out) < 2


def test_stream_rejects_wrong_content_type_and_bad_boot_id():
    api = ConsoleApi(BackendClient("http://localhost", opener=FakeOpener([FakeResponse({"a": 1})])))
    with pytest.raises(BackendError) as exc:
        list(api.stream(0, None, lambda: False))
    assert exc.value.code == "INVALID_RESPONSE"
    opener = FakeOpener([stream_response(b"")])
    list(ConsoleApi(BackendClient("http://localhost", opener=opener)).stream(0, "../evil", lambda: False))
    assert "boot_id" not in opener.requests[0][0].full_url


def test_stream_line_too_long_is_an_error():
    api = ConsoleApi(BackendClient("http://localhost",
                                   opener=FakeOpener([stream_response(b"data: " + b"x" * 70_000 + b"\n")])))
    with pytest.raises(BackendError):
        list(api.stream(0, None, lambda: False))
