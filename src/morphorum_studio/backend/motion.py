"""Motion Lab (S5.1): six-axis camera motion layers composed by the backend.

Studio never computes motion itself. A *draft* is a list of layer objects; the backend validates
and compiles them (``/motion-lab/preview`` without saving, ``/motion-lab/apply`` saving into the
project's camera tracks) and reports the six resolved per-frame curves. Layers Studio has no
editor for yet (recorded takes) are kept exactly as the backend stored them and
sent back unchanged, so editing other layers never loses them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .client import BackendClient, BackendError
from .projects import valid_project_id

AXES = ("translation_x", "translation_y", "translation_z",
        "rotation_x", "rotation_y", "rotation_z")
AXIS_LABELS = {
    "translation_x": "Move X", "translation_y": "Move Y", "translation_z": "Move Z (forward)",
    "rotation_x": "Tilt (X)", "rotation_y": "Pan (Y)", "rotation_z": "Roll (Z)",
}
PRESETS = ("still", "gentle-drift", "wave", "spiral", "figure-eight", "rocking", "push-in", "pull-out")
INTERPOLATIONS = ("linear", "hold", "smoothstep", "smootherstep", "cubic")
EDITABLE = ("preset", "keyframes", "audio")  # layer types Studio can edit; others are preserved as-is
MAX_LAYERS = 24
MAX_KEYS = 128
_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
CONFLICT_HINT = "Camera schedules changed since Motion Lab"


def preset_label(name: str) -> str:
    return name.replace("-", " ").capitalize()


@dataclass(frozen=True)
class MotionState:
    """What the saved project says about Motion Lab."""
    mode: str  # "2d" | "3d"
    frames: int
    fps: float
    layers: tuple[dict[str, Any], ...] = ()
    limits: dict[str, float] = field(default_factory=dict)
    applied: bool = False  # a previous Apply left a base-track snapshot

    @property
    def usable(self) -> bool:
        return self.mode == "3d" and self.frames > 0


@dataclass(frozen=True)
class MotionPreview:
    layers: tuple[dict[str, Any], ...]  # the backend's normalised layers
    series: dict[str, tuple[float, ...]]
    limited: dict[str, int]
    camera_changed: bool
    rebased: bool
    frames: int
    fps: float


def state_of(project: Any) -> MotionState:
    """Read Motion Lab state out of a raw project object (never raises on odd data)."""
    data = project if isinstance(project, Mapping) else {}
    animation = data.get("animation") if isinstance(data.get("animation"), Mapping) else {}
    lab = data.get("motion_lab") if isinstance(data.get("motion_lab"), Mapping) else {}
    layers = lab.get("layers") if isinstance(lab.get("layers"), list) else []
    limits = lab.get("limits") if isinstance(lab.get("limits"), Mapping) else {}
    frames = animation.get("max_frames")
    fps = animation.get("fps")
    return MotionState(
        mode=str(animation.get("mode") or "2d").lower(),
        frames=frames if type(frames) is int and frames > 0 else 0,
        fps=float(fps) if isinstance(fps, (int, float)) and not isinstance(fps, bool) and fps > 0 else 0.0,
        layers=tuple(deepcopy(x) for x in layers if isinstance(x, dict)),
        limits={k: float(v) for k, v in limits.items()
                if k in AXES and isinstance(v, (int, float)) and not isinstance(v, bool)},
        applied=lab.get("last_applied_tracks") is not None,
    )


def unique_id(layers, prefix: str = "layer") -> str:
    taken = {str(item.get("id")) for item in layers}
    number = len(taken) + 1
    while f"{prefix}-{number}" in taken:
        number += 1
    return f"{prefix}-{number}"


def new_preset_layer(layers, frames: int, preset: str = "gentle-drift") -> dict[str, Any]:
    if preset not in PRESETS:
        raise ValueError("unknown preset")
    return {"id": unique_id(layers), "type": "preset", "preset": preset, "enabled": True,
            "blend": "add", "start_frame": 0, "end_frame": frames, "strength": 0.5,
            "cycle_seconds": 8.0, "fade_seconds": 0.5}


def new_curve_layer(layers, frames: int, axis: str = "translation_x") -> dict[str, Any]:
    if axis not in AXES:
        raise ValueError("unknown axis")
    value = 0.4 if axis.startswith("rotation") else 0.02
    return {"id": unique_id(layers), "type": "keyframes", "axis": axis, "enabled": True,
            "blend": "add", "interpolation": "smoothstep", "start_frame": 0, "end_frame": frames,
            "keys": [{"frame": max(1, frames // 2), "value": value}]}


def describe_layer(layer: Mapping[str, Any]) -> str:
    kind = layer.get("type")
    if kind == "preset":
        return preset_label(str(layer.get("preset", "preset")))
    if kind == "keyframes":
        return f"Curve · {AXIS_LABELS.get(str(layer.get('axis')), layer.get('axis'))}"
    if kind == "audio":
        return str(layer.get("name") or "Audio pulses")
    if kind == "recording":
        return str(layer.get("name") or "Recorded take")
    return str(kind or "Layer")


def editable(layer: Mapping[str, Any]) -> bool:
    return layer.get("type") in EDITABLE


def parse_preview(payload: Any) -> MotionPreview:
    data = payload if isinstance(payload, Mapping) else {}
    diag = data.get("diagnostics") if isinstance(data.get("diagnostics"), Mapping) else {}
    raw_series = diag.get("series") if isinstance(diag.get("series"), Mapping) else {}
    series: dict[str, tuple[float, ...]] = {}
    for axis in AXES:
        values = raw_series.get(axis)
        if isinstance(values, list) and len(values) <= 10_000:
            series[axis] = tuple(float(v) for v in values
                                 if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not series:
        raise BackendError("INVALID_RESPONSE", "Motion preview has no curves")
    limited = diag.get("limited") if isinstance(diag.get("limited"), Mapping) else {}
    layers = data.get("layers") if isinstance(data.get("layers"), list) else []
    return MotionPreview(
        layers=tuple(x for x in layers if isinstance(x, dict)), series=series,
        limited={k: int(v) for k, v in limited.items() if k in AXES and type(v) is int and v > 0},
        camera_changed=diag.get("camera_changed") is True, rebased=diag.get("rebased") is True,
        frames=int(diag.get("frames") or 0) if type(diag.get("frames")) is int else 0,
        fps=float(diag.get("fps") or 0.0) if isinstance(diag.get("fps"), (int, float)) else 0.0)


class MotionApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    @staticmethod
    def _path(project_id: str, suffix: str) -> str:
        if not valid_project_id(project_id):
            raise ValueError("invalid project id")
        return f"/api/animation/projects/{project_id}/motion-lab/{suffix}"

    def presets(self) -> tuple[str, ...]:
        payload = self._client.get_json("/api/animation/motion-lab/presets")
        names = payload.get("presets") if isinstance(payload, Mapping) else None
        found = tuple(n for n in names if isinstance(n, str)) if isinstance(names, list) else ()
        return found or PRESETS

    def preview(self, project_id: str, layers: list[dict[str, Any]]) -> MotionPreview:
        payload, _ = self._client.send_json("POST", self._path(project_id, "preview"),
                                            {"layers": layers})
        return parse_preview(payload)

    def apply(self, project_id: str, layers: list[dict[str, Any]], rebase: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"layers": layers}
        if rebase:
            body["rebase_current"] = True
        payload, _ = self._client.send_json("POST", self._path(project_id, "apply"), body)
        return payload if isinstance(payload, dict) else {}


def is_conflict(code: str, message: str) -> bool:
    """The backend refused because hand-edited camera tracks would be overwritten."""
    return code == "CONFLICT" or CONFLICT_HINT in message
