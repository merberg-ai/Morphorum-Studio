"""UI pass: shortcuts that only act on their page, remembered console view, tooltips (offscreen Qt)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.console_page import ConsolePage
from morphorum_studio.ui.console_service import ConsoleService
from morphorum_studio.ui.main_window import PAGES, StudioMainWindow
from morphorum_studio.ui.preferences import StudioPreferences


def prefs(tmp_path, name="p.ini"):
    return StudioPreferences(QSettings(str(tmp_path / name), QSettings.Format.IniFormat))


def window(tmp_path):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    return StudioMainWindow(preferences=prefs(tmp_path))


def action(win, text):
    return next(a for a in win.findChildren(QAction) if a.text() == text)


def test_page_shortcuts_only_act_on_their_own_page(tmp_path):
    win = window(tmp_path)
    try:
        names = [p[0] for p in PAGES]
        calls = []
        win.editor_page.undo_button.click = lambda: calls.append("undo")
        win.projects_page.new_button.click = lambda: calls.append("new")
        undo, new = action(win, "Undo keyframe edit"), action(win, "New project")
        assert undo.shortcut().toString() == "Ctrl+Z" and new.shortcut().toString() == "Ctrl+N"
        win.navigation.setCurrentRow(names.index("Home"))
        undo.trigger()
        new.trigger()
        assert calls == []  # not on those pages
        win.navigation.setCurrentRow(names.index("Editor"))
        undo.trigger()
        new.trigger()
        assert calls == ["undo"]
        win.navigation.setCurrentRow(names.index("Projects"))
        new.trigger()
        assert calls == ["undo", "new"]
    finally:
        win.close()


def test_redo_accepts_both_conventional_shortcuts_and_f5_refreshes_the_page(tmp_path):
    win = window(tmp_path)
    try:
        redo = action(win, "Redo keyframe edit")
        assert {s.toString() for s in redo.shortcuts()} == {"Ctrl+Shift+Z", "Ctrl+Y"}
        names = [p[0] for p in PAGES]
        calls = []
        win.editor_page.reload.click = lambda: calls.append("reload")
        win.navigation.setCurrentRow(names.index("Editor"))
        win._refresh_page()
        win.navigation.setCurrentRow(names.index("Home"))
        win._refresh_page()  # nothing to refresh on Home: no error
        assert calls == ["reload"]
        assert action(win, "Keyboard shortcuts").shortcut().toString() == "F1"
    finally:
        win.close()


def test_main_controls_have_tooltips(tmp_path):
    win = window(tmp_path)
    try:
        for widget in (win.projects_page.new_button, win.projects_page.save_button,
                       win.projects_page.models_button, win.editor_page.set_button,
                       win.editor_page.undo_button, win.editor_page.interp):
            assert widget.toolTip(), widget
    finally:
        win.close()


def test_console_view_settings_are_remembered(tmp_path):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    session = BackendSession()
    service = ConsoleService(session, spawn=lambda fn: None)
    preferences = prefs(tmp_path)
    page = ConsolePage(session, service, preferences)
    page.level.setCurrentIndex(2)  # warnings and up
    page.follow.setChecked(False)
    page.wrap.setChecked(True)
    again = ConsolePage(session, service, preferences)
    assert again.level.currentData() == "warning"
    assert not again.follow.isChecked() and again.wrap.isChecked()
    fresh = ConsolePage(session, service, prefs(tmp_path, "other.ini"))
    assert fresh.level.currentIndex() == 0 and fresh.follow.isChecked() and not fresh.wrap.isChecked()
