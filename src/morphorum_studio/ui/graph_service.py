"""Loads the data behind the Graph page: the project list and, for one project, its details,
timeline and soundtrack, combined into a ``Graph``.

The timeline and soundtrack are best effort: a backend without them still shows the rest of the
pipeline. Answers for another project or another connection are dropped.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.assets import AssetsApi
from morphorum_studio.backend.client import BackendClient
from morphorum_studio.backend.graph import build_graph
from morphorum_studio.backend.projects import ProjectsApi
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.timeline import TimelineApi
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


def load_graph(client: BackendClient, project_id: str, with_timeline: bool):
    detail, _etag = ProjectsApi(client).open(project_id)
    timeline = soundtrack = None
    if with_timeline:
        try:
            timeline = TimelineApi(client).timeline(project_id)
        except Exception:  # The pipeline is still worth showing without schedules.
            timeline = None
    try:
        soundtrack = AssetsApi(client).soundtrack(project_id)
    except Exception:
        soundtrack = None
    return build_graph(detail, timeline, soundtrack)


class GraphService(QObject):
    projects = Signal(object)  # tuple[ProjectSummary, ...]
    loaded = Signal(object)  # Graph
    failed = Signal(str, str, str)  # operation, code, message
    busy_changed = Signal(bool)
    cleared = Signal()

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._seq = 0
        self._busy = False
        session.changed.connect(self._session_changed)

    @property
    def available(self) -> bool:
        return self._session.state == "connected" and self._session.feature("project_crud")

    @property
    def busy(self) -> bool:
        return self._busy

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._seq += 1
            self._set_busy(False)
            self.cleared.emit()

    def load_projects(self) -> None:
        client = self._session.client(timeout=10.0) if self.available else None
        if client is None:
            return
        epoch = self._session.epoch

        def done(result, error) -> None:
            if epoch != self._session.epoch:
                return
            if error:
                self.failed.emit("projects", *error)
            else:
                self.projects.emit(result)

        self._run(client, lambda c: ProjectsApi(c).list_projects(), done)

    def load(self, project_id: str) -> None:
        client = self._session.client(timeout=15.0) if self.available else None
        if client is None:
            return
        self._seq += 1
        seq, epoch = self._seq, self._session.epoch
        with_timeline = self._session.feature("timeline")
        self._set_busy(True)

        def done(result, error) -> None:
            if epoch != self._session.epoch or seq != self._seq:
                return
            self._set_busy(False)
            if error:
                self.failed.emit("graph", *error)
            else:
                self.loaded.emit(result)

        self._run(client, lambda c: load_graph(c, project_id, with_timeline), done)
