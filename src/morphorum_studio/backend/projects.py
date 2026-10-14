"""Animation projects (S2.2): typed views plus the read and write calls the Projects page uses.

Writes always carry the project's strong ETag as ``If-Match``. A stale ETag is reported as
``PRECONDITION_FAILED`` and the caller must reload; Studio never overwrites silently.
The backend merges a partial PUT body into the stored project, so saving only the fields the
page edits (name, notes) cannot disturb anything else. A new project is created from just a
name: the backend supplies its own validated defaults rather than Studio copying any.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .client import BackendClient, BackendError
from .schema import _CONTROL, _number, _object, _text, _whole

PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}")
MAX_NAME = 120
MAX_NOTES = 20_000


def valid_project_id(value: Any) -> bool:
    return isinstance(value, str) and PROJECT_ID.fullmatch(value) is not None


@dataclass(frozen=True)
class ProjectSummary:
    id: str
    name: str
    updated_at: str | None = None
    created_at: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    max_frames: int | None = None
    mode: str | None = None
    model_family: str | None = None
    has_source_image: bool = False

    @property
    def duration_seconds(self) -> float | None:
        if self.max_frames and self.fps:
            return self.max_frames / self.fps
        return None


@dataclass(frozen=True)
class ProjectDetail:
    id: str
    name: str
    notes: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    max_frames: int | None = None
    mode: str | None = None
    start_mode: str | None = None
    source_image_name: str | None = None
    model_id: str | None = None
    model_family: str | None = None
    model_variant: str | None = None
    prompt_keyframes: int = 0
    first_prompt: str | None = None
    motion_layers: int = 0
    audio_layers: int = 0
    hybrid_enabled: bool = False

    @property
    def duration_seconds(self) -> float | None:
        if self.max_frames and self.fps:
            return self.max_frames / self.fps
        return None


@dataclass(frozen=True)
class RenderSummary:
    id: str
    status: str | None = None
    created_at: str | None = None
    latest_frame: int | None = None


# ----------------------------------------------------------------------------- parsing

def parse_project_list(payload: Any) -> tuple[ProjectSummary, ...]:
    data = _object(payload, "Projects")
    items = data.get("projects")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Projects response lacks a projects list")
    result = []
    for item in items[:2000]:
        if not isinstance(item, Mapping) or not valid_project_id(item.get("id")):
            continue
        name = _text(item.get("name"), MAX_NAME)
        if name is None:
            continue
        result.append(ProjectSummary(
            id=item["id"], name=name,
            updated_at=_text(item.get("updated_at"), 40),
            created_at=_text(item.get("created_at"), 40),
            width=_whole(item.get("width"), 1), height=_whole(item.get("height"), 1),
            fps=_number(item.get("fps"), 0.001, 1000),
            max_frames=_whole(item.get("max_frames"), 1),
            mode=_text(item.get("mode"), 10),
            model_family=_text(item.get("model_family"), 40),
            has_source_image=item.get("has_source_image") is True,
        ))
    return tuple(result)


def parse_project(payload: Any) -> ProjectDetail:
    data = _object(payload, "Project")
    project = data.get("project")
    if not isinstance(project, Mapping) or not valid_project_id(project.get("id")):
        raise BackendError("INVALID_RESPONSE", "Project response is incomplete")
    name = _text(project.get("name"), MAX_NAME)
    if name is None:
        raise BackendError("INVALID_RESPONSE", "Project has no name")
    animation = project.get("animation") if isinstance(project.get("animation"), Mapping) else {}
    model = project.get("model") if isinstance(project.get("model"), Mapping) else {}
    prompts = project.get("prompts") if isinstance(project.get("prompts"), Mapping) else {}
    motion_lab = project.get("motion_lab") if isinstance(project.get("motion_lab"), Mapping) else {}
    layers = motion_lab.get("layers")
    hybrid = project.get("hybrid") if isinstance(project.get("hybrid"), Mapping) else {}
    notes = project.get("notes")
    first = None
    if prompts:
        key = min(prompts, key=_numeric_key)
        first = _text(prompts.get(key), 300)
    return ProjectDetail(
        id=project["id"], name=name,
        notes=_CONTROL.sub(" ", notes)[:MAX_NOTES] if isinstance(notes, str) else "",
        created_at=_text(project.get("created_at"), 40),
        updated_at=_text(project.get("updated_at"), 40),
        width=_whole(animation.get("width"), 1), height=_whole(animation.get("height"), 1),
        fps=_number(animation.get("fps"), 0.001, 1000),
        max_frames=_whole(animation.get("max_frames"), 1),
        mode=_text(animation.get("mode"), 10),
        start_mode=_text(animation.get("start_mode"), 10),
        source_image_name=_text(animation.get("source_image_name"), 200),
        model_id=_text(model.get("model_id"), 200),
        model_family=_text(model.get("family"), 40),
        model_variant=_text(model.get("variant"), 40),
        prompt_keyframes=len(prompts),
        first_prompt=first,
        motion_layers=len(layers) if isinstance(layers, list) else 0,
        audio_layers=sum(1 for x in layers if isinstance(x, Mapping) and x.get("type") == "audio")
        if isinstance(layers, list) else 0,
        hybrid_enabled=hybrid.get("enabled") is True,
    )


def _numeric_key(key: Any) -> float:
    try:
        return float(key)
    except (TypeError, ValueError):
        return float("inf")


def parse_renders(payload: Any) -> tuple[RenderSummary, ...]:
    data = _object(payload, "Renders")
    items = data.get("renders")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Renders response lacks a renders list")
    result = []
    for item in items[:200]:
        if not isinstance(item, Mapping):
            continue
        render_id = _text(item.get("id"), 80)
        if render_id is None:
            continue
        latest = item.get("latest_completed_frame")
        result.append(RenderSummary(
            id=render_id, status=_text(item.get("status"), 30),
            created_at=_text(item.get("created_at"), 40),
            latest_frame=_whole(latest) if latest is not None else None,
        ))
    return tuple(result)


# ----------------------------------------------------------------------------- calls

def clean_name(value: str) -> str:
    """Trim and validate a user-entered project name."""
    name = _CONTROL.sub(" ", value or "").strip()
    if not name:
        raise ValueError("Enter a project name")
    if len(name) > MAX_NAME:
        raise ValueError(f"Project names are limited to {MAX_NAME} characters")
    return name


class ProjectsApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    @staticmethod
    def _path(project_id: str, suffix: str = "") -> str:
        if not valid_project_id(project_id):
            raise ValueError("invalid project id")
        return f"/api/animation/projects/{project_id}{suffix}"

    def list_projects(self) -> tuple[ProjectSummary, ...]:
        return parse_project_list(self._client.get_json("/api/animation/projects"))

    def open(self, project_id: str) -> tuple[ProjectDetail, str]:
        """The project plus the strong ETag later saves must present."""
        payload, etag = self._client.get_json_etag(self._path(project_id))
        if etag is None:
            raise BackendError("INVALID_RESPONSE", "Backend did not provide a project revision")
        return parse_project(payload), etag

    def raw(self, project_id: str) -> dict[str, Any]:
        """The complete saved project exactly as the backend stores it (needed to start a render)."""
        payload, _ = self._client.get_json_etag(self._path(project_id))
        project = _object(payload, "Project").get("project")
        if not isinstance(project, dict) or project.get("id") != project_id:
            raise BackendError("INVALID_RESPONSE", "Project response is incomplete")
        return project

    def renders(self, project_id: str) -> tuple[RenderSummary, ...]:
        return parse_renders(self._client.get_json(self._path(project_id, "/renders")))

    def create(self, name: str) -> ProjectDetail:
        payload, _ = self._client.send_json("POST", "/api/animation/projects", {"name": clean_name(name)})
        return parse_project(payload)

    def save(self, project_id: str, etag: str, name: str, notes: str) -> tuple[ProjectDetail, str]:
        """Conditional save of name and notes only. 412 means the project changed: reload."""
        if len(notes) > MAX_NOTES:
            raise ValueError(f"Notes are limited to {MAX_NOTES} characters")
        payload, new_etag = self._client.send_json(
            "PUT", self._path(project_id), {"name": clean_name(name), "notes": notes}, if_match=etag)
        if new_etag is None:
            raise BackendError("INVALID_RESPONSE", "Backend did not provide the new project revision")
        return parse_project(payload), new_etag

    def set_start_mode(self, project_id: str, mode: str) -> None:
        """Choose whether frame 0 starts from the prompt or the attached source image (img2img).

        The current ETag is read first and presented, so a project changed elsewhere is refused
        (412) instead of overwritten. The backend merges the partial ``animation`` body.
        """
        if mode not in ("prompt", "source"):
            raise ValueError("start mode must be 'prompt' or 'source'")
        _, etag = self._client.get_json_etag(self._path(project_id))
        if etag is None:
            raise BackendError("INVALID_RESPONSE", "Backend did not provide a project revision")
        self._client.send_json("PUT", self._path(project_id), {"animation": {"start_mode": mode}},
                               if_match=etag)

    def trash(self, project_id: str) -> None:
        """Moves the project to the backend's Trash (the backend refuses while it is busy: 409)."""
        self._client.send_json("DELETE", self._path(project_id))
