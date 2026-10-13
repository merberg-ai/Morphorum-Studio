"""Design foundation: tokens, fonts, icons, frameless shell, rail and status pill."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QToolButton

from morphorum_studio.ui.fonts import FONT_FILES, font_path, load_bundled_fonts
from morphorum_studio.ui.frameless import edges_at
from morphorum_studio.ui.icons import ICON_NAMES, pixmap
from morphorum_studio.ui.main_window import NAV_META, PAGES, StudioMainWindow
from morphorum_studio.ui.preferences import StudioPreferences
from morphorum_studio.ui.shell import ConnectionPill, asset_path
from morphorum_studio.ui.tokens import DARK, build_stylesheet


def _app():
    return QApplication.instance() or QApplication(["morphorum-studio-tests"])


def _window(tmp_path):
    _app()
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    return StudioMainWindow(preferences=StudioPreferences(settings))


def test_color_tokens_are_valid_and_distinct_surfaces():
    colors = DARK.colors()
    assert colors
    for name, value in colors.items():
        assert QColor(value).isValid(), name
    surfaces = [DARK.void, DARK.base, DARK.panel, DARK.raised, DARK.hover]
    assert len(set(surfaces)) == len(surfaces)


def test_stylesheet_is_fully_resolved_and_uses_only_supported_qss():
    css = build_stylesheet(DARK)
    assert "$" not in css
    assert "letter-spacing" not in css  # unsupported by Qt stylesheets
    assert DARK.cyan in css
    assert "qlineargradient" in css


def test_bundled_fonts_ship_with_their_licences_and_register():
    _app()
    for name in FONT_FILES:
        assert font_path(name).is_file(), name
    for licence in ("OFL-Sora.txt", "OFL-Geist.txt", "OFL-GeistMono.txt"):
        assert asset_path("fonts", licence).is_file(), licence
    families = set(load_bundled_fonts())
    assert {"Sora", "Geist", "Geist Mono"} <= families


@pytest.mark.parametrize("name", ICON_NAMES)
def test_every_icon_draws_something(name):
    _app()
    image = pixmap(name, "#ffffff", 20).toImage()
    opaque = any(
        QColor.fromRgba(image.pixel(x, y)).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    )
    assert opaque


def test_brand_assets_exist():
    assert asset_path("logo-mark.png").is_file()
    assert asset_path("app-icon.ico").is_file()


def test_edge_detection_for_frameless_resize():
    rect = QRect(0, 0, 100, 100)
    assert edges_at(rect, QPoint(50, 50)) == Qt.Edge(0)
    assert edges_at(rect, QPoint(2, 50)) == Qt.Edge.LeftEdge
    assert edges_at(rect, QPoint(97, 50)) == Qt.Edge.RightEdge
    assert edges_at(rect, QPoint(50, 1)) == Qt.Edge.TopEdge
    assert edges_at(rect, QPoint(50, 98)) == Qt.Edge.BottomEdge
    assert edges_at(rect, QPoint(2, 2)) == Qt.Edge.LeftEdge | Qt.Edge.TopEdge
    assert edges_at(rect, QPoint(98, 98)) == Qt.Edge.RightEdge | Qt.Edge.BottomEdge
    assert edges_at(rect, QPoint(-5, 50)) == Qt.Edge(0)


@pytest.mark.parametrize(
    ("text", "state"),
    [
        ("BACKEND OFFLINE", "offline"),
        ("BACKEND CONNECTING", "busy"),
        ("BACKEND RECONNECTING", "busy"),
        ("BACKEND CONNECTED", "connected"),
        ("BACKEND UNAUTHORIZED", "error"),
        ("BACKEND INCOMPATIBLE", "error"),
        ("BACKEND IDENTITY MISMATCH", "error"),
    ],
)
def test_connection_pill_states(text, state):
    assert ConnectionPill.state_for(text) == state


def test_every_workspace_has_a_rail_icon_and_label():
    assert [entry[0] for entry in PAGES] == list(NAV_META)
    for icon_name, short in NAV_META.values():
        assert icon_name in ICON_NAMES
        assert 0 < len(short) <= 8  # must fit under a 52px rail button


def test_window_is_frameless_and_controls_work(tmp_path):
    window = _window(tmp_path)
    try:
        assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
        bar = window.title_bar
        assert bar.minimize_button.accessibleName() == "Minimize"
        assert bar.close_button.accessibleName() == "Close"
        window.show()
        bar.toggle_maximized()
        assert window.isMaximized()
        assert bar.maximize_button.accessibleName() == "Restore"
        bar.toggle_maximized()
        assert not window.isMaximized()
        assert bar.maximize_button.accessibleName() == "Maximize"
    finally:
        window.close()


def test_close_button_closes_the_window(tmp_path):
    window = _window(tmp_path)
    window.show()
    assert window.isVisible()
    window.title_bar.close_button.click()
    assert not window.isVisible()


def test_rail_tracks_the_page_stack(tmp_path):
    window = _window(tmp_path)
    try:
        rail = window.navigation
        assert rail.count() == window.pages.count() == len(PAGES)
        seen = []
        rail.currentRowChanged.connect(seen.append)
        rail.setCurrentRow(3)
        assert seen == [3]
        assert window.pages.currentIndex() == 3
        assert rail.currentRow() == 3
        buttons = rail.findChildren(QToolButton, "railItem")
        assert [b.isChecked() for b in buttons].count(True) == 1
    finally:
        window.close()


def test_connection_status_updates_pill_footer_and_opens_connections(tmp_path):
    window = _window(tmp_path)
    try:
        window.connections_panel.status_changed.emit("BACKEND CONNECTED")
        assert window.connection_status.text() == "BACKEND CONNECTED"
        assert window.connection_status.property("state") == "connected"
        assert window.footer_status.text() == "BACKEND CONNECTED"
        window.navigation.setCurrentRow(0)
        window.connection_status.click()
        assert window.navigation.currentRow() == [p[0] for p in PAGES].index("Connections")
    finally:
        window.close()


def test_view_menu_switches_workspaces(tmp_path):
    window = _window(tmp_path)
    try:
        menus = {
            b.text(): b.menu() for b in window.title_bar.findChildren(QToolButton, "menuButton")
        }
        assert set(menus) == {"File", "View", "Help"}
        actions = menus["View"].actions()
        assert [a.text() for a in actions] == [p[0] for p in PAGES]
        actions[4].trigger()
        assert window.navigation.currentRow() == 4
    finally:
        window.close()
