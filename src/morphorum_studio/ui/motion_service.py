"""Motion Lab loading, preview and apply (S5.1). Answers for an older project or connection are dropped."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.client import BackendClient
from morphorum_studio.backend.motion import MotionApi, MotionState, is_conflict, state_of
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.timeline import EditApi
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


class MotionService(QObject):
    loaded = Signal(object, object)  # MotionState, tuple of preset names
    previewed = Signal(object)  # MotionPreview
    applied = Signal(object)  # the saved raw project
    conflict = Signal(str)  # Apply was refused because hand-edited camera tracks would be replaced
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
        self._project_id: str | None = None
        session.changed.connect(self._session_changed)

    @property
    def available(self) -> bool:
        return self._session.state == "connected" and self._session.feature("timeline")

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def project_id(self) -> str | None:
        return self._project_id

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _stale(self, epoch: int, seq: int) -> bool:
        return (epoch != self._session.epoch or self._session.state == "offline"
                or seq != self._seq)

    def forget(self) -> None:
        self._seq += 1
        self._project_id = None
        self._set_busy(False)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self.forget()
            self.cleared.emit()

    def _start(self, operation: str, work, on_result) -> None:
        client = self._session.client(timeout=60.0) if self.available else None
        if client is None or self._project_id is None:
            return
        seq, epoch = self._seq, self._session.epoch
        self._set_busy(True)

        def done(result, error):
            if self._stale(epoch, seq):
                return
            self._set_busy(False)
            if error:
                if operation == "apply" and is_conflict(*error):
                    self.conflict.emit(error[1])
                else:
                    self.failed.emit(operation, *error)
                return
            on_result(result)

        self._run(client, work, done)

    # -- calls --------------------------------------------------------------------------

    def load(self, project_id: str) -> None:
        self.forget()
        self._project_id = project_id

        def work(c: BackendClient):
            project, _etag = EditApi(c).project_revision(project_id)
            return state_of(project), MotionApi(c).presets()

        self._start("load", work, lambda result: self.loaded.emit(*result))

    def preview(self, layers: list) -> None:
        project_id = self._project_id
        self._start("preview", lambda c: MotionApi(c).preview(project_id, layers),
                    self.previewed.emit)

    def apply(self, layers: list, rebase: bool = False) -> None:
        project_id = self._project_id

        def finished(payload):
            self.applied.emit(payload.get("project") if isinstance(payload, dict) else None)

        self._start("apply", lambda c: MotionApi(c).apply(project_id, layers, rebase), finished)


__all__ = ["MotionService", "MotionState"]
