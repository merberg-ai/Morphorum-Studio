"""Schedule validation (S4.3): the backend's own verdict on a project's tracks, unmodified."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import BackendClient, BackendError
from .schema import _object, _text

MAX_ISSUES = 200
SEVERITIES = ("error", "warning")


@dataclass(frozen=True)
class Issue:
    field: str
    severity: str  # error | warning
    message: str

    @property
    def track_id(self) -> str | None:
        return field_track_id(self.field)


@dataclass(frozen=True)
class Validation:
    valid: bool
    issues: tuple[Issue, ...]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")


def field_track_id(field: str) -> str | None:
    """Timeline track id for a backend schedule field (``motion.zoom`` is the 2D camera zoom)."""
    if field.startswith("tracks."):
        return field[len("tracks."):] or None
    group, _, name = field.partition(".")
    group = {"motion": "camera_2d"}.get(group, group)
    return f"{group}.{name}" if name else None


def parse_validation(payload: Any) -> Validation:
    data = _object(payload, "Validation")
    items = data.get("issues")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Validation response lacks an issue list")
    issues = []
    for item in items[:MAX_ISSUES]:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity")
        message = _text(item.get("message"), 400)
        if severity in SEVERITIES and message:
            issues.append(Issue(_text(item.get("field"), 80) or "", severity, message))
    # The backend's verdict is authoritative; an error we could not parse still blocks.
    valid = data.get("valid") is True and not any(i.severity == "error" for i in issues)
    return Validation(valid, tuple(issues))


def summary(validation: Validation, limit: int = 3) -> str:
    lines = [f"{i.field or 'project'}: {i.message}" for i in validation.errors[:limit]]
    more = len(validation.errors) - limit
    return "; ".join(lines) + (f" (+{more} more)" if more > 0 else "")


class ValidationApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def check(self, project: dict) -> Validation:
        payload, _ = self._client.send_json(
            "POST", "/api/animation/validate-schedules", {"project": project}, max_bytes=2 * 1024 * 1024)
        return parse_validation(payload)
