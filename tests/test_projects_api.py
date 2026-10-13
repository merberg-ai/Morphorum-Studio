"""Project parsing and the conditional write calls (no Qt, no network)."""
import json
from urllib.error import HTTPError

import pytest
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.projects import (
    MAX_NOTES, ProjectsApi, clean_name, parse_project, parse_project_list, parse_renders,
    valid_project_id,
)

ETAG = '"' + "a" * 64 + '"'
ETAG2 = '"' + "b" * 64 + '"'
PROJECT = {"project": {
    "id": "demo-1", "name": "Demo", "notes": "hello\x00 world", "created_at": "2026-10-01T00:00:00Z",
    "updated_at": "2026-10-02T00:00:00Z",
    "animation": {"width": 512, "height": 768, "fps": 12, "max_frames": 120, "mode": "2D"},
    "model": {"model_id": "sdxl-aaa", "family": "sdxl"},
    "prompts": {"30": "later", "0": "first"},
    "motion_lab": {"layers": [{}, {}]}, "hybrid": {"enabled": True},
}}


def response(payload, etag=None):
    r = FakeResponse(payload)
    if etag:
        r.headers["ETag"] = etag
    return r


def api(*responses):
    opener = FakeOpener(list(responses))
    return ProjectsApi(BackendClient("http://localhost", "tok", opener=opener)), opener


def test_ids():
    assert valid_project_id("demo-1.a_b")
    for bad in ("", "../x", "A", "a/b", "-a", "a" * 97, None, 5):
        assert not valid_project_id(bad)


def test_list_skips_bad_rows():
    rows = parse_project_list({"projects": [
        {"id": "ok", "name": "Ok", "width": 512, "height": 512, "fps": 12, "max_frames": 24},
        {"id": "../bad", "name": "Bad"}, {"id": "noname"}, "junk",
        {"id": "z", "name": "Zero", "width": 0, "fps": "x"},
    ]})
    assert [p.id for p in rows] == ["ok", "z"]
    assert rows[0].duration_seconds == 2.0
    assert rows[1].width is None and rows[1].fps is None and rows[1].duration_seconds is None


def test_list_requires_list():
    with pytest.raises(BackendError):
        parse_project_list({"projects": "no"})


def test_detail():
    d = parse_project(PROJECT)
    assert d.notes == "hello  world"
    assert (d.width, d.height, d.fps, d.max_frames) == (512, 768, 12, 120)
    assert d.first_prompt == "first" and d.prompt_keyframes == 2
    assert d.motion_layers == 2 and d.hybrid_enabled


def test_detail_missing_pieces():
    d = parse_project({"project": {"id": "x", "name": "X"}})
    assert d.notes == "" and d.width is None and d.motion_layers == 0 and not d.hybrid_enabled
    for bad in ({}, {"project": {"id": "BAD", "name": "X"}}, {"project": {"id": "x"}}):
        with pytest.raises(BackendError):
            parse_project(bad)


def test_renders():
    out = parse_renders({"renders": [{"id": "r1", "status": "done", "latest_completed_frame": 9},
                                     {"status": "x"}, {"id": "r2"}]})
    assert [r.id for r in out] == ["r1", "r2"]
    assert out[0].latest_frame == 9 and out[1].latest_frame is None


def test_clean_name():
    assert clean_name("  hi\x00there ") == "hi there"
    for bad in ("", "   ", "x" * 121):
        with pytest.raises(ValueError):
            clean_name(bad)


def test_open_returns_strong_etag_and_rejects_missing():
    a, opener = api(response(PROJECT, ETAG))
    detail, etag = a.open("demo-1")
    assert detail.id == "demo-1" and etag == ETAG
    assert opener.requests[0][0].full_url.endswith("/api/animation/projects/demo-1")
    for tag in (None, 'W/"' + "a" * 64 + '"', '"short"'):
        a, _ = api(response(PROJECT, tag))
        with pytest.raises(BackendError):
            a.open("demo-1")


def test_save_sends_only_name_notes_and_if_match():
    a, opener = api(response(PROJECT, ETAG2))
    detail, etag = a.save("demo-1", ETAG, " New ", "n")
    request = opener.requests[0][0]
    assert request.get_method() == "PUT"
    assert request.get_header("If-match") == ETAG
    assert json.loads(request.data) == {"name": "New", "notes": "n"}
    assert etag == ETAG2 and detail.id == "demo-1"


def test_save_precondition_failed_includes_detail():
    err = HTTPError("http://localhost/x", 412, "x", {}, __import__("io").BytesIO(
        b'{"detail":"Project changed"}'))
    a, _ = api(err)
    with pytest.raises(BackendError) as exc:
        a.save("demo-1", ETAG, "n", "")
    assert exc.value.code == "PRECONDITION_FAILED"
    assert "Project changed" in str(exc.value)


def test_save_validation():
    a, opener = api()
    with pytest.raises(ValueError):
        a.save("demo-1", ETAG, "n", "x" * (MAX_NOTES + 1))
    with pytest.raises(ValueError):
        a.save("demo-1", "bad", "n", "")
    with pytest.raises(ValueError):
        a.save("../x", ETAG, "n", "")
    assert opener.requests == []


def test_create_posts_only_name():
    a, opener = api(response(PROJECT))
    assert a.create(" Demo ").id == "demo-1"
    request = opener.requests[0][0]
    assert request.get_method() == "POST" and json.loads(request.data) == {"name": "Demo"}
    assert request.get_header("If-match") is None


def test_trash_is_bodyless_delete():
    a, opener = api(response({"ok": True}))
    a.trash("demo-1")
    request = opener.requests[0][0]
    assert request.get_method() == "DELETE" and request.data is None


def test_writes_not_retried():
    from urllib.error import URLError
    a, opener = api(URLError("down"), response(PROJECT))
    with pytest.raises(BackendError):
        a.create("x")
    assert len(opener.requests) == 1


def test_send_json_guards():
    c = BackendClient("http://localhost", "t", opener=FakeOpener([]))
    with pytest.raises(ValueError):
        c.send_json("GET", "/api/x")
    with pytest.raises(ValueError):
        c.send_json("DELETE", "/api/x", {"a": 1})
    with pytest.raises(ValueError):
        c.send_json("POST", "/api/x", {"a": 1}, if_match=ETAG)
    with pytest.raises(ValueError):
        c.send_json("POST", "/api/x", {"a": "x" * 300_000})
