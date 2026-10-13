"""S0 native UI shell: navigable and intentionally offline."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio import __version__
from morphorum_studio.ui.connections_panel import ConnectionsPanel
from morphorum_studio.ui.preferences import StudioPreferences
from morphorum_studio.ui.startup_settings import StartupSettingsPanel


PAGES: tuple[tuple[str, str, str], ...] = (
    (
        "Home",
        "Welcome to Morphorum Studio",
        "This is the S0 native desktop shell. Connect to a Morphorum GPU backend in S1. "
        "Model loading and media rendering stay on the backend, not this computer.",
    ),
    (
        "Connections",
        "Backend Connection Manager",
        "S1: named connection profiles, authenticated capability discovery, "
        "OS credential storage, host identity checks, and safe reconnect.",
    ),
    (
        "Projects",
        "Project Browser",
        "S2: discover remote projects, open versioned saves, and synchronize "
        "source images and soundtrack assets.",
    ),
    (
        "Image Lab",
        "Image Generation",
        "S3: select indexed models and LoRAs, submit jobs with durable idempotency "
        "keys, and view verified full-resolution results.",
    ),
    (
        "Editor",
        "Animation Timeline",
        "S4: prompts, keyframes, 2D/3D camera tracks, generation schedules, "
        "and version-safe remote project editing.",
    ),
    (
        "Motion Lab",
        "Motion and Audio",
        "S5: camera composer, easing/smoothing, audio-driven layers, "
        "preview, and recorded motion controls.",
    ),
    (
        "Render Queue",
        "Live Job Monitor",
        "S3: follow render progress, reconnect to existing jobs, "
        "download completed frames and export video with audio.",
    ),
    (
        "Console",
        "Backend Events",
        "S3: authenticated console messages, live job events, gap detection, "
        "and authoritative polling after connection loss.",
    ),
    (
        "Settings",
        "Studio Preferences",
        "S1 onward: host profiles, local cache locations, appearance, "
        "network diagnostics, and privacy controls.",
    ),
)


def _label(text: str, object_name: str | None = None) -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    if object_name:
        widget.setObjectName(object_name)
    return widget


class StudioMainWindow(QMainWindow):
    """Responsive-enough desktop-first S0 shell; all navigation works offline."""

    def __init__(self, preferences: StudioPreferences | None = None) -> None:
        super().__init__()
        self.preferences = preferences or StudioPreferences()
        self.setWindowTitle(f"Morphorum Studio | {__version__}")
        self.resize(1200, 760)
        self.setMinimumSize(880, 560)
        self.setObjectName("mainWindow")

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QFrame()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(26, 16, 26, 16)
        brand = _label("MORPHORUM  /  STUDIO", "brandName")
        top_layout.addWidget(brand)
        top_layout.addStretch()
        self.connection_status = _label("BACKEND OFFLINE", "connectionStatus")
        top_layout.addWidget(self.connection_status)
        outer.addWidget(top)

        workspace = QWidget()
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(12, 12, 12, 12)
        workspace_layout.setSpacing(12)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(190)
        sidebar.setMaximumWidth(245)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 18, 12, 16)
        sidebar_layout.setSpacing(12)
        sidebar_layout.addWidget(_label("WORKSPACES", "sidebarCaption"))

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.addItems([item[0] for item in PAGES])
        self.navigation.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sidebar_layout.addWidget(self.navigation, 1)
        sidebar_layout.addWidget(_label(f"PRE-ALPHA  {__version__}", "sidebarCaption"))
        workspace_layout.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        for page_name, title, description in PAGES:
            if page_name == "Connections":
                self.connections_panel = ConnectionsPanel()
                self.connections_panel.status_changed.connect(self.connection_status.setText)
                self.pages.addWidget(self.connections_panel)
            elif page_name == "Settings":
                self.pages.addWidget(StartupSettingsPanel(self.preferences))
            else:
                self.pages.addWidget(self._make_page(page_name, title, description))
        workspace_layout.addWidget(self.pages, 1)

        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self._remember_workspace)
        selected_id = self.preferences.profile("last_selected")
        if selected_id:
            self.connections_panel.select_by_id(selected_id)
        self.connections_panel.profile_selected.connect(
            lambda profile_id: self.preferences.set_profile("last_selected", profile_id)
        )
        self.connections_panel.connection_succeeded.connect(
            lambda profile_id: self.preferences.set_profile("last_successful", profile_id)
        )
        start_page = self.preferences.workspace() if self.preferences.enabled(
            "restore_workspace", True
        ) else "Home"
        names = [entry[0] for entry in PAGES]
        self.navigation.setCurrentRow(names.index(start_page) if start_page in names else 0)
        outer.addWidget(workspace, 1)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 9, 24, 9)
        footer_layout.addWidget(_label("Studio S1.2  •  Native remote connection manager", "footerText"))
        footer_layout.addStretch()
        footer_layout.addWidget(_label("No GPU or model downloads required", "footerText"))
        outer.addWidget(footer)
        self.preferences.restore_window(self)

    def _remember_workspace(self, index):
        if index >= 0:
            self.preferences.set_workspace(PAGES[index][0])

    def closeEvent(self, event):
        if self.preferences.enabled("restore_geometry", True):
            self.preferences.save_window(self)
        self.preferences.sync()
        self.connections_panel.disconnect()
        super().closeEvent(event)

    def _make_page(self, name: str, title: str, description: str) -> QWidget:
        page = QFrame()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 40, 38, 32)
        layout.setSpacing(18)

        layout.addWidget(_label(name.upper() + "  /  STUDIO", "sectionCaption"))
        layout.addWidget(_label(title, "pageHeading"))

        details = _label(description, "pageDescription")
        details.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(details)

        info = QFrame()
        info.setObjectName("infoPanel")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(22, 24, 22, 24)
        info_layout.setSpacing(12)
        info_layout.addWidget(_label("SCOPED FOR A LATER MILESTONE", "sectionCaption"))
        info_layout.addWidget(
            _label(
                "This panel is a placeholder, not a simulated backend feature. "
                "See docs/ROADMAP.md for implementation and physical acceptance gates.",
                "panelDescription",
            )
        )
        layout.addWidget(info)
        layout.addStretch(1)
        return page
