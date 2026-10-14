"""A small status strip for the Studio-managed local backend, shown on Home and in the footer.

It mirrors the process state and offers Start and Stop without opening Settings. It stays hidden
until a Morphorum folder is set up for Studio to manage.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget

from morphorum_studio.backend import managed
from morphorum_studio.ui import managed_backend as mb
from morphorum_studio.ui.managed_panel import STATE_CHIP


def usable(backend: mb.ManagedBackend) -> bool:
    return bool(backend.folder) and managed.check_folder(backend.folder).ok


def summary(backend: mb.ManagedBackend) -> str:
    label, _kind = STATE_CHIP.get(backend.state, (backend.state, "idle"))
    return label


class ManagedStatusStrip(QFrame):
    """Home: 'Local backend  [Running]  detail  [Stop]'."""

    open_settings = Signal()

    def __init__(self, backend: mb.ManagedBackend, start: Callable[[], object], stop: Callable[[], object],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.backend, self._start, self._stop = backend, start, stop
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)
        title = QLabel("Local backend")
        title.setObjectName("cardTitle")
        self.chip = QLabel("")
        self.chip.setObjectName("chip")
        self.detail = QLabel("")
        self.detail.setObjectName("hint")
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.settings_button = QToolButton()
        self.settings_button.setObjectName("linkButton")
        self.settings_button.setText("Settings")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self.open_settings)
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primaryAction")
        self.start_button.clicked.connect(lambda: self._start())
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("dangerAction")
        self.stop_button.clicked.connect(lambda: self._stop())
        for button in (self.start_button, self.stop_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row.addWidget(title)
        row.addWidget(self.chip)
        row.addWidget(self.detail, 1)
        row.addWidget(self.settings_button)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        backend.state_changed.connect(lambda _s, _d: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        state = self.backend.state
        label, kind = STATE_CHIP.get(state, (state, "idle"))
        self.chip.setText(label)
        self.chip.setProperty("state", kind)
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        self.detail.setText(self.backend.detail if state not in (mb.RUNNING, mb.STOPPED) else "")
        self.setVisible(usable(self.backend))
        owned = self.backend.owned
        self.start_button.setText("Connect" if state == mb.ADOPTED else "Start")
        self.start_button.setVisible(state in (mb.STOPPED, mb.CRASHED, mb.ERROR, mb.ADOPTED))
        self.stop_button.setVisible(owned and state in (mb.STARTING, mb.RUNNING))


class ManagedStatusChip(QToolButton):
    """Footer: 'Local backend: Running'. Click to open the settings."""

    def __init__(self, backend: mb.ManagedBackend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("linkButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Open the local backend settings")
        self.backend = backend
        backend.state_changed.connect(lambda _s, _d: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        self.setVisible(usable(self.backend))
        self.setText(f"Local backend: {summary(self.backend)}")


__all__ = ["ManagedStatusChip", "ManagedStatusStrip", "summary", "usable"]
