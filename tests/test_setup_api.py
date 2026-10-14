"""New-project setup, LoRA inspection and start-mode calls (no Qt, no network)."""
import json

import pytest
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.loras import LoraApi, parse_lora_detail
from morphorum_studio.backend.projects import ProjectsApi
from morphorum_studio.backend.setup import (
    Choices, SetupApi, apply_choices, check_choices, has_errors,
)

CAMERA = {"translation_x": "0:(0)", "translation_z": "0:(0)", "fov": "0:(40)", "projection_mode": "legacy"}
TEMPLATE = {
    "schema_version": 5, "id": "x", "name": "Template", "created_at": "t", "updated_at": "t",
    "animation": {"max_frames": 120, "fps": 24.0, "width": 1024, "height": 1024, "mode": "2d",
                  "start_mode": "prompt", "prompt_transition": "blend"},
    "model": {"model_id": "", "family": "", "variant": ""},
    "prompts": {"0": ""}, "negative_prompts": {"0": ""}, "camera_3d": dict(CAMERA),
    "generation": {"strength": "0:(0.65)"}, "tracks": {"camera_3d.translation_z": {}},
}
GOOD = Choices(name="  My Film ", model_id="m1", family="SDXL", variant="Base", prompt=" a fox ")
ETAG = '"' + "a" * 64 + '"'


def client(*responses):
    opener = FakeOpener(list(responses))
    return BackendClient("http://localhost", "tok", opener=opener), opener


def codes(issues):
    return {(i.field, i.severity) for i in issues}


def test_good_choices_have_no_errors_and_blank_prompt_only_warns():
    assert not has_errors(check_choices(GOOD))
    blank = check_choices(Choices(model_id="m1"))
    assert not has_errors(blank) and ("prompt", "warning") in codes(blank)


def test_each_bad_choice_is_an_error():
    bad = Choices(name=" ", width=10, height=99999, fps=0, frames=0, mode="4d",
                  start_mode="x", model_id="")
    found = codes(check_choices(bad))
    for field in ("name", "width", "height", "fps", "frames", "mode", "start_mode", "model"):
        assert (field, "error") in found
    assert has_errors(check_choices(Choices(model_id="m", prompt="x" * 4001)))


def test_odd_and_huge_sizes_warn_and_source_start_explains():
    found = codes(check_choices(Choices(model_id="m", width=1001, height=5000, start_mode="source")))
    assert ("width", "warning") in found and ("size", "warning") in found
    assert ("start_mode", "warning") in found


def test_apply_overlays_choices_and_leaves_everything_else_alone():
    project = apply_choices(TEMPLATE, GOOD)
    assert project["name"] == "My Film"
    assert project["animation"]["width"] == 1024 and project["animation"]["prompt_transition"] == "blend"
    assert project["model"] == {"model_id": "m1", "family": "sdxl", "variant": "base"}
    assert project["prompts"] == {"0": "a fox"} and project["negative_prompts"] == {"0": ""}
    assert project["generation"] == TEMPLATE["generation"]
    for key in ("id", "created_at", "updated_at", "tracks"):
        assert key not in project
    assert "tracks" in TEMPLATE and TEMPLATE["animation"]["mode"] == "2d"  # the template is not mutated


def test_three_d_mode_never_touches_camera_values():
    project = apply_choices(TEMPLATE, Choices(model_id="m", mode="3d", width=640, height=360, frames=48, fps=12))
    assert project["animation"]["mode"] == "3d" and project["animation"]["max_frames"] == 48
    assert project["camera_3d"] == CAMERA and project["camera_3d"]["translation_z"] == "0:(0)"


def test_template_fetch_and_validation():
    c, opener = client(FakeResponse({"project": TEMPLATE}))
    assert SetupApi(c).template()["animation"]["fps"] == 24.0
    assert opener.requests[0][0].full_url.endswith("/api/animation/project-template")
    for bad in ({}, {"project": {}}, {"project": {"animation": "x"}}):
        c, _ = client(FakeResponse(bad))
        with pytest.raises(BackendError):
            SetupApi(c).template()


