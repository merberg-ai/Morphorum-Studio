"""Deforum settings import operations (S4.3): checkpoints, preview, create."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.api import ReadApi
from morphorum_studio.backend.client import BackendClient
from morphorum_studio.backend.deforum import DeforumApi
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


class ImportService(QObject):
    models_ready = Signal(object)  # tuple[ModelEntry]
    preview_ready = Signal(object)  # DeforumPreview
    created = Signal(object)  # DeforumCreated
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

    def _client(self, timeout: float = 30.0) -> BackendClient | None:
        return self._session.client(timeout=timeout) if self.available else None

    def _stale(self, epoch: int, seq: int) -> bool:
        return (epoch != self._session.epoch or self._session.state == "offline" or seq != self._seq)

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

    def _go(self, op: str, work, signal, timeout: float = 30.0, busy: bool = True) -> None:
        client = self._client(timeout)
        if client is None or (busy and self._busy):
            return
        self._seq += 1
        seq, epoch = self._seq, self._session.epoch
        if busy:
            self._set_busy(True)

        def done(result, error):
            if self._stale(epoch, seq):
                return
            if busy:
                self._set_busy(False)
            if error:
                self.failed.emit(op, *error)
            else:
                signal.emit(result)

        self._run(client, work, done)

    def load_models(self) -> None:
        if not self._session.feature("model_discovery"):
            return
        self._go("models", lambda c: ReadApi(c).models(kind="checkpoints"), self.models_ready, 15.0,
                 busy=False)

    def preview(self, text: str, filename: str, model_id: str | None, name: str | None) -> None:
        self._go("preview", lambda c: DeforumApi(c).preview(text, filename, model_id, name),
                 self.preview_ready)

    def create(self, text: str, filename: str, model_id: str, name: str | None) -> None:
        self._go("create", lambda c: DeforumApi(c).create(text, filename, model_id, name), self.created)
