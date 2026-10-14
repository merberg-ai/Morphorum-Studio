"""New-project setup (S4.4): the wizard's choices, local sanity checks and the create call.

The backend's ``/api/animation/project-template`` supplies every default. Studio only overlays the
few things the wizard asks about (name, size, frame rate, length, mode, start mode, checkpoint and
the first prompts) and sends the result without ``tracks``, ``id`` or timestamps, so the backend
derives its own timeline from the legacy sections. The wizard never writes camera values: a 3D
camera schedule is left exactly as the template has it, so nothing it creates can place the scene
behind the camera. The backend's schedule validation stays the authoritative verdict.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .client import BackendClient, BackendError
from .projects import MAX_NAME, ProjectDetail, parse_project
from .schema import _object
from .validation import Issue, Validation, ValidationApi

MODES = ("2d", "3d")
START_MODES = ("prompt", "source")
MIN_SIDE, MAX_SIDE = 64, 8192
MAX_FRAMES = 100_000
MAX_PROMPT = 4000
BIG_PIXELS = 2048 * 2048

# Keys the wizard owns; everything else in the template is passed through untouched.
_DROPPED = ("id", "created_at", "updated_at", "tracks")


@dataclass(frozen=True)
class Choices:
    name: str = "Untitled Animation"
    width: int = 1024
    height: int = 1024
    fps: float = 24.0
    frames: int = 120
    mode: str = "2d"
    start_mode: str = "prompt"
    model_id: str = ""
    family: str = ""
    variant: str = ""
    prompt: str = ""
    negative: str = ""

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.fps if self.fps else 0.0


def check_choices(c: Choices) -> tuple[Issue, ...]:
    """Local, advisory checks that can run before the backend is asked anything."""
    issues: list[Issue] = []

    def error(field: str, message: str) -> None:
        issues.append(Issue(field, "error", message))

    def warn(field: str, message: str) -> None:
        issues.append(Issue(field, "warning", message))

    name = c.name.strip()
    if not name:
        error("name", "Give the project a name.")
    elif len(name) > MAX_NAME:
        error("name", f"The name is limited to {MAX_NAME} characters.")
    for side, label in ((c.width, "width"), (c.height, "height")):
        if not MIN_SIDE <= side <= MAX_SIDE:
            error(label, f"The {label} must be between {MIN_SIDE} and {MAX_SIDE} pixels.")
        elif side % 8:
            warn(label, f"The {label} is not a multiple of 8; most models work best on multiples of 8.")
    if not 1 <= c.fps <= 240:
        error("fps", "The frame rate must be between 1 and 240.")
    if not 1 <= c.frames <= MAX_FRAMES:
        error("frames", f"The length must be between 1 and {MAX_FRAMES} frames.")
    if c.mode not in MODES:
        error("mode", "Choose 2D or 3D.")
    if c.start_mode not in START_MODES:
        error("start_mode", "Choose how the first frame starts.")
    if not c.model_id:
        error("model", "Choose a checkpoint; rendering needs one.")
    if len(c.prompt) > MAX_PROMPT or len(c.negative) > MAX_PROMPT:
        error("prompt", f"Prompts are limited to {MAX_PROMPT} characters.")
    if (MIN_SIDE <= c.width <= MAX_SIDE and MIN_SIDE <= c.height <= MAX_SIDE
            and c.width * c.height > BIG_PIXELS):
        warn("size", "This frame size is very large and may run out of GPU memory.")
    if c.start_mode == "source":
        warn("start_mode", "Attach a source image from the Projects page after the project is created.")
    elif not c.prompt.strip():
        warn("prompt", "The first prompt is empty; add one in the Editor before rendering.")
    return tuple(issues)


def has_errors(issues: tuple[Issue, ...]) -> bool:
    return any(i.severity == "error" for i in issues)


def apply_choices(template: Mapping[str, Any], c: Choices) -> dict[str, Any]:
    """A copy of the template with the wizard's choices overlaid and no camera values touched."""
    project = copy.deepcopy(dict(template))
    for key in _DROPPED:
        project.pop(key, None)
    animation = dict(project.get("animation") or {})
    animation.update(width=int(c.width), height=int(c.height), fps=float(c.fps),
                     max_frames=int(c.frames), mode=c.mode, start_mode=c.start_mode)
    project["animation"] = animation
    project["name"] = c.name.strip()
    project["model"] = {"model_id": c.model_id, "family": c.family.lower(), "variant": c.variant.lower()}
    project["prompts"] = {"0": c.prompt.strip()}
    project["negative_prompts"] = {"0": c.negative.strip()}
    return project


class SetupApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def template(self) -> dict[str, Any]:
        data = _object(self._client.get_json("/api/animation/project-template"), "Project template")
        project = data.get("project")
        if not isinstance(project, dict) or not isinstance(project.get("animation"), dict):
            raise BackendError("INVALID_RESPONSE", "Project template is incomplete")
        return project

    def review(self, template: Mapping[str, Any], c: Choices) -> Validation:
        """The backend's own verdict on the schedules the new project would have."""
        return ValidationApi(self._client).check(apply_choices(template, c))

    def create(self, template: Mapping[str, Any], c: Choices) -> ProjectDetail:
        if has_errors(check_choices(c)):
            raise BackendError("INVALID_REQUEST", "Fix the problems listed before creating the project")
        payload, _ = self._client.send_json(
            "POST", "/api/animation/projects", apply_choices(template, c), max_bytes=1024 * 1024)
        return parse_project(payload)
