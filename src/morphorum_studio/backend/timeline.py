"""Animation timeline (S4.1): tracks, keyframes, resolved values and curve samples. Read-only.

The backend owns schedule interpretation (expressions such as ``sin(t)``, interpolation, seeds),
so Studio never evaluates anything itself: keyframe values stay text exactly as stored, and the
numbers shown for a frame or drawn as a curve come from the backend's own resolver.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .client import BackendClient, BackendError
from .projects import valid_project_id
from .schema import _number, _object, _text, _whole

MAX_TRACKS = 200
MAX_KEYFRAMES = 5000
MAX_FRAMES = 1_000_000
_ID = re.compile(r"[a-z0-9_]{1,40}")


@dataclass(frozen=True)
class Keyframe:
    frame: int
    value: str
    expression: str = ""  # the frame expression when it is not a plain number

    @property
    def number(self) -> float | None:
        """The value as a number, or None for an expression such as ``sin(t)``."""
        try:
            number = float(self.value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None


@dataclass(frozen=True)
class Track:
    id: str  # "group.name"
    group: str
    name: str
    label: str
    kind: str  # numeric | prompt
    unit: str | None
    modes: tuple[str, ...]
    interpolation: str
    keyframes: tuple[Keyframe, ...]
    field: str | None = None  # the backend's schedule field, e.g. "motion.zoom"
    value_type: str = "float"


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    reserved: bool = False


@dataclass(frozen=True)
class Timeline:
    project_id: str
    max_frames: int
    fps: float
    groups: tuple[Group, ...]
    tracks: tuple[Track, ...] = field(default_factory=tuple)

    @property
    def duration(self) -> float:
        return self.max_frames / self.fps if self.fps > 0 else 0.0

    def track(self, track_id: str) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)

    def in_group(self, group_id: str) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.group == group_id)


@dataclass(frozen=True)
class Series:
    field: str
    interpolation: str
    samples: tuple[tuple[int, float], ...]
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resolved:
    frame: int
    seconds: float
    values: Mapping[str, float]  # track id -> numeric value at this frame
    positive: str = ""
    negative: str = ""
    seed: int | None = None


def _keyframes(items: Any, prompt: bool) -> tuple[Keyframe, ...]:
    result = []
    for item in (items if isinstance(items, list) else [])[:MAX_KEYFRAMES]:
        if not isinstance(item, dict):
            continue
        frame = _whole(item.get("frame"), 0)
        value = item.get("value")
        if frame is None or frame > MAX_FRAMES:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            value = "" if prompt else None
        if value is None:
            continue
        expression = item.get("frame_expression")
        result.append(Keyframe(frame, str(value)[:4000],
                               expression if isinstance(expression, str) and expression != str(frame)
                               else ""))
    return tuple(sorted(result, key=lambda k: k.frame))


def parse_timeline(payload: Any) -> Timeline:
    data = _object(payload, "Timeline")
    project_id = data.get("project_id")
    max_frames, fps = _whole(data.get("max_frames"), 1), _number(data.get("fps"), 0.001, 1000)
    descriptors = data.get("descriptors")
    bundle = data.get("tracks")
    if (not valid_project_id(project_id) or max_frames is None or max_frames > MAX_FRAMES
            or fps is None or not isinstance(descriptors, dict) or not isinstance(bundle, dict)):
        raise BackendError("INVALID_RESPONSE", "Timeline response is incomplete")
    groups = []
    for item in (descriptors.get("groups") if isinstance(descriptors.get("groups"), list) else []):
        if isinstance(item, dict) and isinstance(item.get("id"), str) and _ID.fullmatch(item["id"]):
            groups.append(Group(item["id"], _text(item.get("label"), 60) or item["id"],
                                item.get("reserved") is True))
    tracks = []
    for item in (descriptors.get("tracks") if isinstance(descriptors.get("tracks"), list) else [])[:MAX_TRACKS]:
        if not isinstance(item, dict):
            continue
        group, name = item.get("group"), item.get("name")
        kind = item.get("kind")
        if not (isinstance(group, str) and isinstance(name, str) and _ID.fullmatch(group)
                and _ID.fullmatch(name) and kind in ("numeric", "prompt")):
            continue
        stored = bundle.get(group)
        stored = stored.get(name) if isinstance(stored, dict) else None
        stored = stored if isinstance(stored, dict) else {}
        modes = tuple(m for m in (item.get("interpolation_modes") or []) if isinstance(m, str))[:6]
        interpolation = stored.get("interpolation")
        legacy = item.get("legacy_field")
        tracks.append(Track(
            id=f"{group}.{name}", group=group, name=name,
            label=_text(item.get("label"), 60) or f"{group}.{name}", kind=kind,
            unit=_text(item.get("unit"), 12),
            modes=modes, interpolation=interpolation if isinstance(interpolation, str) else (modes[0] if modes else ""),
            keyframes=_keyframes(stored.get("keyframes"), kind == "prompt"),
            field=legacy if isinstance(legacy, str) and re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", legacy) else None,
            value_type=_text(item.get("value_type"), 12) or "float"))
    known = {g.id for g in groups}
    for track in tracks:  # a track whose group the backend forgot to list still gets a lane
        if track.group not in known:
            groups.append(Group(track.group, track.group))
            known.add(track.group)
    return Timeline(project_id, max_frames, fps, tuple(groups), tuple(tracks))


def parse_series(payload: Any) -> Series:
    data = _object(payload, "Schedule series")
    field_name = data.get("field")
    samples = []
    for item in (data.get("samples") if isinstance(data.get("samples"), list) else [])[:600]:
        if isinstance(item, dict):
            frame, value = _whole(item.get("frame"), 0), _number(item.get("value"))
            if frame is not None and value is not None:
                samples.append((frame, value))
    if not isinstance(field_name, str) or not samples:
        raise BackendError("INVALID_RESPONSE", "Schedule series is incomplete")
    issues = tuple(
        _text(i.get("message"), 200) or "" for i in (data.get("issues") if isinstance(data.get("issues"), list) else [])
        if isinstance(i, dict))[:10]
    return Series(field_name, _text(data.get("interpolation"), 12) or "", tuple(samples), issues)


_GROUP_KEY = {"camera_2d": "motion", "camera_3d": "camera_3d", "generation": "generation",
              "cadence": "cadence"}


def parse_resolved(payload: Any, timeline: Timeline) -> Resolved:
    """One frame out of ``/resolve-timeline``: numeric values keyed by track id, plus prompts."""
    data = _object(payload, "Resolved timeline")
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames or not isinstance(frames[0], dict):
        raise BackendError("INVALID_RESPONSE", "Resolved timeline has no frame")
    frame = frames[0]
    number = _whole(frame.get("frame"), 0)
    if number is None:
        raise BackendError("INVALID_RESPONSE", "Resolved frame has no number")
    values: dict[str, float] = {}
    for track in timeline.tracks:
        section = frame.get(_GROUP_KEY.get(track.group, ""))
        value = section.get(track.name) if isinstance(section, dict) else None
        number_value = _number(value) if not isinstance(value, bool) else None
        if number_value is not None:
            values[track.id] = number_value
    prompts = frame.get("prompts") if isinstance(frame.get("prompts"), dict) else {}

    def prompt(name: str) -> str:
        state = prompts.get(name)
        if not isinstance(state, dict):
            return ""
        a, b = state.get("from_text"), state.get("to_text")
        a, b = (a if isinstance(a, str) else ""), (b if isinstance(b, str) else "")
        return (a if a == b else f"{a}  →  {b}")[:2000]

    generation = frame.get("generation") if isinstance(frame.get("generation"), dict) else {}
    seed = generation.get("seed")
    return Resolved(number, _number(frame.get("time_seconds"), 0) or 0.0, values,
                    prompt("positive"), prompt("negative"),
                    seed if type(seed) is int else None)


class TimelineApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def timeline(self, project_id: str) -> Timeline:
        if not valid_project_id(project_id):
            raise ValueError("invalid project id")
        return parse_timeline(self._client.get_json(f"/api/animation/projects/{project_id}/timeline"))

    def series(self, project: dict, schedule_field: str, samples: int = 120) -> Series:
        payload, _ = self._client.send_json(
            "POST", "/api/animation/schedule-series",
            {"project": project, "field": schedule_field, "sample_count": max(2, min(samples, 500))},
            max_bytes=2 * 1024 * 1024)
        return parse_series(payload)

    def resolve(self, project: dict, frame: int, timeline: Timeline) -> Resolved:
        payload, _ = self._client.send_json(
            "POST", "/api/animation/resolve-timeline",
            {"project": project, "start_frame": frame, "end_frame": frame, "step": 1},
            max_bytes=2 * 1024 * 1024)
        return parse_resolved(payload, timeline)


# ---- S4.2: keyframe editing ---------------------------------------------------------------
#
# The backend saves each keyframe call immediately and has no revision check of its own, so Studio
# (1) compares the project's ETag with the one it loaded before every edit, (2) plans each edit
# together with its exact inverse from the timeline it is showing, and (3) reloads from the
# backend afterwards instead of trusting its own prediction.

MAX_VALUE = 4000


@dataclass(frozen=True)
class Op:
    kind: str  # upsert | delete | move | interp
    track: str  # "group.name"
    frame: int = 0
    value: str = ""  # upsert: the value; interp: the mode
    target: int = 0  # move: destination frame
    overwrite: bool = False  # move


@dataclass(frozen=True)
class Edit:
    label: str
    forward: tuple[Op, ...]
    inverse: tuple[Op, ...]


class EditError(ValueError):
    """The edit is refused before anything is sent (no network involved)."""


def keyframe_at(track: Track, frame: int) -> Keyframe | None:
    return next((k for k in track.keyframes if k.frame == frame), None)


def _editable(track: Track, frame: int, max_frames: int) -> Keyframe | None:
    if not 0 <= frame < max_frames:
        raise EditError(f"Frame {frame} is outside 0..{max_frames - 1}.")
    existing = keyframe_at(track, frame)
    if existing is not None and existing.expression:
        raise EditError("This keyframe uses a frame expression; edit it in the backend Web UI.")
    return existing


def plan_set(track: Track, frame: int, value: str, max_frames: int) -> Edit:
    value = value.strip() if track.kind == "numeric" else value
    if track.kind == "numeric" and not value:
        raise EditError("A numeric keyframe needs a value or expression.")
    if len(value) > MAX_VALUE:
        raise EditError(f"Values are limited to {MAX_VALUE} characters.")
    previous = _editable(track, frame, max_frames)
    if previous is not None and previous.value == value:
        raise EditError("That keyframe already has this value.")
    forward = (Op("upsert", track.id, frame, value),)
    inverse = (Op("upsert", track.id, frame, previous.value),) if previous else (Op("delete", track.id, frame),)
    verb = "Change" if previous else "Add"
    return Edit(f"{verb} {track.label} keyframe at {frame}", forward, inverse)


def plan_delete(track: Track, frame: int, max_frames: int) -> Edit:
    previous = _editable(track, frame, max_frames)
    if previous is None:
        raise EditError("There is no keyframe at that frame.")
    if frame == 0 and track.kind == "prompt":
        raise EditError("A prompt track needs a keyframe at frame 0.")
    return Edit(f"Delete {track.label} keyframe at {frame}", (Op("delete", track.id, frame),),
                (Op("upsert", track.id, frame, previous.value),))


def plan_move(track: Track, source: int, target: int, max_frames: int, overwrite: bool = False) -> Edit:
    moving = _editable(track, source, max_frames)
    if moving is None:
        raise EditError("There is no keyframe at that frame.")
    if source == target:
        raise EditError("The keyframe is already there.")
    replaced = _editable(track, target, max_frames)
    if source == 0 and track.kind == "prompt":
        raise EditError("The frame-0 prompt keyframe cannot be moved.")
    if replaced is not None and not overwrite:
        raise EditError("There is already a keyframe at the target frame.")
    inverse: list[Op] = [Op("move", track.id, target, target=source)]
    if replaced is not None:
        inverse.append(Op("upsert", track.id, target, replaced.value))
    return Edit(f"Move {track.label} keyframe {source} to {target}",
                (Op("move", track.id, source, target=target, overwrite=replaced is not None),),
                tuple(inverse))


def plan_interpolation(track: Track, mode: str) -> Edit:
    if mode not in track.modes:
        raise EditError(f"{mode} is not available for this track.")
    if mode == track.interpolation:
        raise EditError("That interpolation is already set.")
    return Edit(f"Set {track.label} interpolation to {mode}", (Op("interp", track.id, value=mode),),
                (Op("interp", track.id, value=track.interpolation),))


def etag_of(payload_etag: str | None) -> str:
    if not payload_etag:
        raise BackendError("INVALID_RESPONSE", "The backend did not provide a project revision")
    return payload_etag


class EditApi(TimelineApi):
    """Keyframe calls plus the revision check that guards them."""

    def project_revision(self, project_id: str) -> tuple[dict, str]:
        if not valid_project_id(project_id):
            raise ValueError("invalid project id")
        payload, etag = self._client.get_json_etag(f"/api/animation/projects/{project_id}")
        project = _object(payload, "Project").get("project")
        if not isinstance(project, dict) or project.get("id") != project_id:
            raise BackendError("INVALID_RESPONSE", "Project response is incomplete")
        return project, etag_of(etag)

    def _track_path(self, project_id: str, track_id: str) -> str:
        group, _, name = track_id.partition(".")
        if not (valid_project_id(project_id) and _ID.fullmatch(group) and _ID.fullmatch(name)):
            raise ValueError("invalid track")
        return f"/api/animation/projects/{project_id}/timeline/tracks/{group}/{name}"

    def run(self, project_id: str, op: Op) -> None:
        base = self._track_path(project_id, op.track)
        if op.kind == "upsert":
            self._client.send_json("PUT", f"{base}/keyframes/{int(op.frame)}", {"value": op.value})
        elif op.kind == "delete":
            self._client.send_json("DELETE", f"{base}/keyframes/{int(op.frame)}")
        elif op.kind == "move":
            self._client.send_json("POST", f"{base}/keyframes/{int(op.frame)}/move",
                                   {"frame": int(op.target), "overwrite": bool(op.overwrite)})
        elif op.kind == "interp":
            self._client.send_json("PUT", f"{base}/interpolation", {"interpolation": op.value})
        else:
            raise ValueError("unknown edit operation")
