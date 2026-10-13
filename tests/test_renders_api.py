"""Render job parsing, calls, journal kinds and the raw project read (no Qt, no network)."""
import json

import pytest
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.images import SubmissionJournal
from morphorum_studio.backend.projects import ProjectsApi
from morphorum_studio.backend.renders import (
    RenderApi, parse_render, parse_render_list, render_text,
)

GIF = b"GIF89a" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
RENDER = {
    "id": "render-20261013-1", "project_id": "demo", "status": "rendering", "message": "Rendering",
    "progress": 0.4, "eta_seconds": 125.0, "current_frame": 9, "total_frames": 24,
    "current_step": 7, "current_step_total": 20, "load_progress": 1.0, "latest_completed_frame": 8,
    "results": [{"frame": i, "path": "D:\\secret"} for i in range(9)], "preview_url": None,
    "resumable": False, "resumed": False, "cancel_requested": False, "error": None,
    "created_at": "2026-10-13T08:00:00+00:00", "frame_seconds": 11.5, "average_frame_seconds": 12.0,
    "imported_soundtrack": {"enabled": True, "filename": "song.wav", "offset_seconds": 0.5},
    "hybrid_source": {"enabled": False},
}


def api(*responses):
    opener = FakeOpener(list(responses))
    return RenderApi(BackendClient("http://localhost", "tok", opener=opener)), opener


def test_parse_render_full():
    job = parse_render(RENDER)
    assert job.active and not job.final and job.latest_frame == 8 and job.completed_frames == 9
    assert job.soundtrack == "song.wav" and not job.hybrid and job.average_frame_seconds == 12.0
    assert "secret" not in repr(job)


def test_parse_render_tolerates_missing_and_rejects_bad():
    job = parse_render({"id": "r1", "project_id": "demo", "status": "queued", "progress": "x"})
    assert job.progress == 0.0 and job.latest_frame is None and job.completed_frames == 0
    for bad in ({}, {**RENDER, "id": "../x"}, {**RENDER, "project_id": "../p"}, {**RENDER, "status": None}, []):
        with pytest.raises(BackendError):
            parse_render(bad)


def test_latest_frame_falls_back_to_results():
    data = {k: v for k, v in RENDER.items() if k != "latest_completed_frame"}
    assert parse_render(data).latest_frame == 8


def test_resumed_and_interrupted_flags():
    job = parse_render({**RENDER, "status": "interrupted", "resumable": True})
    assert job.final and job.resumable
    assert "can be resumed" in render_text(job)


def test_parse_list_skips_bad():
    out = parse_render_list({"renders": [RENDER, {"id": "../no"}, "junk"]})
    assert len(out) == 1
    with pytest.raises(BackendError):
        parse_render_list({"renders": 5})


def test_render_text_variants():
    base = parse_render(RENDER)
    assert render_text(base) == "frame 10 of 24, step 7 of 20, about 2 min 05 s left"
    assert render_text(parse_render({**RENDER, "status": "queued", "resumed": True})) == "Waiting in the queue (resuming)"
    assert render_text(parse_render({**RENDER, "status": "loading_model", "load_message": "Loading SDXL",
                                      "load_progress": 0.5})) == "Loading SDXL (50%)"
    assert render_text(parse_render({**RENDER, "status": "completed"})) == "Done: 9 frames"
    assert render_text(parse_render({**RENDER, "status": "cancelled"})).startswith("Cancelled after 9 frames")
    assert render_text(parse_render({**RENDER, "status": "failed", "error": "out of memory"})) == "Failed: out of memory"


def test_journal_kinds_are_separate(tmp_path):
    j = SubmissionJournal(tmp_path)
    img = j.begin("p", {"prompt": "x"})
    ani = j.begin("p", {"project": {"id": "demo"}}, kind="animation")
    assert [e.key for e in j.entries("p", "image")] == [img.key]
    assert [e.key for e in j.entries("p", "animation")] == [ani.key]
    assert len(j.entries("p")) == 2
    submitted = j.submitted(ani, "render-1")
    assert submitted.kind == "animation"
    assert j.entries("p", "animation")[0].job_id == "render-1"
    with pytest.raises(ValueError):
        j.begin("p", {}, kind="audio")


def test_journal_accepts_large_project_payload(tmp_path):
    j = SubmissionJournal(tmp_path)
    big = {"project": {"id": "demo", "notes": "n" * 500_000}}
    entry = j.begin("p", big, kind="animation")
    assert j.entries("p")[0].payload == big and entry.kind == "animation"


