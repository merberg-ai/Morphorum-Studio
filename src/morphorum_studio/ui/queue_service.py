"""The Queue page's data: image jobs and animation renders in one list.

The backend has no endpoint that lists jobs across projects, so renders are read from each recent
project's own render list (one small request each) and image jobs from the image-jobs list.
Refresh is quick while something is running and slow when everything is finished. A
single failing project never hides the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.images import ImagesApi, ImageJob, eta_text
from morphorum_studio.backend.projects import ProjectsApi
from morphorum_studio.backend.renders import RenderApi, RenderJob, render_text
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner
from morphorum_studio.ui.recent_service import recent_first

PROJECT_COUNT = 12
IMAGE_COUNT = 30
ACTIVE_MS = 3000
IDLE_MS = 15000


@dataclass(frozen=True)
class QueueEntry:
    kind: str  # "render" | "image"
    id: str
    title: str
    detail: str  # project name for renders, model name for images
    status: str
    text: str  # plain-language status line
    progress: float = 0.0
    active: bool = False
    can_cancel: bool = False
    can_resume: bool = False
    project_id: str | None = None
    created_at: str | None = None


def chip_for(status: str) -> tuple[str, str]:
    """(label, state) for a status chip; the state drives the colour."""
    if status == "queued":
        return "Waiting", "idle"
    if status in ("loading_model", "rendering", "generating", "finalizing"):
        return "Running", "busy"
    return {
        "completed": ("Done", "ok"),
        "failed": ("Failed", "bad"),
        "cancelled": ("Cancelled", "idle"),
        "interrupted": ("Interrupted", "warn"),
    }.get(status, (status.replace("_", " ").capitalize(), "idle"))


def render_entry(job: RenderJob, project_name: str) -> QueueEntry:
    return QueueEntry(
        kind="render", id=job.id, title=f"Render {job.id}", detail=project_name,
        status=job.status, text=render_text(job) + (" (cancelling…)" if job.cancel_requested and job.active else ""),
        progress=job.progress, active=job.active,
        can_cancel=job.active and not job.cancel_requested,
        can_resume=job.resumable and not job.active,
        project_id=job.project_id, created_at=job.created_at)


def image_entry(job: ImageJob) -> QueueEntry:
    title = job.prompt.strip() or job.id
    if len(title) > 70:
        title = title[:69] + "…"
    return QueueEntry(
        kind="image", id=job.id, title=title, detail=job.model_name or "Image job",
        status=job.status, text=eta_text(job) + (" (cancelling…)" if job.cancel_requested and job.active else ""),
        progress=job.progress, active=job.active,
        can_cancel=job.active and not job.cancel_requested, created_at=job.created_at)


def sort_entries(entries) -> tuple[QueueEntry, ...]:
    """Running and waiting jobs first (oldest first, so the next to run is on top), then the newest finished."""
    active = sorted((e for e in entries if e.active), key=lambda e: e.created_at or "")
    done = sorted((e for e in entries if not e.active), key=lambda e: e.created_at or "", reverse=True)
    return tuple(active) + tuple(done)


def load_queue(client: BackendClient, images: bool, renders: bool,
               projects: int = PROJECT_COUNT) -> tuple[QueueEntry, ...]:
    """Runs on a worker thread. Raises only when nothing at all could be read."""
    entries: list[QueueEntry] = []
    failures: list[BackendError] = []
    attempts = 0
    if images:
        attempts += 1
        try:
            entries += [image_entry(j) for j in ImagesApi(client).recent(IMAGE_COUNT)]
        except BackendError as exc:
            failures.append(exc)
    if renders:
        attempts += 1
        try:
            summaries = recent_first(ProjectsApi(client).list_projects(), projects)
        except BackendError as exc:
            failures.append(exc)
            summaries = ()
        api = RenderApi(client)
        for project in summaries:
            try:
                entries += [render_entry(j, project.name) for j in api.for_project(project.id)]
            except BackendError:
                continue
    if failures and len(failures) == attempts:
        raise failures[0]
    return sort_entries(entries)


class QueueService(QObject):
    updated = Signal(object)  # tuple[QueueEntry]
    failed = Signal(str)  # error code
    action_failed = Signal(str)  # message for a cancel or resume the backend refused
    cleared = Signal()

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 runner: Runner | None = None, projects: int = PROJECT_COUNT,
                 active_ms: int = ACTIVE_MS, idle_ms: int = IDLE_MS) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._projects, self._active_ms, self._idle_ms = projects, active_ms, idle_ms
        self._epoch = session.epoch
        self._on = False
        self._inflight = False
        self._again = False
        self._last: tuple[QueueEntry, ...] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        session.changed.connect(self._session_changed)

    @property
    def last(self) -> tuple[QueueEntry, ...] | None:
        return self._last

    @property
    def sources(self) -> tuple[bool, bool]:
        """(image jobs, animation renders) the connected backend offers."""
        if self._session.state != "connected":
            return False, False
        return (self._session.feature("sdxl_generation"),
                self._session.feature("animation_render") and self._session.feature("project_crud"))

    @property
    def available(self) -> bool:
        return any(self.sources)

    def set_active(self, active: bool) -> None:
        if active == self._on:
            return
        self._on = active
        if active:
            self.refresh()
        else:
            self._timer.stop()

    def refresh(self) -> None:
        self._timer.stop()
        if self._inflight:
            self._again = True
            return
        images, renders = self.sources
        client = self._session.client(timeout=20.0) if (images or renders) else None
        if client is None:
            return
        self._inflight = True
        epoch, count = self._session.epoch, self._projects
        self._run(client, lambda c: load_queue(c, images, renders, count),
                  lambda result, error: self._done(epoch, result, error))

    def cancel(self, entry: QueueEntry) -> None:
        def work(c: BackendClient) -> Any:
            return (ImagesApi(c).cancel(entry.id) if entry.kind == "image"
                    else RenderApi(c).cancel(entry.id))
        self._act(work)

    def resume(self, entry: QueueEntry) -> None:
        if entry.kind != "render" or not entry.project_id:
            return
        self._act(lambda c: RenderApi(c).resume(entry.project_id, entry.id))

    # -- internals ----------------------------------------------------------------------

    def _act(self, work) -> None:
        client = self._session.client(timeout=20.0)
        if client is None:
            return
        epoch = self._session.epoch

        def done(_result, error) -> None:
            if epoch != self._session.epoch:
                return
            if error:
                self.action_failed.emit(error[1])
            self.refresh()

        self._run(client, work, done)

    def _done(self, epoch: int, result, error) -> None:
        if epoch != self._session.epoch or self._session.state == "offline":
            return
        self._inflight = False
        if error:
            self.failed.emit(error[0])
        else:
            self._last = result
            self.updated.emit(result)
        if self._on and self._session.state == "connected":
            busy = bool(self._last) and any(e.active for e in self._last)
            if self._again:
                self._again = False
                self.refresh()
            else:
                self._timer.start(self._active_ms if busy else self._idle_ms)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._timer.stop()
            self._inflight = self._again = False
            self._last = None
            self.cleared.emit()
        if self._session.state == "connected" and self._on and not self._inflight:
            self.refresh()
        elif self._session.state != "connected":
            self._timer.stop()
