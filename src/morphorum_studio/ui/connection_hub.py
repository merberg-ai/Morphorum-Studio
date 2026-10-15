"""The Backend connection tab: choose Simple (Studio runs a local backend) or Advanced (connect to one
that is already running). Both views share one session; switching the view never disconnects."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from morphorum_studio.ui.connections_panel import ConnectionsPanel
from morphorum_studio.ui.managed_panel import ManagedPanel
from morphorum_studio.ui.preferences import StudioPreferences

SIMPLE, ADVANCED = "simple", "advanced"
MODES = (
    (SIMPLE, "Simple", "Studio runs a Morphorum backend on this PC"),
    (ADVANCED, "Advanced", "Connect to a backend that is already running"),
)


def default_mode(connections: ConnectionsPanel) -> str:
    """People who already saved a connection keep today's view; a new install starts Simple."""
    return ADVANCED if any(p.kind == "remote" for p in connections.profiles) else SIMPLE


class ConnectionHub(QWidget):
    mode_changed = Signal(str)

    def __init__(self, connections: ConnectionsPanel, managed: ManagedPanel,
                 preferences: StudioPreferences, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.connections, self.managed, self.preferences = connections, managed, preferences
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 16, 28, 0)
        outer.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, title, tip in MODES:
            button = QPushButton(title)
            button.setObjectName("segButton")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setAccessibleName(f"{title}: {tip}")
            button.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            group.addButton(button)
            row.addWidget(button)
            self.buttons[key] = button
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        row.addWidget(self.hint, 1)
        outer.addLayout(row)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.managed)
        self.stack.addWidget(self.connections)
        outer.addWidget(self.stack, 1)
        saved = preferences.ui("connection_mode")
        self.set_mode(saved if saved in (SIMPLE, ADVANCED) else default_mode(connections), remember=False)

    @property
    def mode(self) -> str:
        return ADVANCED if self.stack.currentWidget() is self.connections else SIMPLE

    def set_mode(self, mode: str, remember: bool = True) -> None:
        mode = ADVANCED if mode == ADVANCED else SIMPLE
        self.stack.setCurrentWidget(self.connections if mode == ADVANCED else self.managed)
        for key, button in self.buttons.items():
            button.setChecked(key == mode)
        self.hint.setText(next(tip for key, _t, tip in MODES if key == mode))
        if remember:
            self.preferences.set_ui("connection_mode", mode)
        self.mode_changed.emit(mode)
