"""Project operations for the Projects page (S2.2). One request per kind at a time, off the GUI
thread, with results from an older connection (``epoch``) discarded. Nothing here polls: the
list refreshes when the page asks (visible, connected, Refresh, after a change)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.assets import Asset, AssetsApi
from morphorum_studio.backend.client import BackendClient
from morphorum_studio.backend.projects import ProjectsApi, RenderSummary
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


class ProjectsService(QObject):
    listed = Signal(object)  # tuple[ProjectSummary, ...]
    opened = Signal(object, str, object)  # ProjectDetail, etag, tuple[RenderSummary, ...] | None
    created = Signal(object)  # ProjectDetail
    saved = Signal(object, str)  # ProjectDetail, new etag
    trashed = Signal(str)  # project id
    failed = Signal(str, str, str)  # operation, error code, message
    assets_loaded = Signal(str, object, object)  # project id, tuple[Asset], Soundtrack | None
    preview_loaded = Signal(str, object)  # project id, image bytes | None
    asset_changed = Signal(str, str, object)  # operation, project id, Soundtrack | None
    copy_saved = Signal(str)  # final path
    busy_changed = Signal(bool)
    peeked = Signal(str, object)  # project id, ProjectDetail | None (conflict comparison)
    cleared = Signal()

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._listing = False
        self._open_seq = 0
        self._mutating = False
        self._assets_seq = 0
        self._peek_seq = 0
        self._preview_seq = 0
        self._copying = False
        session.changed.connect(self._session_changed)

    # -- state --------------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Connected to a backend that advertises project support."""
        return self._session.state == "connected" and self._session.feature("project_crud")

    @property
    def mutating(self) -> bool:
        return self._mutating

    @property
    def copying(self) -> bool:
        return self._copying

    def _client(self, timeout: float = 10.0) -> BackendClient | None:
        return self._session.client(timeout=timeout) if self.available else None

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._listing = False
            self._open_seq += 1
            self._assets_seq += 1
            self._preview_seq += 1
            self._peek_seq += 1
            self._copying = False
            if self._mutating:
                self._mutating = False
                self.busy_changed.emit(False)
            self.cleared.emit()

    def _stale(self, epoch: int) -> bool:
        return epoch != self._session.epoch or self._session.state == "offline"

    # -- reads --------------------------------------------------------------------------

    def refresh(self) -> None:
        client = self._client()
        if client is None or self._listing:
            return
        self._listing = True
        epoch = self._session.epoch
        self._run(client, lambda c: ProjectsApi(c).list_projects(),
                  lambda result, error: self._listed(epoch, result, error))

    def _listed(self, epoch: int, result, error) -> None:
        if self._stale(epoch):
            return
        self._listing = False
        if error:
            self.failed.emit("list", *error)
        else:
            self.listed.emit(result)

    def open(self, project_id: str) -> None:
        client = self._client()
        if client is None:
            return
        self._open_seq += 1
        seq, epoch = self._open_seq, self._session.epoch

        def work(c: BackendClient):
            api = ProjectsApi(c)
            detail, etag = api.open(project_id)
            try:
                renders: tuple[RenderSummary, ...] | None = api.renders(project_id)
            except Exception:  # Render history is a nicety; the project itself opened.
                renders = None
            return detail, etag, renders

        self._run(client, work, lambda result, error: self._opened(epoch, seq, result, error))

    def _opened(self, epoch: int, seq: int, result, error) -> None:
        if self._stale(epoch) or seq != self._open_seq:
            return  # Superseded by a newer selection or another connection.
        if error:
            self.failed.emit("open", *error)
        else:
            detail, etag, renders = result
            self.opened.emit(detail, etag, renders)

    def peek(self, project_id: str) -> None:
        """Read the backend's current version without touching the open form (conflict compare)."""
        client = self._client()
        if client is None:
            self.peeked.emit(project_id, None)
            return
        self._peek_seq += 1
        seq, epoch = self._peek_seq, self._session.epoch

        def done(result, error):
            if self._stale(epoch) or seq != self._peek_seq:
                return
            self.peeked.emit(project_id, None if error else result[0])

        self._run(client, lambda c: ProjectsApi(c).open(project_id), done)

    # -- writes (one at a time, never retried) -------------------------------------------

    def create(self, name: str) -> None:
        self._mutate("create", lambda c: ProjectsApi(c).create(name))

    def save(self, project_id: str, etag: str, name: str, notes: str) -> None:
        self._mutate("save", lambda c: ProjectsApi(c).save(project_id, etag, name, notes))

    def set_start_mode(self, project_id: str, mode: str) -> None:
        def work(c: BackendClient):
            ProjectsApi(c).set_start_mode(project_id, mode)
            return "start_mode", project_id, None
        self._mutate("start_mode", work)

    def trash(self, project_id: str) -> None:
        self._mutate("trash", lambda c: (ProjectsApi(c).trash(project_id), project_id)[1])

    # -- assets (S2.3) --------------------------------------------------------------------

    def load_assets(self, project_id: str) -> None:
        client = self._client()
        if client is None:
            return
        self._assets_seq += 1
        seq, epoch = self._assets_seq, self._session.epoch

        def work(c: BackendClient):
            api = AssetsApi(c)
            return api.catalogue(project_id), api.soundtrack(project_id)

        def done(result, error):
            if self._stale(epoch) or seq != self._assets_seq:
                return
            if error:
                self.failed.emit("assets", *error)
            else:
                self.assets_loaded.emit(project_id, *result)

        self._run(client, work, done)

    def load_preview(self, project_id: str, asset: Asset) -> None:
        client = self._client(30.0)
        if client is None:
            return
        self._preview_seq += 1
        seq, epoch = self._preview_seq, self._session.epoch

        def done(result, error):
            if self._stale(epoch) or seq != self._preview_seq:
                return
            if error:
                self.preview_loaded.emit(project_id, None)  # A missing thumbnail is not an error.
            else:
                self.preview_loaded.emit(project_id, result)

        self._run(client, lambda c: AssetsApi(c).preview_source(project_id, asset), done)

    def upload_source(self, project_id: str, path: str) -> None:
        self._mutate("source_upload", lambda c: (AssetsApi(c).upload_source(project_id, path), project_id, None),
                     timeout=60.0)

    def clear_source(self, project_id: str) -> None:
        self._mutate("source_clear", lambda c: (AssetsApi(c).clear_source(project_id), project_id, None))

    def attach_soundtrack(self, project_id: str, path: str, offset: float) -> None:
        self._mutate("audio_attach", lambda c: (None, project_id,
                     AssetsApi(c).attach_soundtrack(project_id, path, offset)), timeout=60.0)

    def set_offset(self, project_id: str, offset: float) -> None:
        self._mutate("audio_offset", lambda c: (None, project_id, AssetsApi(c).set_offset(project_id, offset)))

    def save_copy(self, project_id: str, asset: Asset, destination: str) -> None:
        client = self._client(60.0)
        if client is None or self._copying:
            return
        self._copying = True
        self.busy_changed.emit(self._mutating)
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            self._copying = False
            self.busy_changed.emit(self._mutating)
            if error:
                self.failed.emit("copy", *error)
            else:
                self.copy_saved.emit(result)

        self._run(client, lambda c: AssetsApi(c).save_copy(project_id, asset, destination), done)

    # -- shared mutation plumbing ---------------------------------------------------------

    def _mutate(self, kind: str, fn: Callable[[BackendClient], Any], timeout: float = 10.0) -> None:
        client = self._client(timeout)
        if client is None or self._mutating:
            return
        self._mutating = True
        self.busy_changed.emit(True)
        epoch = self._session.epoch
        self._run(client, fn, lambda result, error: self._mutated(epoch, kind, result, error))

    def _mutated(self, epoch: int, kind: str, result, error) -> None:
        if self._stale(epoch):
            return
        self._mutating = False
        self.busy_changed.emit(False)
        if error:
            self.failed.emit(kind, *error)
            return
        if kind == "create":
            self.created.emit(result)
        elif kind == "save":
            self.saved.emit(*result)
        elif kind == "trash":
            self.trashed.emit(result)
        else:
            _, project_id, soundtrack = result
            self.asset_changed.emit(kind, project_id, soundtrack)
