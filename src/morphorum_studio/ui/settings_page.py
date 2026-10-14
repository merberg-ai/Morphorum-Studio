"""Settings workspace: backend connection setup and desktop preferences on one page."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from morphorum_studio.ui.connections_panel import ConnectionsPanel
from morphorum_studio.ui.startup_settings import StartupSettingsPanel


class SettingsPage(QWidget):
    def __init__(self, connections: ConnectionsPanel, preferences: StartupSettingsPanel,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageSurface")
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 18, 24, 12)
        self.tabs = QTabWidget()
        self.tabs.addTab(connections, "Backend connection")
        self.tabs.addTab(preferences, "Desktop preferences")
        box.addWidget(self.tabs)

    def show_connection(self) -> None:
        self.tabs.setCurrentIndex(0)
