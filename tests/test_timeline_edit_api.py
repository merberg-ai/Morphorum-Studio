"""Keyframe edit planning and calls (no Qt, no network)."""
import json

import pytest
from test_backend_client import FakeOpener, FakeResponse
from test_timeline_api import SNAPSHOT

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.timeline import (
    EditApi, EditError, Op, parse_timeline, plan_delete, plan_interpolation, plan_move, plan_set,
)

T = parse_timeline(SNAPSHOT)
ZOOM = T.track("camera_2d.zoom")
ANGLE = T.track("camera_2d.angle")
PROMPT = T.track("prompts.positive")


def test_set_changes_existing_and_adds_new_with_exact_inverses():
    change = plan_set(ZOOM, 0, " 1.2 ", 48)
    assert change.forward == (Op("upsert", "camera_2d.zoom", 0, "1.2"),)
    assert change.inverse == (Op("upsert", "camera_2d.zoom", 0, "1.0"),)
    add = plan_set(ZOOM, 10, "2", 48)
    assert add.inverse == (Op("delete", "camera_2d.zoom", 10),) and add.label.startswith("Add")


def test_set_refusals():
    with pytest.raises(EditError):
        plan_set(ZOOM, 0, "1.0", 48)  # no change
    with pytest.raises(EditError):
        plan_set(ZOOM, 0, "  ", 48)  # numeric needs a value
    with pytest.raises(EditError):
        plan_set(ZOOM, 99, "1", 48)  # out of range
    with pytest.raises(EditError):
        plan_set(ZOOM, 0, "x" * 4001, 48)
    assert plan_set(PROMPT, 5, "", 48).forward[0].value == ""  # an empty prompt is a valid prompt


def test_keyframes_with_frame_expressions_are_not_editable():
    snap = json.loads(json.dumps(SNAPSHOT))
    snap["tracks"]["camera_2d"]["zoom"]["keyframes"][1]["frame_expression"] = "t*2"
    zoom = parse_timeline(snap).track("camera_2d.zoom")
    for call in (lambda: plan_set(zoom, 24, "3", 48), lambda: plan_delete(zoom, 24, 48),
                 lambda: plan_move(zoom, 24, 30, 48)):
        with pytest.raises(EditError):
            call()


def test_delete_and_prompt_frame_zero_rule():
    d = plan_delete(ZOOM, 24, 48)
    assert d.forward == (Op("delete", "camera_2d.zoom", 24),)
    assert d.inverse == (Op("upsert", "camera_2d.zoom", 24, "1+0.5*sin(t)"),)
    with pytest.raises(EditError):
        plan_delete(PROMPT, 0, 48)
    with pytest.raises(EditError):
        plan_delete(ZOOM, 7, 48)


def test_move_plain_and_overwrite():
    m = plan_move(ZOOM, 24, 30, 48)
    assert m.forward == (Op("move", "camera_2d.zoom", 24, target=30, overwrite=False),)
    assert m.inverse == (Op("move", "camera_2d.zoom", 30, target=24),)
    with pytest.raises(EditError):
        plan_move(ZOOM, 24, 0, 48)  # occupied, no overwrite
    o = plan_move(ZOOM, 24, 0, 48, overwrite=True)
    assert o.forward[0].overwrite is True
    assert o.inverse == (Op("move", "camera_2d.zoom", 0, target=24), Op("upsert", "camera_2d.zoom", 0, "1.0"))
    for bad in ((7, 8), (24, 24), (24, 99)):
        with pytest.raises(EditError):
            plan_move(ZOOM, *bad, 48)
    with pytest.raises(EditError):
        plan_move(PROMPT, 0, 5, 48)


def test_interpolation_plan():
    p = plan_interpolation(ZOOM, "hold")
    assert p.inverse == (Op("interp", "camera_2d.zoom", value="linear"),)
    for mode in ("linear", "blend"):
        with pytest.raises(EditError):
            plan_interpolation(ZOOM, mode)


def api(*responses):
    opener = FakeOpener(list(responses))
    return EditApi(BackendClient("http://localhost", "t", opener=opener)), opener


def test_ops_map_to_the_documented_calls():
    a, opener = api(*(FakeResponse({"status": "saved"}) for _ in range(4)))
    a.run("demo", Op("upsert", "camera_2d.zoom", 5, "2"))
    a.run("demo", Op("delete", "camera_2d.zoom", 5))
    a.run("demo", Op("move", "camera_2d.zoom", 5, target=9, overwrite=True))
    a.run("demo", Op("interp", "camera_2d.zoom", value="hold"))
    reqs = [r for r, _ in opener.requests]
    base = "/api/animation/projects/demo/timeline/tracks/camera_2d/zoom"
    assert [(r.method, r.full_url.split("localhost")[1]) for r in reqs] == [
        ("PUT", base + "/keyframes/5"), ("DELETE", base + "/keyframes/5"),
        ("POST", base + "/keyframes/5/move"), ("PUT", base + "/interpolation")]
    assert json.loads(reqs[0].data) == {"value": "2"} and reqs[1].data is None
    assert json.loads(reqs[2].data) == {"frame": 9, "overwrite": True}
    assert json.loads(reqs[3].data) == {"interpolation": "hold"}


def test_run_rejects_unsafe_ids_and_unknown_kinds():
    a, _ = api()
    for op in (Op("upsert", "../x.y", 1, "1"), Op("upsert", "nodot", 1, "1"), Op("explode", "a.b")):
        with pytest.raises(ValueError):
            a.run("demo", op)
    with pytest.raises(ValueError):
        a.run("../p", Op("delete", "a.b", 1))


def test_revision_requires_an_etag():
    good = FakeResponse({"project": {"id": "demo"}})
    good.headers["ETag"] = '"' + "a" * 64 + '"'
    a, _ = api(good, FakeResponse({"project": {"id": "demo"}}))
    assert a.project_revision("demo")[1] == '"' + "a" * 64 + '"'
    with pytest.raises(BackendError):
        a.project_revision("demo")
