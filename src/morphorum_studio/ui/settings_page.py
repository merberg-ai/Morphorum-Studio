"""Settings workspace: backend connection setup and desktop preferences on one page."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from morphorum_studio.ui.backend_settings_page import BackendSettingsPage
from morphorum_studio.ui.connections_panel import ConnectionsPanel
from morphorum_studio.ui.startup_settings import StartupSettingsPanel


class SettingsPage(QWidget):
    def __init__(self, connections: ConnectionsPanel, preferences: StartupSettingsPanel,
                 backend_settings: BackendSettingsPage | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageSurface")
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 18, 24, 12)
        self.tabs = QTabWidget()
        self.tabs.addTab(connections, "Backend connection")
        self.backend_settings = backend_settings
        if backend_settings is not None:
            self.tabs.addTab(backend_settings, "Backend settings")
        self.tabs.addTab(preferences, "Desktop preferences")
        self.tabs.currentChanged.connect(self._tab_changed)
        box.addWidget(self.tabs)

    def show_connection(self) -> None:
        self.tabs.setCurrentIndex(0)

    def show_backend_settings(self) -> None:
        if self.backend_settings is not None:
            self.tabs.setCurrentWidget(self.backend_settings)

    def _tab_changed(self, index: int) -> None:
        if self.backend_settings is not None:
            self.backend_settings.set_active(self.tabs.widget(index) is self.backend_settings)
