"""Schedule validation and Deforum import parsing/calls (no Qt, no network)."""
import json

import pytest
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.deforum import DeforumApi, parse_preview, read_settings_file
from morphorum_studio.backend.validation import (
    ValidationApi, field_track_id, parse_validation, summary,
)

ISSUES = {"valid": False, "issues": [
    {"field": "motion.zoom", "severity": "error", "message": "zoom must stay above 0"},
    {"field": "tracks.prompts.positive", "severity": "warning", "message": "LoRA not found"},
    {"field": "x", "severity": "info", "message": "ignored severity"}, {"severity": "error"}, "junk"],
    "fields": {"motion.zoom": {"valid": False}}}


def test_field_to_track_mapping():
    assert field_track_id("motion.zoom") == "camera_2d.zoom"
    assert field_track_id("camera_3d.rotation_x") == "camera_3d.rotation_x"
    assert field_track_id("generation.steps") == "generation.steps"
    assert field_track_id("cadence.diffusion") == "cadence.diffusion"
    assert field_track_id("tracks.prompts.positive") == "prompts.positive"
    assert field_track_id("nonsense") is None


def test_parse_validation_keeps_only_well_formed_issues():
    v = parse_validation(ISSUES)
    assert not v.valid and len(v.issues) == 2 and len(v.errors) == 1 and len(v.warnings) == 1
    assert v.issues[0].track_id == "camera_2d.zoom"
    assert summary(v) == "motion.zoom: zoom must stay above 0"


def test_valid_only_when_backend_says_so_and_no_errors():
    assert parse_validation({"valid": True, "issues": []}).valid
    assert not parse_validation({"valid": False, "issues": []}).valid
    assert not parse_validation({"valid": True, "issues": [
        {"field": "a", "severity": "error", "message": "bad"}]}).valid
    with pytest.raises(BackendError):
        parse_validation({"valid": True})


def test_check_posts_the_complete_project():
    opener = FakeOpener([FakeResponse({"valid": True, "issues": []})])
    project = {"id": "demo", "animation": {}}
    ValidationApi(BackendClient("http://localhost", "t", opener=opener)).check(project)
    req = opener.requests[0][0]
    assert req.full_url.endswith("/api/animation/validate-schedules") and json.loads(req.data) == {"project": project}


PREVIEW = {
    "importer_version": 1, "source_filename": "settings.txt", "source_sha256": "a" * 64,
    "model_required": True, "selected_model": None,
    "project": {"name": "Imported", "animation": {"max_frames": 120, "fps": 24, "width": 512, "height": 768, "mode": "3d"},
                "compatibility": {"huge": "x" * 100}},
    "mappings": [
        {"source_key": "max_frames", "target": "animation.max_frames", "status": "mapped"},
        {"source_key": "sd_model", "target": None, "status": "ignored_path", "message": "passive metadata"},
        {"source_key": "mystery", "target": None, "status": "unmapped"}, {"nope": 1}],
    "warnings": ["a", "a2", 5], "unsupported_keys": ["controlnet"], "unmapped_keys": ["mystery"],
    "validation": {"valid": True, "issues": [{"field": "f", "severity": "warning", "message": "careful"}]},
    "can_create": False}


def test_parse_preview_summarises_without_keeping_the_project():
    p = parse_preview(PREVIEW)
    assert (p.frames, p.fps, p.size, p.mode, p.project_name) == (120, 24.0, (512, 768), "3d", "Imported")
    assert p.model_required and not p.can_create
    assert p.count("mapped") == 1 and p.count("ignored_path") == 1 and len(p.mappings) == 3
    assert p.warnings == ("a", "a2") and p.unsupported == ("controlnet",)
    assert p.validation.valid and len(p.validation.warnings) == 1
    assert "huge" not in repr(p)
    for bad in ({}, {**PREVIEW, "project": []}, {**PREVIEW, "validation": None}):
        with pytest.raises(BackendError):
            parse_preview(bad)


def test_can_create_requires_the_backend_flag():
    assert parse_preview({**PREVIEW, "can_create": True}).can_create
    assert not parse_preview({**PREVIEW, "can_create": "yes"}).can_create


def test_preview_and_create_calls():
    created = {"status": "created", "project": {"id": "imported-1", "name": "Imported"},
               "import": {"warnings": ["w"]}}
    opener = FakeOpener([FakeResponse(PREVIEW), FakeResponse(created)])
    api = DeforumApi(BackendClient("http://localhost", "t", opener=opener))
    api.preview("{}", "s.txt", None, "  ")
    body = json.loads(opener.requests[0][0].data)
    assert body == {"content": "{}", "filename": "s.txt"}
    result = api.create("{}", "s.txt", "model-1", " My Name ")
    assert json.loads(opener.requests[1][0].data) == {
        "content": "{}", "filename": "s.txt", "model_id": "model-1", "name": "My Name"}
    assert (result.project_id, result.warnings) == ("imported-1", ("w",))


def test_create_refusals_before_any_request():
    api = DeforumApi(BackendClient("http://localhost", opener=FakeOpener([])))
    with pytest.raises(ValueError):
        api.create("{}", "s.txt", "", None)
    with pytest.raises(ValueError):
        api.preview("", "s.txt", None, None)
    with pytest.raises(ValueError):
        api.preview("x" * 1_048_577, "s.txt", None, None)
    bad = FakeResponse({"status": "created", "project": {"id": "../x"}})
    with pytest.raises(BackendError):
        DeforumApi(BackendClient("http://localhost", opener=FakeOpener([bad]))).create("{}", "s", "m", None)


def test_read_settings_file(tmp_path):
    good = tmp_path / "settings.txt"
    good.write_bytes(b"\xef\xbb\xbf{\"a\": 1}")
    assert read_settings_file(good) == ("settings.txt", '{"a": 1}')
    empty = tmp_path / "e.txt"
    empty.write_bytes(b"")
    big = tmp_path / "b.txt"
    big.write_bytes(b"x" * 1_048_577)
    binary = tmp_path / "c.txt"
    binary.write_bytes(b"\xff\xfe\x00bad")
    for path in (empty, big, binary, tmp_path / "missing.txt"):
        with pytest.raises(ValueError):
            read_settings_file(path)
