"""Recent projects for the Home grid: newest few projects, each with its latest render status
and a small thumbnail taken from its latest rendered frame.

There is no backend endpoint that lists jobs across projects, so this reads each recent
project's own render list (one small request each). Thumbnails are downloaded once per
(render, frame), scaled down off the GUI thread, and kept in memory; a project with no
rendered frame simply has no thumbnail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QImage

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.projects import ProjectsApi, ProjectSummary, RenderSummary
from morphorum_studio.backend.renders import ACTIVE, RenderApi
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner

RECENT_COUNT = 6
THUMB_WIDTH = 360
REFRESH_MS = 15000


@dataclass(frozen=True)
class RecentProject:
    summary: ProjectSummary
    render_id: str | None = None
    status: str | None = None  # newest render's status, None when it has never rendered
    latest_frame: int | None = None
    thumb: bytes | None = None  # PNG, already scaled


def newest_render(renders: tuple[RenderSummary, ...]) -> RenderSummary | None:
    """Newest by creation time; the backend's own order breaks ties and covers missing dates."""
    if not renders:
        return None
    return max(enumerate(renders), key=lambda p: (p[1].created_at or "", -p[0]))[1]


def latest_with_frame(renders: tuple[RenderSummary, ...]) -> RenderSummary | None:
    having = tuple(r for r in renders if r.latest_frame is not None)
    return newest_render(having)


def recent_first(projects, count: int = RECENT_COUNT):
    return tuple(sorted(projects, key=lambda p: p.updated_at or "", reverse=True))[:count]


def make_thumbnail(data: bytes, width: int = THUMB_WIDTH) -> bytes | None:
    """Scale PNG bytes to a small PNG. QImage is safe to use off the GUI thread."""
    image = QImage.fromData(data)
    if image.isNull():
        return None
    image = image.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    out = QByteArray()
    buffer = QBuffer(out)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(out)


class RecentProjectsService(QObject):
    updated = Signal(object)  # tuple[RecentProject]
    failed = Signal(str)  # error code
    cleared = Signal()

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._active = False
        self._inflight = False
        self._thumbs: dict[tuple[str, str, int], bytes] = {}
        self._last: tuple[RecentProject, ...] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        session.changed.connect(self._session_changed)

    @property
    def last(self) -> tuple[RecentProject, ...] | None:
        return self._last

    @property
    def available(self) -> bool:
        return self._session.state == "connected" and self._session.feature("project_crud")

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self.refresh()
        else:
            self._timer.stop()

    def refresh(self) -> None:
        self._timer.stop()
        if self._inflight or not self.available:
            return
        client: BackendClient | None = self._session.client(timeout=20.0)
        if client is None:
            return
        self._inflight = True
        epoch = self._session.epoch
        have = dict(self._thumbs)

        def work(c: BackendClient) -> Any:
            return load_recent(c, have)

        self._run(client, work, lambda result, error: self._done(epoch, result, error))

    # -- internals ----------------------------------------------------------------------

    def _done(self, epoch: int, result, error) -> None:
        if epoch != self._session.epoch or self._session.state == "offline":
            return
        self._inflight = False
        if error:
            self.failed.emit(error[0])
        else:
            items, fresh = result
            self._thumbs.update(fresh)
            self._last = items
            self.updated.emit(items)
        if self._active and self._session.state == "connected":
            self._timer.start(REFRESH_MS)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._timer.stop()
            self._inflight = False
            self._thumbs.clear()
            self._last = None
            self.cleared.emit()
        if self._session.state == "connected" and self._active and not self._inflight:
            self.refresh()
        elif self._session.state != "connected":
            self._timer.stop()


def load_recent(client: BackendClient, have: dict[tuple[str, str, int], bytes]):
    """Runs on a worker thread. Returns (items, newly downloaded thumbnails).

    One project's failure never hides the others: its tile just shows no status or thumbnail."""
    projects = recent_first(ProjectsApi(client).list_projects())
    renders_api = RenderApi(client)
    api = ProjectsApi(client)
    items: list[RecentProject] = []
    fresh: dict[tuple[str, str, int], bytes] = {}
    for project in projects:
        try:
            renders = api.renders(project.id)
        except BackendError:
            items.append(RecentProject(project))
            continue
        newest = newest_render(renders)
        framed = latest_with_frame(renders)
        thumb = None
        if framed is not None and framed.latest_frame is not None:
            key = (project.id, framed.id, framed.latest_frame)
            thumb = have.get(key) or fresh.get(key)
            if thumb is None:
                try:
                    thumb = make_thumbnail(
                        renders_api.frame_bytes(project.id, framed.id, framed.latest_frame))
                except (BackendError, ValueError):
                    thumb = None
                if thumb is not None:
                    fresh[key] = thumb
        items.append(RecentProject(
            project, render_id=newest.id if newest else None,
            status=newest.status if newest else None,
            latest_frame=framed.latest_frame if framed else None, thumb=thumb))
    return tuple(items), fresh


def status_chip(status: str | None) -> tuple[str, str]:
    """(label, state) for a project tile's chip; state drives the colour."""
    if status is None:
        return "Draft", "idle"
    if status in ACTIVE:
        return ("Queued" if status == "queued" else "Rendering"), "busy"
    return {
        "completed": ("Rendered", "ok"),
        "failed": ("Failed", "bad"),
        "cancelled": ("Cancelled", "idle"),
        "interrupted": ("Interrupted", "warn"),
    }.get(status, (status.replace("_", " ").capitalize(), "idle"))
