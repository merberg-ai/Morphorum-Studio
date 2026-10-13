"""Project-owned media (S2.3): source image and imported soundtrack.

Uploads are read from a file the user picked, checked locally (extension, size, signature) and
sent with their SHA-256 so the backend can verify the transfer. Downloads stream to a ``.part``
file beside the destination, are verified against the catalogue digest and then renamed into
place, so a failed or interrupted copy never leaves a half-written file under the final name.
No server file paths are ever shown or used: assets are addressed by project id only.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .client import BackendClient, BackendError
from .projects import valid_project_id
from .schema import _object, _text

SOURCE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
SOURCE_MAX_BYTES = 32 * 1024 * 1024
AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac")
AUDIO_MAX_BYTES = 40 * 1024 * 1024
OFFSET_LIMIT = 30.0
PREVIEW_MAX_BYTES = 12 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Asset:
    kind: str  # source_image | soundtrack | motion_lab_wav
    id: str
    filename: str
    size: int
    media_type: str
    sha256: str


@dataclass(frozen=True)
class Soundtrack:
    filename: str
    format: str
    size: int | None
    offset_seconds: float
    sha256: str


def parse_assets(payload: Any) -> tuple[Asset, ...]:
    items = _object(payload, "Assets").get("assets")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Assets response lacks an assets list")
    result = []
    for item in items[:200]:
        if not isinstance(item, Mapping):
            continue
        kind, sha = _text(item.get("kind"), 30), item.get("sha256")
        size = item.get("bytes")
        if kind is None or not isinstance(sha, str) or not _DIGEST.fullmatch(sha) \
                or type(size) is not int or size < 1:
            continue
        result.append(Asset(
            kind=kind, id=_text(item.get("id"), 80) or sha,
            filename=_text(item.get("filename"), 200) or kind,
            size=size, media_type=_text(item.get("media_type"), 60) or "application/octet-stream",
            sha256=sha))
    return tuple(result)


def parse_soundtrack(payload: Any) -> Soundtrack | None:
    record = _object(payload, "Soundtrack").get("soundtrack")
    if record is None:
        return None
    if not isinstance(record, Mapping):
        raise BackendError("INVALID_RESPONSE", "Soundtrack record is invalid")
    sha, offset, size = record.get("sha256"), record.get("offset_seconds"), record.get("bytes")
    if not isinstance(sha, str) or not _DIGEST.fullmatch(sha):
        raise BackendError("INVALID_RESPONSE", "Soundtrack record has no checksum")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
        offset = 0.0
    return Soundtrack(
        filename=_text(record.get("filename"), 160) or "soundtrack",
        format=_text(record.get("format"), 8) or "?",
        size=size if type(size) is int and size > 0 else None,
        offset_seconds=float(offset), sha256=sha)


def check_offset(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or abs(value) > OFFSET_LIMIT:
        raise ValueError(f"The offset must be within -{OFFSET_LIMIT:g} and +{OFFSET_LIMIT:g} seconds")
    return float(value)


def read_local(path: str | os.PathLike, extensions: tuple[str, ...], max_bytes: int,
               what: str) -> tuple[bytes, str, str]:
    """Read a user-chosen file: (data, sha256, file name). Checks run before any network use."""
    file = Path(path)
    if file.suffix.lower() not in extensions:
        raise ValueError(f"Choose a supported {what} file ({', '.join(extensions)})")
    try:
        if not file.is_file():
            raise ValueError("That file could not be found")
        size = file.stat().st_size
        if size < 1:
            raise ValueError("That file is empty")
        if size > max_bytes:
            raise ValueError(f"{what.capitalize()} files are limited to {max_bytes // (1024 * 1024)} MiB")
        data = file.read_bytes()
    except OSError as exc:
        raise ValueError(f"That file could not be read: {exc.strerror or 'error'}") from exc
    return data, hashlib.sha256(data).hexdigest(), file.name


def _ascii_name(name: str, fallback: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip()[:100]
    return clean or fallback


class AssetsApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    @staticmethod
    def _base(project_id: str) -> str:
        if not valid_project_id(project_id):
            raise ValueError("invalid project id")
        return f"/api/animation/projects/{project_id}"

    # -- reads ----------------------------------------------------------------------------

    def catalogue(self, project_id: str) -> tuple[Asset, ...]:
        return parse_assets(self._client.get_json(self._base(project_id) + "/assets"))

    def soundtrack(self, project_id: str) -> Soundtrack | None:
        return parse_soundtrack(
            self._client.get_json(self._base(project_id) + "/motion-import/soundtrack"))

    # -- writes (never retried) -------------------------------------------------------------

    def upload_source(self, project_id: str, path: str) -> None:
        data, sha, name = read_local(path, SOURCE_EXTENSIONS, SOURCE_MAX_BYTES, "image")
        self._client.upload_bytes(self._base(project_id) + "/source-image", data, {
            "X-Content-SHA256": sha, "X-Filename": _ascii_name(name, "source-image")})

    def clear_source(self, project_id: str) -> None:
        self._client.send_json("DELETE", self._base(project_id) + "/source-image")

    def attach_soundtrack(self, project_id: str, path: str, offset: float = 0.0) -> Soundtrack | None:
        offset = check_offset(offset)
        data, sha, name = read_local(path, AUDIO_EXTENSIONS, AUDIO_MAX_BYTES, "audio")
        stem, ext = os.path.splitext(name)
        encoded = quote(stem[:80] + ext.lower(), safe="")
        while len(encoded) > 280:
            stem = stem[:-8]
            encoded = quote(stem + ext.lower(), safe="")
        self._client.upload_bytes(self._base(project_id) + "/motion-import/soundtrack", data, {
            "X-Content-SHA256": sha, "X-Audio-Filename": encoded,
            "X-Audio-Offset-Seconds": f"{offset:.3f}"})
        return self.soundtrack(project_id)

    def set_offset(self, project_id: str, offset: float) -> Soundtrack | None:
        self._client.send_json("PUT", self._base(project_id) + "/motion-import/soundtrack-offset",
                               {"offset_seconds": check_offset(offset)})
        return self.soundtrack(project_id)

    # -- downloads --------------------------------------------------------------------------

    def _path_for(self, project_id: str, asset: Asset) -> str:
        base = self._base(project_id)
        if asset.kind == "source_image":
            return base + "/source-image"
        if asset.kind == "soundtrack":
            return base + "/motion-import/soundtrack/file"
        raise ValueError("this asset cannot be downloaded here")

    def save_copy(self, project_id: str, asset: Asset, destination: str | os.PathLike) -> str:
        """Verified copy of an asset to a user-chosen file. Returns the final path."""
        dest = Path(destination)
        if dest.is_dir() or not dest.parent.is_dir():
            raise ValueError("Choose a file name in an existing folder")
        part = dest.with_name(dest.name + ".part")
        try:
            with part.open("wb") as handle:
                total, digest, advertised = self._client.download(
                    self._path_for(project_id, asset), handle.write, max_bytes=asset.size + 1024 * 1024)
            if digest != asset.sha256 or (advertised is not None and advertised != digest):
                raise BackendError("INVALID_RESPONSE", "The downloaded file failed its checksum; nothing was saved")
            os.replace(part, dest)
        except OSError as exc:
            raise BackendError("FILE_ERROR", f"Could not write the file: {exc.strerror or 'error'}") from exc
        finally:
            try:
                part.unlink()
            except OSError:
                pass
        return str(dest)

    def preview_source(self, project_id: str, asset: Asset) -> bytes | None:
        """Image bytes for a thumbnail, verified; None when the image is too big to preview."""
        if asset.size > PREVIEW_MAX_BYTES:
            return None
        chunks: list[bytes] = []
        _, digest, _ = self._client.download(
            self._path_for(project_id, asset), chunks.append, max_bytes=asset.size + 1024 * 1024)
        if digest != asset.sha256:
            raise BackendError("INVALID_RESPONSE", "The preview failed its checksum")
        return b"".join(chunks)