def test_old_journal_files_default_to_image(tmp_path):
    j = SubmissionJournal(tmp_path)
    entry = j.begin("p", {"a": 1})
    path = tmp_path / (entry.key + ".json")
    data = json.loads(path.read_text())
    data.pop("kind")
    path.write_text(json.dumps(data))
    assert j.entries("p")[0].kind == "image"


def test_submit_posts_whole_project_with_key(tmp_path):
    j = SubmissionJournal(tmp_path)
    entry = j.begin("p", {"project": {"id": "demo", "x": [1, 2]}}, kind="animation")
    a, opener = api(FakeResponse(RENDER))
    job = a.submit(entry)
    request = opener.requests[0][0]
    assert request.full_url.endswith("/api/animation/renders") and request.get_method() == "POST"
    assert request.get_header("Idempotency-key") == entry.key
    assert json.loads(request.data) == {"project": {"id": "demo", "x": [1, 2]}} and job.id == RENDER["id"]


def test_get_cancel_resume_list_paths():
    a, opener = api(FakeResponse(RENDER), FakeResponse({**RENDER, "status": "cancelled"}),
                    FakeResponse({**RENDER, "status": "queued", "resumed": True}), FakeResponse({"renders": [RENDER]}))
    assert a.get("render-20261013-1").status == "rendering"
    assert a.cancel("render-20261013-1").status == "cancelled"
    assert a.resume("demo", "render-20261013-1").resumed
    assert len(a.for_project("demo")) == 1
    urls = [(r.get_method(), r.full_url.split("localhost")[1]) for r, _ in opener.requests]
    assert urls == [("GET", "/api/animation/renders/render-20261013-1"),
                    ("POST", "/api/animation/renders/render-20261013-1/cancel"),
                    ("POST", "/api/animation/renders/demo/render-20261013-1/resume"),
                    ("GET", "/api/animation/projects/demo/renders")]


def test_id_validation_before_network():
    a, opener = api()
    for call in (lambda: a.get("../x"), lambda: a.resume("../p", "r1"), lambda: a.resume("demo", "a/b"),
                 lambda: a.frame_bytes("demo", "r1", -1), lambda: a.frame_bytes("demo", "r1", "3"),
                 lambda: a.for_project("BAD")):
        with pytest.raises(ValueError):
            call()
    assert opener.requests == []


def test_frame_and_preview_checks():
    a, opener = api(FakeResponse(PNG, content_type="image/png"), FakeResponse(b"nope", content_type="text/plain"),
                    FakeResponse(GIF, content_type="image/gif"), FakeResponse(PNG, content_type="image/png"))
    assert a.frame_bytes("demo", "r1", 4) == PNG
    assert opener.requests[0][0].full_url.endswith("/renders/demo/r1/frames/4")
    with pytest.raises(BackendError):
        a.frame_bytes("demo", "r1", 4)
    assert a.preview_bytes("demo", "r1") == GIF
    with pytest.raises(BackendError):
        a.preview_bytes("demo", "r1")  # a PNG is not a GIF


def test_save_frame_and_preview(tmp_path):
    a, _ = api(FakeResponse(PNG, content_type="image/png"), FakeResponse(GIF, content_type="image/gif"),
               FakeResponse(b"junk", content_type="text/plain"))
    f = tmp_path / "f.png"
    g = tmp_path / "p.gif"
    assert a.save_frame("demo", "r1", 2, f) == str(f) and f.read_bytes() == PNG
    assert a.save_preview("demo", "r1", g) == str(g) and g.read_bytes() == GIF
    with pytest.raises(BackendError):
        a.save_frame("demo", "r1", 3, tmp_path / "bad.png")
    assert not (tmp_path / "bad.png").exists() and not (tmp_path / "bad.png.part").exists()
    with pytest.raises(ValueError):
        a.save_frame("demo", "r1", 3, tmp_path)


def test_raw_project_returns_whole_object():
    etag = '"' + "a" * 64 + '"'
    r = FakeResponse({"project": {"id": "demo", "name": "D", "animation": {"fps": 12}, "extra": [1]}})
    r.headers["ETag"] = etag
    opener = FakeOpener([r, FakeResponse({"project": {"id": "other"}})])
    p = ProjectsApi(BackendClient("http://localhost", "t", opener=opener))
    assert p.raw("demo")["extra"] == [1]
    with pytest.raises(BackendError):
        p.raw("demo")  # id mismatch


def test_send_json_size_limit_is_adjustable():
    c = BackendClient("http://localhost", "t", opener=FakeOpener([FakeResponse({})]))
    big = {"a": "x" * 300_000}
    with pytest.raises(ValueError):
        c.send_json("POST", "/api/x", big)
    c.send_json("POST", "/api/x", big, max_bytes=2 * 1024 * 1024)
