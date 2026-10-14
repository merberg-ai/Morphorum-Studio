"""Deforum settings import (S4.3): preview and create. The backend does all translation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .client import BackendClient, BackendError
from .projects import valid_project_id
from .schema import _object, _text, _whole
from .validation import Validation, parse_validation

MAX_SOURCE_BYTES = 1_048_576
MAX_MAPPINGS = 500
STATUS_ORDER = ("mapped", "mapped_with_warning", "ignored_path", "unsupported", "unmapped")


@dataclass(frozen=True)
class Mapped:
    source_key: str
    target: str | None
    status: str
    message: str = ""


@dataclass(frozen=True)
class DeforumPreview:
    filename: str
    source_sha256: str
    model_required: bool
    model_name: str | None
    project_name: str
    frames: int | None
    fps: float | None
    size: tuple[int, int] | None
    mode: str | None
    mappings: tuple[Mapped, ...]
    warnings: tuple[str, ...]
    unsupported: tuple[str, ...]
    unmapped: tuple[str, ...]
    validation: Validation
    can_create: bool

    def count(self, status: str) -> int:
        return sum(1 for m in self.mappings if m.status == status)


@dataclass(frozen=True)
class DeforumCreated:
    project_id: str
    name: str
    warnings: tuple[str, ...]


def read_settings_file(path: str | os.PathLike) -> tuple[str, str]:
    """(file name, text) of a Deforum settings file; refuses anything over 1 MiB or not UTF-8."""
    try:
        size = os.path.getsize(path)
        if size <= 0 or size > MAX_SOURCE_BYTES:
            raise ValueError("The settings file must be between 1 byte and 1 MiB")
        with open(path, "rb") as handle:
            data = handle.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"Could not read the file: {exc.strerror or 'error'}") from exc
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The settings file is not UTF-8 text") from exc
    return os.path.basename(str(path))[:120], text


def _strings(value: Any, limit: int) -> tuple[str, ...]:
    return tuple(s for s in (_text(v, 300) for v in (value if isinstance(value, list) else [])[:limit]) if s)


def parse_preview(payload: Any) -> DeforumPreview:
    data = _object(payload, "Deforum preview")
    project = data.get("project")
    validation = data.get("validation")
    if not isinstance(project, Mapping) or not isinstance(validation, Mapping):
        raise BackendError("INVALID_RESPONSE", "Deforum preview is incomplete")
    animation = project.get("animation") if isinstance(project.get("animation"), Mapping) else {}
    maps = []
    for item in (data.get("mappings") if isinstance(data.get("mappings"), list) else [])[:MAX_MAPPINGS]:
        if isinstance(item, Mapping) and isinstance(item.get("source_key"), str):
            target = item.get("target")
            maps.append(Mapped(item["source_key"][:120], target if isinstance(target, str) else None,
                               _text(item.get("status"), 30) or "unmapped", _text(item.get("message"), 300) or ""))
    width, height = _whole(animation.get("width"), 1), _whole(animation.get("height"), 1)
    fps = animation.get("fps")
    model = data.get("selected_model")
    return DeforumPreview(
        filename=_text(data.get("source_filename"), 120) or "", source_sha256=_text(data.get("source_sha256"), 64) or "",
        model_required=data.get("model_required") is True,
        model_name=_text(model.get("name"), 120) if isinstance(model, Mapping) else None,
        project_name=_text(project.get("name"), 120) or "",
        frames=_whole(animation.get("max_frames"), 1),
        fps=float(fps) if isinstance(fps, (int, float)) and not isinstance(fps, bool) else None,
        size=(width, height) if width and height else None, mode=_text(animation.get("mode"), 8),
        mappings=tuple(maps), warnings=_strings(data.get("warnings"), 100),
        unsupported=_strings(data.get("unsupported_keys"), MAX_MAPPINGS),
        unmapped=_strings(data.get("unmapped_keys"), MAX_MAPPINGS),
        validation=parse_validation(validation), can_create=data.get("can_create") is True)


class DeforumApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    @staticmethod
    def _body(text: str, filename: str, model_id: str | None, name: str | None) -> dict:
        if not text or len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("The settings text must be between 1 byte and 1 MiB")
        body: dict[str, Any] = {"content": text, "filename": filename[:120]}
        if model_id:
            body["model_id"] = model_id
        if name and name.strip():
            body["name"] = name.strip()[:120]
        return body

    def preview(self, text: str, filename: str, model_id: str | None, name: str | None) -> DeforumPreview:
        payload, _ = self._client.send_json(
            "POST", "/api/animation/import/deforum/preview", self._body(text, filename, model_id, name),
            max_bytes=4 * 1024 * 1024)
        return parse_preview(payload)

    def create(self, text: str, filename: str, model_id: str, name: str | None) -> DeforumCreated:
        if not model_id:
            raise ValueError("Choose a checkpoint before creating the project")
        payload, _ = self._client.send_json(
            "POST", "/api/animation/import/deforum/create", self._body(text, filename, model_id, name),
            max_bytes=4 * 1024 * 1024)
        data = _object(payload, "Deforum import")
        project = data.get("project")
        if data.get("status") != "created" or not isinstance(project, Mapping) \
                or not valid_project_id(project.get("id")):
            raise BackendError("INVALID_RESPONSE", "Deforum import response is incomplete")
        report = data.get("import") if isinstance(data.get("import"), Mapping) else {}
        return DeforumCreated(project["id"], _text(project.get("name"), 120) or project["id"],
                              _strings(report.get("warnings"), 100))
