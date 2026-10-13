"""Shared view of the one authenticated backend connection.

``ConnectionsPanel`` owns connecting, health probing and identity checks. It reports the
outcome here, so every other page reads the same state and builds its own short-lived
clients from it. There is deliberately no second connection monitor: pages only react to
``changed`` and compare ``epoch`` to discard late results.

``epoch`` increases whenever the connection identity changes (different profile, backend
installation or boot) or the connection ends. A transient outage ("reconnecting") keeps the
same epoch, so a recovered backend simply resumes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from PySide6.QtCore import QObject, Signal

from .client import BackendClient

State = Literal["offline", "connected", "reconnecting"]


@dataclass(frozen=True)
class SessionInfo:
    profile_id: str
    profile_name: str
    base_url: str
    version: str
    mode: str
    instance_id: str
    boot_id: str
    features: Mapping[str, bool] = field(default_factory=dict)

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.profile_id, self.instance_id, self.boot_id)


class BackendSession(QObject):
    changed = Signal()

    def __init__(self, parent=None, client_factory: Callable[..., BackendClient] = BackendClient):
        super().__init__(parent)
        self._factory = client_factory
        self._state: State = "offline"
        self._info: SessionInfo | None = None
        self._token: str | None = None
        self._epoch = 0

    @property
    def state(self) -> State:
        return self._state

    @property
    def info(self) -> SessionInfo | None:
        return self._info

    @property
    def epoch(self) -> int:
        return self._epoch

    def feature(self, name: str) -> bool:
        return bool(self._info and self._info.features.get(name) is True)

    def client(self, timeout: float = 6.0) -> BackendClient | None:
        """A fresh client for the live connection, or None unless fully connected."""
        if self._state != "connected" or self._info is None:
            return None
        return self._factory(self._info.base_url, self._token, timeout=timeout)

    # -- reported by ConnectionsPanel ---------------------------------------------------

    def connected(self, info: SessionInfo, token: str | None) -> None:
        previous = self._info
        if previous is None or previous.identity != info.identity:
            self._epoch += 1
        changed = self._state != "connected" or previous != info
        self._state = "connected"
        self._info = info
        self._token = token or None
        if changed:
            self.changed.emit()

    def reconnecting(self) -> None:
        if self._info is None or self._state == "reconnecting":
            return
        self._state = "reconnecting"
        self.changed.emit()

    def disconnected(self) -> None:
        if self._state == "offline" and self._info is None:
            return
        self._epoch += 1
        self._state = "offline"
        self._info = None
        self._token = None
        self.changed.emit()
