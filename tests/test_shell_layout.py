"""Layout step 1: renamed rail, Ctrl+K palette, host chip and live footer (offscreen Qt)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QToolButton

from morphorum_studio.backend.schema import GpuDevice, Telemetry
from morphorum_studio.backend.session import SessionInfo
from morphorum_studio.ui.main_window import DISPLAY, NAV_META, PAGES, StudioMainWindow
from morphorum_studio.ui.palette import Command, CommandPalette, filter_commands
from morphorum_studio.ui.preferences import StudioPreferences


def window(tmp_path):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    prefs = StudioPreferences(QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat))
    return StudioMainWindow(preferences=prefs, journal_dir=tmp_path / "j")


def info():
    return SessionInfo("p1", "Workshop GPU", "http://10.0.0.5:7866", "0.1.0", "backend-only",
                       "i1", "b1", {"gpu_telemetry": True})


def test_filter_ranks_prefix_then_title_then_keywords_and_requires_every_word():
    run = lambda: None  # noqa: E731
    commands = [
        Command("Go to Lab", "Ctrl+3", run, keywords="image generate"),
        Command("New project", "Ctrl+N", run, keywords="create"),
        Command("Refresh this page", "F5", run, keywords="reload"),
        Command("Open project folder", "", run),
    ]
    assert [c.title for c in filter_commands(commands, "")] == [c.title for c in commands]
    titles = [c.title for c in filter_commands(commands, "project")]
    assert set(titles) == {"New project", "Open project folder"}
    assert [c.title for c in filter_commands(commands, "NEW pro")] == ["New project"]
    assert [c.title for c in filter_commands(commands, "reload")] == ["Refresh this page"]
    assert filter_commands(commands, "zzz") == []
    assert filter_commands(commands, "go lab")[0].title == "Go to Lab"


def test_palette_runs_selected_command_and_wraps_selection():
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    ran = []
    palette = CommandPalette([Command("One", "", lambda: ran.append(1)),
                              Command("Two", "", lambda: ran.append(2))])
    assert palette.visible_titles() == ["One", "Two"] and palette.results.currentRow() == 0
    palette.step_selection(-1)
    assert palette.results.currentRow() == 1
    palette.input.setText("tw")
    assert palette.visible_titles() == ["Two"]
    palette.run_selected()
    assert ran == [2]
    palette.input.setText("nothing")
    assert palette.visible_titles() == [] and not palette.empty.isHidden()
    palette.run_selected()  # nothing selected: no error
    assert ran == [2]


def test_rail_uses_the_mockup_names_but_keeps_page_keys(tmp_path):
    win = window(tmp_path)
    try:
        assert [DISPLAY[p[0]] for p in PAGES] == [
            "Home", "Library", "Lab", "Timeline", "Graph", "Queue", "Console", "Settings"]
        assert [NAV_META[p[0]][1] for p in PAGES] == [
            "Home", "Library", "Lab", "Timeline", "Graph", "Queue", "Console", "Settings"]
        tips = [b.toolTip() for b in win.navigation.findChildren(QToolButton, "railItem")]
        assert tips == [DISPLAY[p[0]] for p in PAGES]
        assert [p[0] for p in PAGES][:2] == ["Home", "Projects"]  # saved workspaces still resolve
    finally:
        win.close()


def test_ctrl_k_action_and_title_bar_button_open_the_palette(tmp_path):
    win = window(tmp_path)
    try:
        action = next(a for a in win.findChildren(QAction) if a.text() == "Command palette")
        assert action.shortcut().toString() == "Ctrl+K"
        assert win.title_bar.search_button.toolTip().endswith("(Ctrl+K)")
        titles = [c.title for c in win._commands()]
        assert "Go to Timeline" in titles and "Go to Library" in titles
        assert "New project" in titles and "Backend connection settings" in titles
        go = next(c for c in win._commands() if c.title == "Go to Console")
        go.run()
        assert win.navigation.currentRow() == [p[0] for p in PAGES].index("Console")
    finally:
        win.close()


def test_palette_new_project_switches_to_library_and_clicks_new(tmp_path):
    win = window(tmp_path)
    try:
        calls = []
        win.projects_page.new_button.click = lambda: calls.append("new")
        next(c for c in win._commands() if c.title == "New project").run()
        assert win.navigation.currentRow() == 1 and calls == ["new"]
    finally:
        win.close()


def test_host_chip_shows_profile_host_and_latency_and_clears_on_disconnect(tmp_path):
    win = window(tmp_path)
    try:
        assert win.title_bar.host_chip.isHidden()
        win.session.connected(info(), "t")
        assert win.title_bar.host_chip.text() == "Workshop GPU · 10.0.0.5:7866"
        assert not win.title_bar.host_chip.isHidden()
        win.dashboard.latency_updated.emit(23.4)
        assert win.title_bar.host_chip.text() == "Workshop GPU · 10.0.0.5:7866 · 23 ms"
        win.session.disconnected()
        assert win.title_bar.host_chip.isHidden() and win._latency_ms is None
    finally:
        win.close()


def test_footer_shows_vram_gpu_and_queue_and_resets_without_data(tmp_path):
    win = window(tmp_path)
    try:
        assert win.dashboard._watching  # telemetry keeps flowing on every page
        gpu = GpuDevice(0, "RTX", utilization_percent=71.4, memory_total_mib=16384,
                        memory_used_mib=8192)
        win._footer_telemetry(Telemetry(gpus=(gpu,)))
        assert win.footer_vram.text() == "VRAM 8.0/16.0 GiB" and win.footer_gpu.text() == "GPU 71%"
        win._footer_telemetry(Telemetry(gpus=(GpuDevice(0, "RTX"),)))
        assert win.footer_vram.text() == "VRAM —" and win.footer_gpu.text() == "GPU —"
        win._footer_telemetry(Telemetry(gpus=(gpu,)))
        win._footer_telemetry(None)
        assert win.footer_vram.text() == "VRAM —" and win.footer_gpu.text() == "GPU —"
        win._footer_queue(SimpleNamespace(final=False, status="rendering"))
        assert win.footer_queue.text() == "Queue rendering"
        win._footer_queue(SimpleNamespace(final=True, status="done"))
        assert win.footer_queue.text() == "Queue idle"
    finally:
        win.close()
