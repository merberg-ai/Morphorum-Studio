"""Video export parsing, calls, verified download and the playback cache (no Qt, no network)."""
import hashlib
import json

import pytest
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.images import SubmissionJournal
from morphorum_studio.backend.videos import (
    VideoApi, audio_text, cached_video, describe, parse_availability, parse_export,
    parse_exports, prune_cache,
)

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"v" * 4000
SHA = hashlib.sha256(MP4).hexdigest()
EXPORT = {
    "id": "video-0123456789ab", "project_id": "demo", "render_id": "render-20261013-1",
    "format": "mp4", "quality": "balanced", "fps": 24, "total_frames": 48, "audio_included": True,
    "audio_source": "imported_soundtrack", "audio_offset_seconds": 0.5, "status": "completed",
    "progress": 1.0, "message": "Done", "error": None, "bytes": len(MP4), "sha256": SHA,
    "path": "D:\\secret\\x.mp4", "url": "/api/x",
}


def api(*responses):
    opener = FakeOpener(list(responses))
    return VideoApi(BackendClient("http://localhost", "tok", opener=opener)), opener


def test_availability_defaults_closed():
    assert not parse_availability({}).available
    a = parse_availability({"available": True, "formats": ["mp4", "avi"], "qualities": ["high"]})
    assert a.available and a.formats == ("mp4",) and a.qualities == ("high",)
    assert "FFmpeg" in parse_availability({"available": False, "message": "FFmpeg missing"}).message


def test_parse_export_and_no_secret_paths():
    e = parse_export(EXPORT)
    assert e.downloadable and e.final and e.audio_included and e.audio_offset == 0.5
    assert "secret" not in repr(e)
    assert "With audio (imported soundtrack, offset +0.5 s)" == audio_text(e)
    assert "MP4" in describe(e) and "24 fps" in describe(e)


def test_audio_is_never_claimed_without_evidence():
    e = parse_export({**EXPORT, "audio_included": "yes", "audio_source": "imported_soundtrack"})
    assert not e.audio_included and audio_text(e) == "No audio track"
    assert "No audio" in describe(e)


def test_incomplete_or_unsafe_records_rejected():
    for bad in ({}, [], {**EXPORT, "format": "avi"}, {**EXPORT, "quality": "x"}, {**EXPORT, "fps": 0},
                {**EXPORT, "fps": 500}, {**EXPORT, "render_id": "../x"}, {**EXPORT, "project_id": "../p"},
                {**EXPORT, "id": "../job"}, {**EXPORT, "status": None}):
        with pytest.raises(BackendError):
            parse_export(bad)


def test_not_downloadable_without_digest_or_when_unfinished():
    assert not parse_export({**EXPORT, "sha256": "zz"}).downloadable
    assert not parse_export({**EXPORT, "status": "encoding", "progress": 0.3}).downloadable
    assert parse_export({**EXPORT, "status": "interrupted", "sha256": None}).final


def test_parse_exports_skips_bad():
    out = parse_exports({"exports": [EXPORT, {"format": "avi"}, "junk"]})
    assert len(out) == 1
    with pytest.raises(BackendError):
        parse_exports({"nope": 1})


def test_start_sends_key_and_exact_body(tmp_path):
    journal = SubmissionJournal(tmp_path)
    body = {"format": "webm", "quality": "high"}
    entry = journal.begin("p1", {"project_id": "demo", "render_id": "render-20261013-1", "body": body},
                          kind="video")
    a, opener = api(FakeResponse({**EXPORT, "format": "webm", "status": "queued"}))
    a.start(entry)
    req = opener.requests[0][0]
    assert req.method == "POST" and req.full_url.endswith("/renders/demo/render-20261013-1/video")
    assert req.get_header("Idempotency-key") == entry.key and json.loads(req.data) == body
    assert [e.kind for e in journal.entries("p1", "video")] == ["video"]


def test_start_rejects_bad_ids(tmp_path):
    entry = SubmissionJournal(tmp_path).begin("p", {"project_id": "../x", "render_id": "r1", "body": {}},
                                              kind="video")
    a, _ = api()
    with pytest.raises(ValueError):
        a.start(entry)


def test_download_verifies_and_is_atomic(tmp_path):
    e = parse_export(EXPORT)
    dest = tmp_path / "out.mp4"
    good = FakeResponse(MP4, content_type="video/mp4")
    good.headers["X-Content-SHA256"] = SHA
    a, opener = api(good)
    assert a.download(e, dest) == str(dest) and dest.read_bytes() == MP4
    assert opener.requests[0][0].full_url.endswith("/video/mp4/balanced/24")
    assert not list(tmp_path.glob("*.part"))


def test_download_mismatch_keeps_existing_file(tmp_path):
    e = parse_export(EXPORT)
    dest = tmp_path / "out.mp4"
    dest.write_bytes(b"precious")
    a, _ = api(FakeResponse(MP4[:-1] + b"X", content_type="video/mp4"))
    with pytest.raises(BackendError):
        a.download(e, dest)
    assert dest.read_bytes() == b"precious" and not list(tmp_path.glob("*.part"))


def test_download_refuses_when_not_ready_or_bad_destination(tmp_path):
    a, _ = api()
    with pytest.raises(ValueError):
        a.download(parse_export({**EXPORT, "status": "encoding"}), tmp_path / "x.mp4")
    with pytest.raises(ValueError):
        a.download(parse_export(EXPORT), tmp_path / "missing" / "x.mp4")
    with pytest.raises(ValueError):
        a.download(parse_export(EXPORT), tmp_path)


def test_cache_reuses_only_intact_copies_and_prunes(tmp_path):
    e = parse_export(EXPORT)
    assert cached_video(tmp_path, e) is None
    f = tmp_path / f"{SHA[:24]}.mp4"
    f.write_bytes(MP4)
    assert cached_video(tmp_path, e) == f
    f.write_bytes(MP4[:-1] + b"X")
    assert cached_video(tmp_path, e) is None
    import os
    for i in range(8):
        p = tmp_path / f"{i:024d}.webm"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    prune_cache(tmp_path, keep=3)
    assert len(list(tmp_path.glob("*.webm"))) + len(list(tmp_path.glob("*.mp4"))) == 3
