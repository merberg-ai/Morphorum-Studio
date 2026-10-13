"""Studio main window: frameless shell with title bar, icon rail, pages and status bar."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio import __version__
from morphorum_studio.backend.images import SubmissionJournal
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui import frameless
from morphorum_studio.ui.connections_panel import ConnectionsPanel
from morphorum_studio.ui.dashboard_service import DashboardService
from morphorum_studio.ui.home_page import HomePage
from morphorum_studio.ui.image_lab_page import ImageLabPage
from morphorum_studio.ui.image_service import ImageLabService
from morphorum_studio.ui.preferences import StudioPreferences
from morphorum_studio.ui.projects_page import ProjectsPage
from morphorum_studio.ui.render_service import RenderService
from morphorum_studio.ui.video_service import VideoService
from morphorum_studio.ui.console_service import ConsoleService
from morphorum_studio.ui.console_page import ConsolePage
from morphorum_studio.ui.projects_service import ProjectsService
from morphorum_studio.ui.shell import NavRail, TitleBar
from morphorum_studio.ui.startup_settings import StartupSettingsPanel


PAGES: tuple[tuple[str, str, str], ...] = (
    (
        "Home",
        "Welcome to Morphorum Studio",
        "Connect to a Morphorum GPU backend from Connections. Model loading and "
        "media rendering stay on the backend, not this computer. The live dashboard "
        "arrives in S2.1.",
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
        "Live backend log with level and category filters, search, follow, "
        "copy and save; gaps and restarts are reported, never hidden.",
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



# Rail icon and short label per workspace (full names appear as tooltips).
NAV_META: dict[str, tuple[str, str]] = {
    "Home": ("home", "Home"),
    "Connections": ("plug", "Connect"),
    "Projects": ("library", "Projects"),
    "Image Lab": ("sparkle", "Image"),
    "Editor": ("timeline", "Editor"),
    "Motion Lab": ("graph", "Motion"),
    "Render Queue": ("queue", "Queue"),
    "Console": ("console", "Console"),
    "Settings": ("settings", "Settings"),
}

def _label(text: str, object_name: str | None = None) -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    if object_name:
        widget.setObjectName(object_name)
    return widget


class StudioMainWindow(QMainWindow):
    """Frameless desktop shell; all navigation works offline."""

    def __init__(self, preferences: StudioPreferences | None = None,
                 journal_dir: str | os.PathLike | None = None) -> None:
        super().__init__()
        self.preferences = preferences or StudioPreferences()
        self.setWindowTitle(f"Morphorum Studio | {__version__}")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.resize(1200, 760)
        self.setMinimumSize(880, 560)
        self.setObjectName("mainWindow")

        shell = QWidget()
        shell.setObjectName("shell")
        shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(shell)
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self)
        self.connection_status = self.title_bar.connection_pill
        outer.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        names = [entry[0] for entry in PAGES]
        self.navigation = NavRail(
            [(name, NAV_META[name][1], NAV_META[name][0]) for name in names],
            footer_from=names.index("Settings"),
        )
        body_layout.addWidget(self.navigation)

        self.session = BackendSession(self)
        self.dashboard = DashboardService(self.session, self)
        self.projects_service = ProjectsService(self.session, self)
        if journal_dir is None:
            journal_dir = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation)) / "submissions"
        self.journal = SubmissionJournal(journal_dir)
        self.image_service = ImageLabService(self.session, self.journal, self)
        self.render_service = RenderService(self.session, self.journal, self)
        self.video_service = VideoService(
            self.session, self.journal,
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
            / "video-playback", self)
        self.console_service = ConsoleService(self.session, self)
        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        for page_name, title, description in PAGES:
            if page_name == "Home":
                self.home_page = HomePage(self.session, self.dashboard)
                self.home_page.open_connections.connect(
                    lambda: self.navigation.setCurrentRow(names.index("Connections"))
                )
                self.pages.addWidget(self.home_page)
            elif page_name == "Projects":
                self.projects_page = ProjectsPage(
                    self.session, self.projects_service, self.preferences, self.render_service,
                    self.video_service,
                )
                self.projects_page.open_connections.connect(
                    lambda: self.navigation.setCurrentRow(names.index("Connections"))
                )
                self.pages.addWidget(self.projects_page)
            elif page_name == "Image Lab":
                self.image_lab_page = ImageLabPage(self.session, self.image_service, self.preferences)
                self.image_lab_page.open_connections.connect(
                    lambda: self.navigation.setCurrentRow(names.index("Connections"))
                )
                self.pages.addWidget(self.image_lab_page)
            elif page_name == "Console":
                self.console_page = ConsolePage(self.session, self.console_service)
                self.pages.addWidget(self.console_page)
            elif page_name == "Connections":
                self.connections_panel = ConnectionsPanel(
                    preferences=self.preferences, session=self.session
                )
                self.connections_panel.status_changed.connect(self._on_connection_status)
                self.pages.addWidget(self.connections_panel)
            elif page_name == "Settings":
                self.pages.addWidget(StartupSettingsPanel(self.preferences))
            else:
                self.pages.addWidget(self._make_page(page_name, title, description))
        body_layout.addWidget(self.pages, 1)
        outer.addWidget(body, 1)

        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self._remember_workspace)
        self.navigation.currentRowChanged.connect(
            lambda row: self.dashboard.set_active(row == names.index("Home"))
        )
        self.navigation.currentRowChanged.connect(
            lambda row: self.projects_page.set_active(row == names.index("Projects"))
        )
        self.navigation.currentRowChanged.connect(
            lambda row: self.image_lab_page.set_active(row == names.index("Image Lab"))
        )
        self.connection_status.clicked.connect(
            lambda *_: self.navigation.setCurrentRow(names.index("Connections"))
        )
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
        self.navigation.setCurrentRow(names.index(start_page) if start_page in names else 0)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 5, 14, 5)
        footer_layout.setSpacing(18)
        footer_layout.addWidget(_label(f"Studio {__version__}", "footerText"))
        footer_layout.addWidget(_label("Native remote connection manager", "footerText"))
        footer_layout.addStretch()
        self.footer_status = _label("BACKEND OFFLINE", "footerText")
        footer_layout.addWidget(self.footer_status)
        outer.addWidget(footer)

        self._build_menus(names)
        self.title_bar.sync_window_state()
        frameless.enable_mouse_tracking(self)
        self._edge_resizer = frameless.EdgeResizer(self)
        self.preferences.restore_window(self)
        if self.preferences.enabled("auto_connect", False):
            QTimer.singleShot(0, self._startup_connect)

    def _build_menus(self, names: list[str]) -> None:
        quit_action = QAction("Quit Morphorum Studio", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)
        self.title_bar.add_menu("File", [quit_action])

        view_actions: list[QAction | None] = []
        for index, name in enumerate(names):
            action = QAction(name, self)
            if index < 9:
                action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.triggered.connect(lambda _checked=False, row=index: self.navigation.setCurrentRow(row))
            self.addAction(action)
            view_actions.append(action)
        self.title_bar.add_menu("View", view_actions)

        about = QAction("About Morphorum Studio", self)
        about.triggered.connect(self._show_about)
        self.title_bar.add_menu("Help", [about])

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Morphorum Studio",
            f"Morphorum Studio {__version__}\n\n"
            "Native desktop client for Morphorum GPU backends.\n"
            "Rendering and models run on the backend, not this computer.",
        )

    def _on_connection_status(self, text: str) -> None:
        self.connection_status.set_status(text)
        self.footer_status.setText(text)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if hasattr(self, "title_bar"):
            self.title_bar.sync_window_state()

    def _startup_connect(self):
        profile_id = self.preferences.profile("last_successful")
        if profile_id:
            self.connections_panel.auto_connect(profile_id)

    def _remember_workspace(self, index):
        if index >= 0:
            self.preferences.set_workspace(PAGES[index][0])

    def closeEvent(self, event):
        if self.projects_page.has_unsaved_changes() and not self._confirm_discard():
            event.ignore()
            return
        if self.preferences.enabled("restore_geometry", True):
            self.preferences.save_window(self)
        self.preferences.sync()
        self.console_service.stop()
        self.dashboard.set_active(False)
        self.connections_panel.disconnect()
        super().closeEvent(event)

    def _confirm_discard(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved project changes")
        box.setText("The open project has changes that have not been saved to the backend.")
        discard = box.addButton("Discard and close", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Keep editing", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is discard

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
