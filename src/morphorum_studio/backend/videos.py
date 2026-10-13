"""Video export (S3.3): availability, export jobs, and verified downloads.

The backend turns a *completed* render's PNG frames into MP4 or WebM with FFmpeg. Studio never
claims a video has sound unless the backend's own export record says audio was muxed in
(``audio_included``), and a downloaded file is only kept if its SHA-256 matches that record.
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import BackendClient, BackendError
from .images import JournalEntry
from .projects import valid_project_id
from .renders import RENDER_ID
from .schema import _number, _object, _text, _whole

FORMATS = ("mp4", "webm")
QUALITIES = ("high", "balanced", "compact")
ACTIVE = frozenset({"queued", "encoding"})
FINAL = frozenset({"completed", "failed", "interrupted"})
MAX_VIDEO_BYTES = 8 * 1024 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")
JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


@dataclass(frozen=True)
class VideoAvailability:
    available: bool
    formats: tuple[str, ...] = FORMATS
    qualities: tuple[str, ...] = QUALITIES
    message: str = ""


@dataclass(frozen=True)
class VideoExport:
    id: str | None
    project_id: str
    render_id: str
    format: str
    quality: str
    fps: int
    status: str
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    size: int | None = None
    sha256: str | None = None
    total_frames: int = 0
    audio_included: bool = False
    audio_source: str | None = None
    audio_offset: float = 0.0
    created_at: str | None = None

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    @property
    def final(self) -> bool:
        return self.status in FINAL

    @property
    def downloadable(self) -> bool:
        return self.status == "completed" and self.sha256 is not None and self.size is not None

    @property
    def variant(self) -> tuple[str, str, int]:
        return (self.format, self.quality, self.fps)


def parse_availability(payload: Any) -> VideoAvailability:
    data = _object(payload, "Video availability")
    formats = tuple(f for f in (data.get("formats") if isinstance(data.get("formats"), list) else [])
                    if f in FORMATS) or FORMATS
    qualities = tuple(q for q in (data.get("qualities") if isinstance(data.get("qualities"), list) else [])
                      if q in QUALITIES) or QUALITIES
    return VideoAvailability(data.get("available") is True, formats, qualities,
                             _text(data.get("message"), 300) or "")


def parse_export(payload: Any) -> VideoExport:
    data = _object(payload, "Video export")
    project_id, render_id = data.get("project_id"), data.get("render_id")
    fmt, quality, status = data.get("format"), data.get("quality"), _text(data.get("status"), 30)
    fps = _whole(data.get("fps"), 1)
    job_id = data.get("id")
    if (not valid_project_id(project_id) or not isinstance(render_id, str)
            or not RENDER_ID.fullmatch(render_id) or fmt not in FORMATS or quality not in QUALITIES
            or fps is None or fps > 120 or status is None
            or (job_id is not None and not (isinstance(job_id, str) and JOB_ID.fullmatch(job_id)))):
        raise BackendError("INVALID_RESPONSE", "Video export response is incomplete")
    digest = data.get("sha256")
    size = data.get("bytes")
    offset = data.get("audio_offset_seconds")
    progress = _number(data.get("progress"), 0, 1)
    return VideoExport(
        id=job_id, project_id=project_id, render_id=render_id, format=fmt, quality=quality, fps=fps,
        status=status, progress=progress if progress is not None else 0.0,
        message=_text(data.get("message"), 200) or "", error=_text(data.get("error"), 400),
        size=size if type(size) is int and size > 0 else None,
        sha256=digest if isinstance(digest, str) and _DIGEST.fullmatch(digest) else None,
        total_frames=_whole(data.get("total_frames"), 0) or 0,
        audio_included=data.get("audio_included") is True,
        audio_source=_text(data.get("audio_source"), 40),
        audio_offset=float(offset) if isinstance(offset, (int, float)) and not isinstance(offset, bool)
        and math.isfinite(offset) else 0.0,
        created_at=_text(data.get("created_at"), 40))


def parse_exports(payload: Any) -> tuple[VideoExport, ...]:
    items = _object(payload, "Video exports").get("exports")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Exports response lacks an exports list")
    result = []
    for item in items[:100]:
        with contextlib.suppress(BackendError):
            result.append(parse_export(item))
    return tuple(result)


def audio_text(export: VideoExport) -> str:
    """What the backend says about sound, and nothing more."""
    if not export.audio_included:
        return "No audio track"
    source = {"imported_soundtrack": "imported soundtrack", "motion_lab": "Motion Lab audio"}.get(
        export.audio_source or "", export.audio_source or "soundtrack")
    shift = f", offset {export.audio_offset:+g} s" if export.audio_offset else ""
    return f"With audio ({source}{shift})"


def describe(export: VideoExport) -> str:
    bits = [export.format.upper(), export.quality, f"{export.fps} fps"]
    if export.size:
        bits.append(_size(export.size))
    if export.status == "completed":
        bits.append(audio_text(export))
    elif export.status == "interrupted":
        bits.append("interrupted; export again")
    elif export.status == "failed":
        bits.append("failed")
    else:
        bits.append(f"{export.status} {export.progress * 100:.0f}%")
    return "  ·  ".join(bits)


def _size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class VideoApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    @staticmethod
    def _base(project_id: str, render_id: str) -> str:
        if not valid_project_id(project_id) or not RENDER_ID.fullmatch(render_id):
            raise ValueError("invalid project or render id")
        return f"/api/animation/renders/{project_id}/{render_id}"

    def availability(self) -> VideoAvailability:
        return parse_availability(self._client.get_json("/api/animation/video/availability"))

    def start(self, entry: JournalEntry) -> VideoExport:
        """``entry.payload`` is {"project_id", "render_id", "body": {format, quality, fps?}}."""
        p = entry.payload
        body = p.get("body")
        if not isinstance(body, dict):
            raise ValueError("malformed video export request")
        payload, _ = self._client.send_json(
            "POST", self._base(str(p.get("project_id")), str(p.get("render_id"))) + "/video",
            body, idempotency_key=entry.key)
        return parse_export(payload)

    def job(self, job_id: str) -> VideoExport:
        if not JOB_ID.fullmatch(job_id):
            raise ValueError("invalid export id")
        return parse_export(self._client.get_json(f"/api/animation/video/jobs/{job_id}"))

    def exports(self, project_id: str, render_id: str) -> tuple[VideoExport, ...]:
        return parse_exports(self._client.get_json(self._base(project_id, render_id) + "/videos"))

    def download(self, export: VideoExport, destination: str | os.PathLike) -> str:
        """Verified copy: SHA-256 and size must match the export record, then an atomic rename."""
        if not export.downloadable:
            raise ValueError("This export is not ready to download")
        dest = Path(destination)
        if dest.is_dir() or not dest.parent.is_dir():
            raise ValueError("Choose a file name in an existing folder")
        part = dest.with_name(dest.name + ".part")
        path = (self._base(export.project_id, export.render_id)
                + f"/video/{export.format}/{export.quality}/{export.fps}")
        try:
            with part.open("wb") as handle:
                total, digest, advertised = self._client.download(
                    path, handle.write, min(MAX_VIDEO_BYTES, (export.size or 0) + 1024 * 1024))
            if digest != export.sha256 or total != export.size \
                    or (advertised is not None and advertised != digest):
                raise BackendError("INVALID_RESPONSE",
                                   "The downloaded video failed its checksum; nothing was saved")
            os.replace(part, dest)
        except OSError as exc:
            raise BackendError("FILE_ERROR", f"Could not write the file: {exc.strerror or 'error'}") from exc
        finally:
            with contextlib.suppress(OSError):
                part.unlink()
        return str(dest)


def cached_video(cache_dir: Path, export: VideoExport) -> Path | None:
    """A previously downloaded, still-intact copy for playback, or None."""
    if export.sha256 is None:
        return None
    path = cache_dir / f"{export.sha256[:24]}.{export.format}"
    try:
        if path.is_file() and path.stat().st_size == export.size and sha256_file(path) == export.sha256:
            return path
    except OSError:
        pass
    return None


def prune_cache(cache_dir: Path, keep: int = 5) -> None:
    """Keep only the most recently used playback copies."""
    try:
        files = sorted((f for f in cache_dir.iterdir() if f.is_file() and f.suffix in (".mp4", ".webm")),
                       key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[keep:]:
        with contextlib.suppress(OSError):
            old.unlink()
