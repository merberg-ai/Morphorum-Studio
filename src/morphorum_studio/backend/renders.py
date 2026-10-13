"""Animation renders (S3.2): job parsing, the calls, and plain-language status text.

A render is started by sending the *complete saved project* (never just its id) with an
``Idempotency-Key``; the body and key are journalled first (see ``backend.images``). The backend
keeps a manifest per render, so a job survives a Studio exit and even a backend restart: after a
restart it reports ``interrupted`` and can be resumed from the frames already on disk. Job state
always comes from REST GETs; Studio does not rely on event streams (see docs/S3_2_ANIMATION.md).
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import BackendClient, BackendError
from .images import JournalEntry, _duration
from .projects import valid_project_id
from .schema import _number, _object, _text, _whole

RENDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
ACTIVE = frozenset({"queued", "loading_model", "rendering", "finalizing"})
FINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
MAX_FRAME_BYTES = 64 * 1024 * 1024
MAX_PREVIEW_BYTES = 256 * 1024 * 1024
RENDERS_PATH = "/api/animation/renders"


@dataclass(frozen=True)
class RenderJob:
    id: str
    project_id: str
    status: str
    message: str = ""
    progress: float = 0.0
    eta_seconds: float | None = None
    current_frame: int = 0
    total_frames: int = 0
    current_step: int = 0
    current_step_total: int = 0
    load_progress: float | None = None
    load_phase: str = ""
    load_message: str = ""
    latest_frame: int | None = None
    completed_frames: int = 0
    has_preview: bool = False
    resumable: bool = False
    resumed: bool = False
    cancel_requested: bool = False
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    frame_seconds: float | None = None
    average_frame_seconds: float | None = None
    soundtrack: str | None = None  # file name when a soundtrack is frozen into this render
    hybrid: bool = False

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    @property
    def final(self) -> bool:
        return self.status in FINAL


def parse_render(payload: Any) -> RenderJob:
    data = _object(payload, "Render")
    render_id, project_id = data.get("id"), data.get("project_id")
    status = _text(data.get("status"), 30)
    if (not isinstance(render_id, str) or not RENDER_ID.fullmatch(render_id)
            or not valid_project_id(project_id) or status is None):
        raise BackendError("INVALID_RESPONSE", "Render response is incomplete")
    results = data.get("results") if isinstance(data.get("results"), list) else []
    frames = {r.get("frame") for r in results[:100_000]
              if isinstance(r, Mapping) and type(r.get("frame")) is int and r["frame"] >= 0}
    latest = _whole(data.get("latest_completed_frame"), 0)
    if latest is None and frames:
        latest = max(frames)
    progress = _number(data.get("progress"), 0, 1)
    soundtrack = data.get("imported_soundtrack")
    hybrid = data.get("hybrid_source")
    return RenderJob(
        id=render_id, project_id=project_id, status=status,
        message=_text(data.get("message"), 200) or "",
        progress=progress if progress is not None else 0.0,
        eta_seconds=_number(data.get("eta_seconds"), 0, 10**7),
        current_frame=_whole(data.get("current_frame"), 0) or 0,
        total_frames=_whole(data.get("total_frames"), 0) or 0,
        current_step=_whole(data.get("current_step"), 0) or 0,
        current_step_total=_whole(data.get("current_step_total"), 0) or 0,
        load_progress=_number(data.get("load_progress"), 0, 1),
        load_phase=_text(data.get("load_phase"), 40) or "",
        load_message=_text(data.get("load_message"), 200) or "",
        latest_frame=latest, completed_frames=len(frames) or (latest + 1 if latest is not None else 0),
        has_preview=bool(data.get("preview_url")),
        resumable=data.get("resumable") is True,
        resumed=data.get("resumed") is True,
        cancel_requested=data.get("cancel_requested") is True,
        error=_text(data.get("error"), 400),
        created_at=_text(data.get("created_at"), 40), completed_at=_text(data.get("completed_at"), 40),
        frame_seconds=_number(data.get("frame_seconds"), 0, 10**6),
        average_frame_seconds=_number(data.get("average_frame_seconds"), 0, 10**6),
        soundtrack=(_text(soundtrack.get("filename"), 160) or "soundtrack")
        if isinstance(soundtrack, Mapping) and soundtrack.get("enabled") is True else None,
        hybrid=isinstance(hybrid, Mapping) and hybrid.get("enabled") is True,
    )


def parse_render_list(payload: Any) -> tuple[RenderJob, ...]:
    items = _object(payload, "Renders").get("renders")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Renders response lacks a renders list")
    jobs = []
    for item in items[:100]:
        with contextlib.suppress(BackendError):
            jobs.append(parse_render(item))
    return tuple(jobs)


class RenderApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    @staticmethod
    def _render_path(render_id: str) -> str:
        if not RENDER_ID.fullmatch(render_id):
            raise ValueError("invalid render id")
        return f"{RENDERS_PATH}/{render_id}"

    @staticmethod
    def _files(project_id: str, render_id: str, suffix: str) -> str:
        if not valid_project_id(project_id) or not RENDER_ID.fullmatch(render_id):
            raise ValueError("invalid project or render id")
        return f"{RENDERS_PATH}/{project_id}/{render_id}/{suffix}"

    def submit(self, entry: JournalEntry) -> RenderJob:
        payload, _ = self._client.send_json(
            "POST", RENDERS_PATH, entry.payload, idempotency_key=entry.key, max_bytes=2 * 1024 * 1024)
        return parse_render(payload)

    def get(self, render_id: str) -> RenderJob:
        return parse_render(self._client.get_json(self._render_path(render_id)))

    def for_project(self, project_id: str) -> tuple[RenderJob, ...]:
        if not valid_project_id(project_id):
            raise ValueError("invalid project id")
        return parse_render_list(
            self._client.get_json(f"/api/animation/projects/{project_id}/renders"))

    def cancel(self, render_id: str) -> RenderJob:
        payload, _ = self._client.send_json("POST", self._render_path(render_id) + "/cancel")
        return parse_render(payload)

    def resume(self, project_id: str, render_id: str) -> RenderJob:
        """Continue from the frames already rendered. Not retried: a second resume is refused."""
        payload, _ = self._client.send_json("POST", self._files(project_id, render_id, "resume"))
        return parse_render(payload)

    def frame_bytes(self, project_id: str, render_id: str, frame: int) -> bytes:
        if type(frame) is not int or not 0 <= frame <= 1_000_000:
            raise ValueError("invalid frame number")
        return self._png(self._files(project_id, render_id, f"frames/{frame}"))

    def _png(self, path: str) -> bytes:
        chunks: list[bytes] = []
        self._client.download(path, chunks.append, MAX_FRAME_BYTES)
        data = b"".join(chunks)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise BackendError("INVALID_RESPONSE", "The backend did not return a PNG frame")
        return data

    def preview_bytes(self, project_id: str, render_id: str) -> bytes:
        chunks: list[bytes] = []
        self._client.download(self._files(project_id, render_id, "preview"), chunks.append,
                              MAX_PREVIEW_BYTES)
        data = b"".join(chunks)
        if not data.startswith((b"GIF87a", b"GIF89a")):
            raise BackendError("INVALID_RESPONSE", "The backend did not return a GIF preview")
        return data

    def save_frame(self, project_id: str, render_id: str, frame: int, destination: str | os.PathLike) -> str:
        path = self._files(project_id, render_id, f"frames/{frame}")
        return self._save(path, destination, b"\x89PNG\r\n\x1a\n", MAX_FRAME_BYTES)

    def save_preview(self, project_id: str, render_id: str, destination: str | os.PathLike) -> str:
        return self._save(self._files(project_id, render_id, "preview"), destination,
                          b"GIF8", MAX_PREVIEW_BYTES)

    def _save(self, path: str, destination: str | os.PathLike, magic: bytes, limit: int) -> str:
        dest = Path(destination)
        if dest.is_dir() or not dest.parent.is_dir():
            raise ValueError("Choose a file name in an existing folder")
        part = dest.with_name(dest.name + ".part")
        head = bytearray()
        try:
            with part.open("wb") as handle:
                def sink(chunk: bytes) -> None:
                    if len(head) < len(magic):
                        head.extend(chunk[: len(magic) - len(head)])
                    handle.write(chunk)
                total, _, _ = self._client.download(path, sink, limit)
            if total < len(magic) or bytes(head) != magic:
                raise BackendError("INVALID_RESPONSE", "The backend returned an unexpected file; nothing was saved")
            os.replace(part, dest)
        except OSError as exc:
            raise BackendError("FILE_ERROR", f"Could not write the file: {exc.strerror or 'error'}") from exc
        finally:
            with contextlib.suppress(OSError):
                part.unlink()
        return str(dest)


def render_text(job: RenderJob) -> str:
    """Plain-language status line."""
    if job.status == "queued":
        return "Waiting in the queue" + (" (resuming)" if job.resumed else "")
    if job.status == "loading_model":
        detail = job.load_message or "Loading the model"
        if job.load_progress is not None and 0 < job.load_progress < 1:
            detail += f" ({job.load_progress * 100:.0f}%)"
        return detail
    if job.status == "rendering":
        parts = [f"frame {min(job.current_frame + 1, job.total_frames) if job.total_frames else job.current_frame + 1}"
                 + (f" of {job.total_frames}" if job.total_frames else "")]
        if job.current_step_total:
            parts.append(f"step {job.current_step} of {job.current_step_total}")
        if job.eta_seconds:
            parts.append(f"about {_duration(job.eta_seconds)} left")
        return ", ".join(parts)
    if job.status == "finalizing":
        return job.message or "Finishing up"
    if job.status == "completed":
        return f"Done: {job.completed_frames} frame{'s' if job.completed_frames != 1 else ''}"
    if job.status == "cancelled":
        return f"Cancelled after {job.completed_frames} frame{'s' if job.completed_frames != 1 else ''}"
    if job.status == "interrupted":
        return f"Interrupted after {job.completed_frames} frame{'s' if job.completed_frames != 1 else ''}; it can be resumed"
    if job.status == "failed":
        return "Failed" + (f": {job.error}" if job.error else "")
    return job.status.replace("_", " ").capitalize()
