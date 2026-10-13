"""Timeline parsing, calls and resolved values (no Qt, no network)."""
import json

import pytest
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.timeline import (
    TimelineApi, parse_resolved, parse_series, parse_timeline,
)

DESCRIPTORS = {
    "schema_version": 1,
    "groups": [{"id": "prompts", "label": "Prompts", "reserved": False},
               {"id": "camera_2d", "label": "2D Camera", "reserved": False},
               {"id": "loras", "label": "LoRAs", "reserved": True}],
    "tracks": [
        {"id": "prompts.positive", "group": "prompts", "name": "positive", "label": "Positive Prompt",
         "kind": "prompt", "value_type": "text", "unit": None, "interpolation_modes": ["blend", "hold"]},
        {"id": "camera_2d.zoom", "group": "camera_2d", "name": "zoom", "label": "2D Zoom",
         "kind": "numeric", "value_type": "float", "unit": None, "interpolation_modes": ["linear", "hold"],
         "legacy_field": "motion.zoom"},
        {"id": "camera_2d.angle", "group": "camera_2d", "name": "angle", "label": "2D Angle",
         "kind": "numeric", "value_type": "float", "unit": "deg", "interpolation_modes": ["linear", "hold"],
         "legacy_field": "motion.angle"},
    ],
}
SNAPSHOT = {
    "schema_version": 1, "project_id": "demo", "max_frames": 48, "fps": 24.0, "duration_seconds": 2.0,
    "descriptors": DESCRIPTORS,
    "tracks": {
        "prompts": {"positive": {"kind": "prompt", "interpolation": "blend",
                                 "keyframes": [{"frame": 0, "value": "a cat"}, {"frame": 24, "value": "a dog"}]}},
        "camera_2d": {"zoom": {"kind": "numeric", "interpolation": "linear", "schedule": "0:(1.0)",
                               "keyframes": [{"frame": 0, "frame_expression": "0", "value": "1.0"},
                                             {"frame": 24, "frame_expression": "24", "value": "1+0.5*sin(t)"}]}},
    },
}


def test_parse_timeline_builds_lanes_and_keeps_expressions():
    t = parse_timeline(SNAPSHOT)
    assert t.max_frames == 48 and t.fps == 24.0 and t.duration == 2.0
    assert [g.id for g in t.groups] == ["prompts", "camera_2d", "loras"]
    zoom = t.track("camera_2d.zoom")
    assert zoom.field == "motion.zoom" and zoom.interpolation == "linear"
    assert [(k.frame, k.value, k.number) for k in zoom.keyframes] == [(0, "1.0", 1.0), (24, "1+0.5*sin(t)", None)]
    assert t.track("camera_2d.angle").keyframes == ()  # nothing stored: an empty lane, not an invention
    assert t.track("prompts.positive").keyframes[1].value == "a dog"
    assert [x.id for x in t.in_group("camera_2d")] == ["camera_2d.zoom", "camera_2d.angle"]


def test_parse_timeline_rejects_incomplete_and_skips_unsafe_tracks():
    for bad in ({}, [], {**SNAPSHOT, "project_id": "../x"}, {**SNAPSHOT, "max_frames": 0},
                {**SNAPSHOT, "fps": 0}, {**SNAPSHOT, "tracks": []}, {**SNAPSHOT, "descriptors": []}):
        with pytest.raises(BackendError):
            parse_timeline(bad)
    descriptors = {**DESCRIPTORS, "tracks": DESCRIPTORS["tracks"] + [
        {"group": "../x", "name": "y", "kind": "numeric"}, {"group": "a", "name": "b", "kind": "weird"}]}
    assert len(parse_timeline({**SNAPSHOT, "descriptors": descriptors}).tracks) == 3


def test_unlisted_group_still_gets_a_lane():
    descriptors = {**DESCRIPTORS, "groups": []}
    assert {g.id for g in parse_timeline({**SNAPSHOT, "descriptors": descriptors}).groups} == {
        "prompts", "camera_2d"}


def test_bad_keyframes_are_skipped():
    snap = json.loads(json.dumps(SNAPSHOT))
    snap["tracks"]["camera_2d"]["zoom"]["keyframes"] = [
        {"frame": -1, "value": "1"}, {"frame": "x", "value": "1"}, {"frame": 3, "value": None},
        {"frame": 5, "value": 2}, "junk"]
    assert [(k.frame, k.value) for k in parse_timeline(snap).track("camera_2d.zoom").keyframes] == [(5, "2")]


def test_parse_series():
    s = parse_series({"field": "motion.zoom", "interpolation": "linear",
                      "samples": [{"frame": 0, "value": 1.0}, {"frame": 47, "value": 1.5}, {"frame": "x"}],
                      "issues": [{"message": "careful"}]})
    assert s.samples == ((0, 1.0), (47, 1.5)) and s.issues == ("careful",)
    with pytest.raises(BackendError):
        parse_series({"field": "motion.zoom", "samples": []})


def resolved_payload(frame=12):
    return {"frames": [{
        "frame": frame, "time_seconds": 0.5, "motion": {"zoom": 1.25, "angle": 3.0, "border_mode": "replicate"},
        "camera_3d": {}, "generation": {"seed": 42, "strength": 0.6}, "cadence": {},
        "prompts": {"positive": {"from_text": "a cat", "to_text": "a dog"},
                    "negative": {"from_text": "blur", "to_text": "blur"}}}]}


def test_parse_resolved_maps_groups_and_prompts():
    t = parse_timeline(SNAPSHOT)
    r = parse_resolved(resolved_payload(), t)
    assert r.frame == 12 and r.seconds == 0.5 and r.seed == 42
    assert r.values == {"camera_2d.zoom": 1.25, "camera_2d.angle": 3.0}
    assert r.positive == "a cat  →  a dog" and r.negative == "blur"
    for bad in ({}, {"frames": []}, {"frames": ["x"]}, {"frames": [{"frame": "x"}]}):
        with pytest.raises(BackendError):
            parse_resolved(bad, t)


def test_api_calls_send_the_complete_project():
    project = {"id": "demo", "animation": {"fps": 24}}
    opener = FakeOpener([FakeResponse(SNAPSHOT), FakeResponse({"field": "motion.zoom", "samples": [
        {"frame": 0, "value": 1}, {"frame": 1, "value": 2}]}), FakeResponse(resolved_payload())])
    api = TimelineApi(BackendClient("http://localhost", "t", opener=opener))
    t = api.timeline("demo")
    api.series(project, "motion.zoom", 9999)
    api.resolve(project, 12, t)
    urls = [r.full_url for r, _ in (x for x in opener.requests)]
    assert urls[0].endswith("/api/animation/projects/demo/timeline")
    series_body = json.loads(opener.requests[1][0].data)
    assert series_body == {"project": project, "field": "motion.zoom", "sample_count": 500}
    assert json.loads(opener.requests[2][0].data) == {"project": project, "start_frame": 12,
                                                      "end_frame": 12, "step": 1}
    with pytest.raises(ValueError):
        api.timeline("../x")
