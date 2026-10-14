"""Layout step 3: Library tabs, responsive project grid, model and LoRA grids (offscreen Qt)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from morphorum_studio.backend.projects import ProjectSummary
from morphorum_studio.backend.schema import ModelEntry
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.library_views import FlowGrid, ModelGrid, ProjectGrid, columns_for
from morphorum_studio.ui.preferences import StudioPreferences
from morphorum_studio.ui.projects_page import ProjectsPage
from morphorum_studio.ui.projects_service import ProjectsService
from morphorum_studio.ui.recent_service import RecentProject, RecentProjectsService
from morphorum_studio.ui.setup_service import ModelsService
from fakes import info
from test_projects_ui import Client, Store, sync_runner

FEATURES = {"project_crud": True, "model_discovery": True}

QApplication.instance() or QApplication(["morphorum-studio-tests"])


def test_columns_fit_the_width_and_stay_in_range():
    assert columns_for(0) == 1 and columns_for(200) == 1
    assert columns_for(270) == 1 and columns_for(554) == 2 and columns_for(837) == 2
    assert columns_for(838) == 3
    assert columns_for(5000) == 5


def projects(n):
    return tuple(RecentProject(ProjectSummary(f"p{i}", f"Project {i}", f"2026-10-{i + 1:02d}"),
                               status="completed" if i % 2 else None) for i in range(n))


def test_flow_grid_replaces_and_reflows_widgets():
    from PySide6.QtWidgets import QLabel
    flow = FlowGrid()
    flow.resize(900, 400)
    flow.show()
    flow.set_widgets([QLabel(str(i)) for i in range(7)])
    assert len(flow.widgets) == 7 and flow.columns() == columns_for(flow.viewport().width())
    first = flow.widgets
    flow.set_widgets([QLabel("only")])
    assert len(flow.widgets) == 1 and flow.widgets[0] is not first[0]
    flow.set_widgets([])
    assert flow.widgets == []
    flow.close()


def test_project_grid_filters_and_reports_empty_states():
    grid = ProjectGrid()
    opened = []
    grid.opened.connect(opened.append)
    grid.set_items(())
    assert "No projects" in grid.note.text() and grid.tiles == []
    grid.set_items(projects(4))
    assert len(grid.tiles) == 4 and grid.note.isHidden()
    assert [t.chip.text() for t in grid.tiles] == ["Draft", "Rendered", "Draft", "Rendered"]
    grid.apply_filter("project 2")
    assert [t.project_id for t in grid.tiles] == ["p2"]
    grid.apply_filter("zzz")
    assert grid.tiles == [] and "No project matches" in grid.note.text()
    grid.apply_filter("")
    grid.tiles[1].clicked.emit("p1")
    assert opened == ["p1"]
    grid.show_message("Connect first")
    assert grid.tiles == [] and grid.note.text() == "Connect first"


def entries():
    return (ModelEntry("a" * 24, "sdxl", "loras", "Fox Style", "fox.safetensors", 1536, "base"),
            ModelEntry("b" * 24, "flux", "loras", "Ink Wash"),
            ModelEntry("c" * 24, "sdxl", "loras", "Cat Lines"))


def test_model_grid_filters_by_family_and_search_and_only_loras_inspect():
    grid = ModelGrid("LoRAs", inspectable=True)
    asked = []
    grid.inspect_requested.connect(asked.append)
    grid.set_entries(entries())
    assert len(grid.cards) == 3 and "3 of 3 shown" in grid.note.text()
    assert [grid.family.itemText(i) for i in range(grid.family.count())] == [
        "All families", "flux", "sdxl"]
    grid.family.setCurrentIndex(grid.family.findData("sdxl"))
    assert sorted(c.name.text() for c in grid.cards) == ["Cat Lines", "Fox Style"]
    grid.search.setText("fox")
    assert [c.name.text() for c in grid.cards] == ["Fox Style"]
    assert grid.cards[0].meta.text() == "1.5 KiB" and grid.cards[0].toolTip() == "fox.safetensors"
    grid.cards[0].clicked.emit(grid.cards[0].model_id)
    assert asked == ["a" * 24]
    grid.search.setText("nothing")
    assert grid.cards == [] and "no loras match" in grid.note.text().lower()
    grid.family.setCurrentIndex(0)
    grid.search.clear()
    plain = ModelGrid("Models", inspectable=False)
    plain.set_entries(entries()[:1])
    assert "Select one" not in plain.note.text() and plain.cards[0]._clickable is False
    plain.set_entries(())
    assert "No models are indexed" in plain.note.text()


# ----------------------------------------------------------------------------- the page

def rig(tmp_path):
    store = Store()
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(store))
    service = ProjectsService(session, runner=sync_runner)
    library = RecentProjectsService(session, runner=sync_runner, count=24)
    models = ModelsService(session, runner=sync_runner)
    prefs = StudioPreferences(QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat))
    page = ProjectsPage(session, service, prefs, models_service=models, library_service=library)
    return store, session, page, library, models


def test_page_starts_on_the_grid_and_a_tile_opens_the_detail_view(tmp_path):
    store, session, page, library, models = rig(tmp_path)
    session.connected(info(features=FEATURES), "tok")
    page.set_active(True)
    assert page.projects_stack.currentIndex() == 0 and page.back_button.isHidden()
    assert sorted(t.project_id for t in page.project_grid.tiles) == ["alpha", "beta"]
    page.project_grid.tiles[0].clicked.emit("alpha")
    assert page.projects_stack.currentIndex() == 1 and not page.back_button.isHidden()
    assert page._selected == "alpha"
    page.back_button.click()
    assert page.projects_stack.currentIndex() == 0 and page.back_button.isHidden()


def test_unsaved_edits_keep_you_in_the_detail_view_when_a_tile_is_refused(tmp_path, monkeypatch):
    store, session, page, library, models = rig(tmp_path)
    session.connected(info(features=FEATURES), "tok")
    page.set_active(True)
    page.open_project("alpha")
    page.name_edit.setText("Changed")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    page.back_button.click()
    page.project_grid.tiles[0].clicked.emit("beta")  # refused by the prompt
    assert page._selected == "alpha" and page.projects_stack.currentIndex() == 0


def test_open_project_from_home_shows_detail_and_new_project_does_too(tmp_path):
    store, session, page, library, models = rig(tmp_path)
    session.connected(info(features=FEATURES), "tok")
    page.set_active(True)
    page.open_project("beta")
    assert page.projects_stack.currentIndex() == 1 and page._selected == "beta"
    page.show_grid()
    page._created(type("D", (), {"id": "alpha"})())
    assert page.projects_stack.currentIndex() == 1


def test_models_and_lora_tabs_load_lazily_once_and_reset_on_a_new_connection(tmp_path):
    store, session, page, library, models = rig(tmp_path)
    loads = []
    models.load = lambda: loads.append(1)
    session.connected(info(features=FEATURES), "tok")
    page.set_active(True)
    assert loads == []  # Projects tab is showing
    page.tab_buttons["models"].click()
    assert page.library_stack.currentIndex() == 1 and loads == [1]
    page.tab_buttons["loras"].click()
    assert page.library_stack.currentIndex() == 2 and loads == [1, 1]  # nothing loaded yet
    models.library_ready.emit((entries()[2],), entries()[:2])
    assert len(page.model_grid.cards) == 1 and len(page.lora_grid.cards) == 2
    page.tab_buttons["models"].click()
    assert loads == [1, 1]  # already loaded: no refetch
    assert page.tab_buttons["models"].isChecked() and not page.tab_buttons["loras"].isChecked()
    session.connected(info(features=FEATURES, boot="other"), "tok")
    assert page.model_grid.cards == [] and not page._models_loaded
    page.tab_buttons["projects"].click()
    assert page.library_stack.currentIndex() == 0


def test_without_model_discovery_the_tabs_say_so(tmp_path):
    store, session, page, library, models = rig(tmp_path)
    session.connected(info(features={"project_crud": True}), "tok")
    page.set_active(True)
    page.tab_buttons["loras"].click()
    assert "model discovery" in page.lora_grid.note.text()


def test_clicking_a_lora_opens_the_inspector_on_it(tmp_path):
    store, session, page, library, models = rig(tmp_path)
    session.connected(info(features=FEATURES), "tok")
    opened = []
    page._open_models = lambda: opened.append(1) or setattr(
        page, "models_dialog", type("Dlg", (), {"select_lora": lambda self, i: opened.append(i)})())
    page._inspect_lora("x" * 24)
    assert opened == [1, "x" * 24]


@pytest.mark.parametrize("action", ["grid_new_button", "grid_refresh_button"])
def test_grid_toolbar_buttons_forward_to_the_existing_actions(tmp_path, action):
    store, session, page, library, models = rig(tmp_path)
    calls = []
    page.new_button.click = lambda: calls.append("new")
    page.refresh_button.click = lambda: calls.append("refresh")
    getattr(page, action).click()
    assert calls == [{"grid_new_button": "new", "grid_refresh_button": "refresh"}[action]]
