"""Image generation (S3.1): request building, job parsing, the submission journal and the calls.

Every submission is written to a small journal file, key and exact body, *before* the POST. If the
connection drops after the backend accepted the request, retrying the same entry sends the same
``Idempotency-Key`` and the same body, and the backend returns the existing job instead of
starting another. Entries are removed once the outcome is certain (a definitive refusal, or the
job reached a final state while Studio was watching).
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import BackendClient, BackendError
from .schema import FamilyDefaults, _number, _object, _text, _whole

JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
IMAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
ACTIVE = frozenset({"queued", "loading_model", "generating", "finalizing"})
FINAL = frozenset({"completed", "failed", "cancelled"})
MAX_PROMPT = 4000
MAX_IMAGE_BYTES = 64 * 1024 * 1024
SEED_MAX = 2**32 - 1
SEED_MODES = ("fixed", "increment", "random")
JOB_PATH = "/api/generation/jobs"


# ----------------------------------------------------------------------------- request

@dataclass(frozen=True)
class GenerationSpec:
    model_id: str
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 25
    guidance_scale: float = 7.0
    sampler: str = "euler"
    seed: int = -1
    seed_mode: str = "fixed"
    seed_increment: int = 1
    images: int = 1

    def payload(self, negative_allowed: bool = True) -> dict[str, Any]:
        """The exact JSON body sent to the backend (and saved in the journal)."""
        return {
            "model_id": self.model_id, "prompt": self.prompt.strip(),
            "negative_prompt": self.negative_prompt.strip() if negative_allowed else "",
            "width": self.width, "height": self.height, "steps": self.steps,
            "guidance_scale": round(float(self.guidance_scale), 4), "sampler": self.sampler,
            "seed": self.seed, "seed_mode": self.seed_mode,
            "seed_increment": self.seed_increment, "images": self.images,
        }


def size_step(family: str) -> int:
    return 16 if family in ("flux", "zimage") else 8


def validate_spec(spec: GenerationSpec, limits: FamilyDefaults, family: str) -> str | None:
    """First problem found, in plain words, or None. The backend still has the final say."""
    if not spec.model_id:
        return "Choose a model."
    if not spec.prompt.strip():
        return "Write a prompt."
    if len(spec.prompt) > MAX_PROMPT or len(spec.negative_prompt) > MAX_PROMPT:
        return f"Prompts are limited to {MAX_PROMPT} characters."
    step = size_step(family)
    for name, value in (("Width", spec.width), ("Height", spec.height)):
        if not 64 <= value <= 4096 or value % step:
            return f"{name} must be a multiple of {step} between 64 and 4096."
    if limits.steps_min is not None and limits.steps_max is not None \
            and not limits.steps_min <= spec.steps <= limits.steps_max:
        return f"Steps must be between {limits.steps_min} and {limits.steps_max}."
    if limits.guidance_min is not None and limits.guidance_max is not None \
            and not limits.guidance_min <= spec.guidance_scale <= limits.guidance_max:
        return f"{limits.guidance_label or 'Guidance'} must be between " \
               f"{limits.guidance_min:g} and {limits.guidance_max:g}."
    if limits.sampler_ids and spec.sampler not in limits.sampler_ids:
        return "Choose one of the listed samplers."
    if not 1 <= spec.images <= 32:
        return "Image count must be between 1 and 32."
    if spec.seed != -1 and not 0 <= spec.seed <= SEED_MAX:
        return "Seed must be -1 (random) or between 0 and 4294967295."
    if spec.seed_mode not in SEED_MODES:
        return "Choose a seed mode."
    if abs(spec.seed_increment) > 1_000_000:
        return "Seed increment is too large."
    return None


def model_variant(name: str | None, filename: str | None, variant: str | None, family: str) -> str | None:
    """Mirror of how the backend picks a variant, so the right limits are shown."""
    if variant:
        return variant.lower()
    if family == "flux":
        return "schnell" if "schnell" in f"{name or ''} {filename or ''}".lower() else "dev"
    return family or None


# ----------------------------------------------------------------------------- jobs

@dataclass(frozen=True)
class ResultImage:
    index: int
    seed: int | None
    filename: str


@dataclass(frozen=True)
class ImageJob:
    id: str
    status: str
    message: str = ""
    progress: float = 0.0
    current_image: int = 0
    images: int = 1
    current_step: int = 0
    total_steps: int = 0
    eta_seconds: float | None = None
    seeds: tuple[int, ...] = ()
    results: tuple[ResultImage, ...] = ()
    error: str | None = None
    cancel_requested: bool = False
    created_at: str | None = None
    completed_at: str | None = None
    model_name: str | None = None
    prompt: str = ""

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    @property
    def final(self) -> bool:
        return self.status in FINAL


def parse_job(payload: Any) -> ImageJob:
    data = _object(payload, "Job")
    job_id = data.get("id")
    status = _text(data.get("status"), 30)
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id) or status is None:
        raise BackendError("INVALID_RESPONSE", "Generation job response is incomplete")
    request = data.get("request") if isinstance(data.get("request"), Mapping) else {}
    model = data.get("model") if isinstance(data.get("model"), Mapping) else {}
    progress = _number(data.get("progress"), 0, 1)
    results = []
    for item in (data.get("results") if isinstance(data.get("results"), list) else [])[:64]:
        if not isinstance(item, Mapping):
            continue
        name = item.get("filename")
        if not isinstance(name, str) or not IMAGE_NAME.fullmatch(name):
            continue
        seed = item.get("seed")
        results.append(ResultImage(
            index=_whole(item.get("index"), 0) or len(results) + 1,
            seed=seed if type(seed) is int else None, filename=name))
    seeds = data.get("seeds") if isinstance(data.get("seeds"), list) else []
    return ImageJob(
        id=job_id, status=status, message=_text(data.get("message"), 200) or "",
        progress=progress if progress is not None else 0.0,
        current_image=_whole(data.get("current_image"), 0) or 0,
        images=_whole(request.get("images"), 1) or 1,
        current_step=_whole(data.get("current_step"), 0) or 0,
        total_steps=_whole(data.get("total_steps"), 0) or 0,
        eta_seconds=_number(data.get("eta_seconds"), 0, 10**7),
        seeds=tuple(v for v in seeds[:64] if type(v) is int),
        results=tuple(results), error=_text(data.get("error"), 400),
        cancel_requested=data.get("cancel_requested") is True,
        created_at=_text(data.get("created_at"), 40), completed_at=_text(data.get("completed_at"), 40),
        model_name=_text(model.get("name"), 120), prompt=_text(request.get("prompt"), 300) or "",
    )


def parse_jobs(payload: Any) -> tuple[ImageJob, ...]:
    items = _object(payload, "Jobs").get("jobs")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Jobs response lacks a jobs list")
    jobs = []
    for item in items[:50]:
        try:
            jobs.append(parse_job(item))
        except BackendError:
            continue
    return tuple(jobs)


# ----------------------------------------------------------------------------- journal

_KEY = re.compile(r"studio-[0-9a-f]{32}")


@dataclass(frozen=True)
class JournalEntry:
    key: str
    profile_id: str
    payload: dict
    created: float
    state: str = "pending"  # pending: POST may or may not have reached the backend
    job_id: str | None = None  # submitted: the backend gave us this job
    kind: str = "image"  # image | animation


class SubmissionJournal:
    MAX_ENTRIES = 50
    MAX_BYTES = 2 * 1024 * 1024  # an animation entry carries the whole project

    def __init__(self, directory: str | os.PathLike) -> None:
        self._dir = Path(directory)

    def _file(self, key: str) -> Path:
        if not _KEY.fullmatch(key):
            raise ValueError("invalid submission key")
        return self._dir / (key + ".json")

    def _write(self, entry: JournalEntry) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._file(entry.key)
        temp = target.with_name(target.name + ".tmp")
        body = json.dumps({"v": 1, "key": entry.key, "profile": entry.profile_id,
                           "payload": entry.payload, "created": entry.created,
                           "state": entry.state, "job_id": entry.job_id, "kind": entry.kind})
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(temp, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)

    def begin(self, profile_id: str, payload: dict, kind: str = "image") -> JournalEntry:
        """Persist the exact body and a fresh key. Call before the POST, never after."""
        if kind not in ("image", "animation"):
            raise ValueError("unknown submission kind")
        if len(self.entries(profile_id)) >= self.MAX_ENTRIES:
            raise ValueError("Too many unfinished submissions; resolve or discard some first")
        entry = JournalEntry("studio-" + secrets.token_hex(16), profile_id, dict(payload),
                             time.time(), kind=kind)
        self._write(entry)
        return entry

    def submitted(self, entry: JournalEntry, job_id: str) -> JournalEntry:
        updated = JournalEntry(entry.key, entry.profile_id, entry.payload, entry.created,
                               "submitted", job_id, entry.kind)
        self._write(updated)
        return updated

    def finish(self, key: str) -> None:
        with contextlib.suppress(OSError):
            self._file(key).unlink()

    def entries(self, profile_id: str | None = None, kind: str | None = None) -> list[JournalEntry]:
        found = []
        try:
            files = sorted(self._dir.glob("studio-*.json"))
        except OSError:
            return []
        for file in files[: self.MAX_ENTRIES * 2]:
            try:
                if file.is_symlink() or file.stat().st_size > self.MAX_BYTES:
                    continue
                raw = json.loads(file.read_text(encoding="utf-8"))
                key, payload = raw["key"], raw["payload"]
                state = raw.get("state")
                job_id = raw.get("job_id")
                if (key + ".json" != file.name or not _KEY.fullmatch(key)
                        or not isinstance(payload, dict) or state not in ("pending", "submitted")
                        or not isinstance(raw.get("profile"), str)
                        or (job_id is not None and not (isinstance(job_id, str) and JOB_ID.fullmatch(job_id)))):
                    continue
                entry_kind = raw.get("kind", "image")
                if entry_kind not in ("image", "animation"):
                    continue
                if (profile_id is None or raw["profile"] == profile_id) \
                        and (kind is None or entry_kind == kind):
                    found.append(JournalEntry(key, raw["profile"], payload, float(raw.get("created", 0)),
                                              state, job_id, entry_kind))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        found.sort(key=lambda e: e.created)
        return found


# ----------------------------------------------------------------------------- calls

# A refusal that proves the backend did not (and will not) create the job.
DEFINITIVE = frozenset({"INVALID_REQUEST", "VALIDATION_ERROR", "AUTH_REQUIRED", "FORBIDDEN", "NOT_FOUND"})


class ImagesApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    @staticmethod
    def _job_path(job_id: str, suffix: str = "") -> str:
        if not JOB_ID.fullmatch(job_id):
            raise ValueError("invalid job id")
        return f"{JOB_PATH}/{job_id}{suffix}"

    def submit(self, entry: JournalEntry) -> ImageJob:
        payload, _ = self._client.send_json("POST", JOB_PATH, entry.payload, idempotency_key=entry.key)
        return parse_job(payload)

    def job(self, job_id: str) -> ImageJob:
        return parse_job(self._client.get_json(self._job_path(job_id)))

    def recent(self, limit: int = 20) -> tuple[ImageJob, ...]:
        return parse_jobs(self._client.get_json(JOB_PATH, {"limit": limit}))

    def cancel(self, job_id: str) -> ImageJob:
        payload, _ = self._client.send_json("POST", self._job_path(job_id, "/cancel"))
        return parse_job(payload)

    def image_bytes(self, job_id: str, filename: str, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
        chunks: list[bytes] = []
        self._client.download(self._image_path(job_id, filename), chunks.append, max_bytes)
        data = b"".join(chunks)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise BackendError("INVALID_RESPONSE", "The backend did not return a PNG image")
        return data

    def _image_path(self, job_id: str, filename: str) -> str:
        if not IMAGE_NAME.fullmatch(filename):
            raise ValueError("invalid image name")
        return self._job_path(job_id, "/images/" + filename)

    def save_copy(self, job_id: str, filename: str, destination: str | os.PathLike) -> str:
        """Stream a result to a user-chosen file via ``.part``, check it is a PNG, then rename."""
        dest = Path(destination)
        if dest.is_dir() or not dest.parent.is_dir():
            raise ValueError("Choose a file name in an existing folder")
        part = dest.with_name(dest.name + ".part")
        head = bytearray()
        try:
            with part.open("wb") as handle:
                def sink(chunk: bytes) -> None:
                    if len(head) < 8:
                        head.extend(chunk[: 8 - len(head)])
                    handle.write(chunk)
                total, _, _ = self._client.download(self._image_path(job_id, filename), sink,
                                                    MAX_IMAGE_BYTES)
            if total < 8 or bytes(head) != b"\x89PNG\r\n\x1a\n":
                raise BackendError("INVALID_RESPONSE", "The backend did not return a PNG image; nothing was saved")
            os.replace(part, dest)
        except OSError as exc:
            raise BackendError("FILE_ERROR", f"Could not write the file: {exc.strerror or 'error'}") from exc
        finally:
            with contextlib.suppress(OSError):
                part.unlink()
        return str(dest)


def eta_text(job: ImageJob) -> str:
    """Short human status line for a job."""
    if job.status == "queued":
        return "Waiting in the queue"
    if job.status == "loading_model":
        return "Loading the model"
    if job.status == "generating":
        parts = []
        if job.images > 1:
            parts.append(f"image {min(job.current_image + 1, job.images)} of {job.images}")
        if job.total_steps:
            parts.append(f"step {job.current_step} of {job.total_steps}")
        if job.eta_seconds is not None and math.isfinite(job.eta_seconds) and job.eta_seconds > 0:
            parts.append(f"about {_duration(job.eta_seconds)} left")
        return ", ".join(parts) or "Generating"
    if job.status == "finalizing":
        return "Finishing up"
    if job.status == "completed":
        return f"Done, {len(job.results)} image{'s' if len(job.results) != 1 else ''}"
    if job.status == "cancelled":
        return "Cancelled"
    if job.status == "failed":
        return "Failed" + (f": {job.error}" if job.error else "")
    return job.status.replace("_", " ").capitalize()


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} min {rest:02d} s" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"
