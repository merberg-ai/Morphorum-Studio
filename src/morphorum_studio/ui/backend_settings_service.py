"""Loads, saves, checks and rescans the connected backend's settings off the GUI thread.

An answer that arrives after the connection changed is dropped.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.backend_settings import SettingsApi
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


class BackendSettingsService(QObject):
    loaded = Signal(object)  # BackendSettings
    saved = Signal(object)  # BackendSettings
    checked = Signal(str, object)  # path as asked, PathCheck
    scanned = Signal(object, object)  # models found (int | None), warnings (tuple)
    failed = Signal(str, str, str)  # operation, code, message
    busy_changed = Signal(bool)
    cleared = Signal()

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._pending = 0
        session.changed.connect(self._session_changed)

    @property
    def available(self) -> bool:
        return self._session.state == "connected"

    @property
    def busy(self) -> bool:
        return self._pending > 0

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._pending = 0
            self.busy_changed.emit(False)
            self.cleared.emit()

    def _call(self, name: str, work, deliver, timeout: float = 15.0) -> None:
        client = self._session.client(timeout=timeout) if self.available else None
        if client is None:
            return
        epoch = self._session.epoch
        self._pending += 1
        if self._pending == 1:
            self.busy_changed.emit(True)

        def done(result, error) -> None:
            if epoch != self._session.epoch:
                return
            self._pending = max(0, self._pending - 1)
            if self._pending == 0:
                self.busy_changed.emit(False)
            if error:
                self.failed.emit(name, *error)
            else:
                deliver(result)

        self._run(client, lambda c: work(SettingsApi(c)), done)

    def load(self) -> None:
        self._call("load", lambda api: api.load(), self.loaded.emit)

    def save(self, update: dict) -> None:
        self._call("save", lambda api: api.save(update), self.saved.emit)

    def check(self, path: str) -> None:
        self._call("check", lambda api: (path, api.check_path(path)), lambda r: self.checked.emit(*r))

    def rescan(self) -> None:
        self._call("rescan", lambda api: api.rescan(), lambda r: self.scanned.emit(*r), timeout=120.0)