def test_review_posts_the_would_be_project_to_validation():
    c, opener = client(FakeResponse({"valid": True, "issues": []}))
    assert SetupApi(c).review(TEMPLATE, GOOD).valid
    req = opener.requests[0][0]
    assert req.full_url.endswith("/api/animation/validate-schedules")
    sent = json.loads(req.data)["project"]
    assert sent["name"] == "My Film" and "tracks" not in sent


def test_create_posts_once_and_refuses_bad_choices_before_any_request():
    created = {"status": "created", "project": {"id": "my-film-1", "name": "My Film"}}
    c, opener = client(FakeResponse(created))
    detail = SetupApi(c).create(TEMPLATE, GOOD)
    assert detail.id == "my-film-1" and len(opener.requests) == 1
    req = opener.requests[0][0]
    assert req.get_method() == "POST" and req.full_url.endswith("/api/animation/projects")
    c, opener = client()
    with pytest.raises(BackendError) as info:
        SetupApi(c).create(TEMPLATE, Choices())
    assert info.value.code == "INVALID_REQUEST" and not opener.requests


LORA = {"name": "Fox\x00Style", "family": "sdxl", "adapter_format": "kohya", "tensor_count": 800,
        "metadata_base_model": "SDXL 1.0", "trigger_words": ["foxstyle", 5, "  "],
        "trigger_source": "sidecar", "ranks": [{"rank": 16, "modules": 480}, {"rank": "x"}, "junk"],
        "components": {"unet": 700, "text_encoder": 100, "text_encoder_2": 0},
        "warnings": ["w1", 3], "errors": [], "path": "/srv/secret/fox.safetensors"}


def test_parse_lora_detail_is_tolerant_and_drops_paths():
    d = parse_lora_detail("abc", LORA)
    assert d.name == "Fox Style" and d.trigger_words == ("foxstyle",)
    assert d.ranks == ("16 × 480",) and d.components == (("text_encoder", 100), ("unet", 700))
    assert d.warnings == ("w1",) and "secret" not in repr(d)
    assert parse_lora_detail("abc", {}).name == "abc"
    with pytest.raises(BackendError):
        parse_lora_detail("abc", [])


def test_inspect_uses_the_indexed_id_only():
    c, opener = client(FakeResponse(LORA))
    assert LoraApi(c).inspect("0123abcd").family == "sdxl"
    assert opener.requests[0][0].full_url.endswith("/api/loras/0123abcd/inspect")
    for bad in ("", "../x", "a/b", "a b", "-x", "a" * 101):
        with pytest.raises(BackendError):
            LoraApi(client()[0]).inspect(bad)


def test_library_lists_loras_only():
    c, opener = client(FakeResponse({"models": [
        {"id": "l1", "family": "sdxl", "kind": "loras", "name": "Fox"}]}))
    assert [m.id for m in LoraApi(c).library("sdxl")] == ["l1"]
    url = opener.requests[0][0].full_url
    assert "kind=loras" in url and "family=sdxl" in url


def test_start_mode_reads_the_revision_then_puts_a_conditional_partial():
    r = FakeResponse({"project": {"id": "demo", "name": "Demo"}})
    r.headers["ETag"] = ETAG
    c, opener = client(r, FakeResponse({"project": {"id": "demo", "name": "Demo"}}))
    ProjectsApi(c).set_start_mode("demo", "source")
    get, put = (req[0] for req in opener.requests)
    assert get.get_method() == "GET" and put.get_method() == "PUT"
    assert put.get_header("If-match") == ETAG
    assert json.loads(put.data) == {"animation": {"start_mode": "source"}}
    with pytest.raises(ValueError):
        ProjectsApi(client()[0]).set_start_mode("demo", "video")
