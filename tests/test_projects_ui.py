"""Projects service and page against an in-memory fake backend (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.preferences import StudioPreferences
from morphorum_studio.ui.projects_page import ProjectsPage, format_length, format_size, format_when
from morphorum_studio.ui.projects_service import ProjectsService

FEATURES = {"project_crud": True}


def etag(n):
    return '"' + format(n, "x").rjust(64, "0") + '"'


class Store:
    """Backend state shared by every client the session hands out."""

    def __init__(self):
        self.projects = {
            "alpha": {"name": "Alpha", "notes": "a", "rev": 1},
            "beta": {"name": "Beta", "notes": "", "rev": 1},
        }
        self.calls = []
        self.fail = {}

    def project(self, pid):
        p = self.projects[pid]
        return {"project": {"id": pid, "name": p["name"], "notes": p["notes"],
                            "animation": {"width": 512, "height": 512, "fps": 12, "max_frames": 24}}}


class Client:
    def __init__(self, store):
        self.s = store

    def _maybe_fail(self, op):
        if op in self.s.fail:
            raise self.s.fail[op]

    def get_json(self, path, params=None):
        self.s.calls.append(("GET", path))
        self._maybe_fail("get")
        if path == "/api/animation/projects":
            return {"projects": [{"id": k, "name": v["name"]} for k, v in self.s.projects.items()]}
        if path.endswith("/renders"):
            return {"renders": []}
        raise BackendError("NOT_FOUND", "no", 404)

    def get_json_etag(self, path, params=None):
        self.s.calls.append(("GET", path))
        self._maybe_fail("open")
        pid = path.rsplit("/", 1)[1]
        if pid not in self.s.projects:
            raise BackendError("NOT_FOUND", "gone", 404)
        return self.s.project(pid), etag(self.s.projects[pid]["rev"])

    def send_json(self, method, path, body=None, *, if_match=None):
        self.s.calls.append((method, path, body, if_match))
        self._maybe_fail(method)
        if method == "POST":
            pid = body["name"].lower().replace(" ", "-")
            self.s.projects[pid] = {"name": body["name"], "notes": "", "rev": 1}
            return self.s.project(pid), etag(1)
        pid = path.rsplit("/", 1)[1]
        if method == "DELETE":
            del self.s.projects[pid]
            return {"ok": True}, None
        p = self.s.projects[pid]
        if if_match != etag(p["rev"]):
            raise BackendError("PRECONDITION_FAILED", "Project changed", 412)
        p.update(body)
        p["rev"] += 1
        return self.s.project(pid), etag(p["rev"])


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


class Deferred:
    def __init__(self):
        self.pending = []

    def __call__(self, client, fn, callback):
        self.pending.append((client, fn, callback))

    def complete(self, index=None):
        batch = self.pending if index is None else [self.pending[index]]
        self.pending = [p for p in self.pending if p not in batch]
        for client, fn, callback in batch:
            sync_runner(client, fn, callback)


def make(tmp_path, runner=sync_runner, features=FEATURES, connect=True, with_page=True):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    store = Store()
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(store))
    service = ProjectsService(session, runner=runner)
    prefs = StudioPreferences(QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat))
    page = ProjectsPage(session, service, prefs) if with_page else None
    if connect:
        session.connected(info(features=features), "tok")
    return store, session, service, prefs, page


def answer(monkeypatch, question=QMessageBox.StandardButton.Discard):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[1]) or question)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: asked.append(("warn", a[1], a[2])))
    return asked


# ----------------------------------------------------------------------------- service

def test_service_unavailable_without_feature(tmp_path):
    store, session, service, *_ = make(tmp_path, features={}, with_page=False)
    assert not service.available
    service.refresh()
    service.create("x")
    assert store.calls == []


def test_service_lists_opens_and_saves(tmp_path):
    store, session, service, *_ = make(tmp_path, with_page=False)
    listed, opened, saved = [], [], []
    service.listed.connect(listed.append)
    service.opened.connect(lambda d, e, r: opened.append((d, e, r)))
    service.saved.connect(lambda d, e: saved.append((d, e)))
    service.refresh()
    assert [p.id for p in listed[0]] == ["alpha", "beta"]
    service.open("alpha")
    detail, tag, renders = opened[0]
    assert detail.name == "Alpha" and tag == etag(1) and renders == ()
    service.save("alpha", tag, "Alpha 2", "n")
    assert saved[0][1] == etag(2) and store.projects["alpha"]["name"] == "Alpha 2"
    put = [c for c in store.calls if c[0] == "PUT"][0]
    assert put[2] == {"name": "Alpha 2", "notes": "n"} and put[3] == etag(1)


def test_renders_failure_does_not_block_open(tmp_path):
    store, session, service, *_ = make(tmp_path, with_page=False)
    opened = []
    service.opened.connect(lambda d, e, r: opened.append(r))
    original = Client.get_json
    Client.get_json = lambda self, path, params=None: (_ for _ in ()).throw(BackendError("X", "x"))
    try:
        service.open("alpha")
    finally:
        Client.get_json = original
    assert opened == [None]


def test_stale_open_is_dropped(tmp_path):
    runner = Deferred()
    store, session, service, *_ = make(tmp_path, runner=runner, with_page=False)
    opened = []
    service.opened.connect(lambda d, e, r: opened.append(d.id))
    service.open("alpha")
    service.open("beta")
    runner.complete()
    assert opened == ["beta"]


def test_epoch_change_drops_results_and_clears(tmp_path):
    runner = Deferred()
    store, session, service, *_ = make(tmp_path, runner=runner, with_page=False)
    listed, cleared = [], []
    service.listed.connect(listed.append)
    service.cleared.connect(lambda: cleared.append(1))
    service.refresh()
    session.disconnected()
    runner.complete()
    assert listed == [] and cleared


def test_one_mutation_at_a_time(tmp_path):
    runner = Deferred()
    store, session, service, *_ = make(tmp_path, runner=runner, with_page=False)
    busy = []
    service.busy_changed.connect(busy.append)
    service.create("One")
    service.create("Two")
    assert len(runner.pending) == 1 and service.mutating
    runner.complete()
    assert not service.mutating and busy == [True, False]
    assert list(store.projects).count("two") == 0


def test_failure_reported(tmp_path):
    store, session, service, *_ = make(tmp_path, with_page=False)
    failed = []
    service.failed.connect(lambda *a: failed.append(a))
    store.fail["DELETE"] = BackendError("CONFLICT", "Project is rendering", 409)
    service.trash("alpha")
    assert failed[0][:2] == ("trash", "CONFLICT") and not service.mutating


# ----------------------------------------------------------------------------- page

def test_page_disconnected_message_and_button(tmp_path):
    store, session, service, prefs, page = make(tmp_path, connect=False)
    assert "Connect to a Morphorum backend" in page.status_line.text()
    clicks = []
    page.open_connections.connect(lambda: clicks.append(1))
    page.connect_button.click()
    assert clicks == [1]
    assert not page.new_button.isEnabled()


def test_page_without_feature(tmp_path):
    *_, page = make(tmp_path, features={})
    assert "does not advertise project support" in page.status_line.text()


def test_page_lists_only_when_active_and_filters(tmp_path):
    store, session, service, prefs, page = make(tmp_path)
    assert page.project_list.count() == 0
    page.set_active(True)
    assert page.project_list.count() == 2
    page.search.setText("bet")
    assert page.project_list.count() == 1
    page.search.setText("zzz")
    assert page.project_list.count() == 0


def test_page_opens_edits_saves(tmp_path):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    page._select("alpha")
    assert page.name_edit.text() == "Alpha" and not page.save_button.isEnabled()
    page.name_edit.setText("Alpha renamed")
    assert page.has_unsaved_changes() and page.save_button.isEnabled()
    assert page.dirty_label.text() == "Unsaved changes"
    page.save_button.click()
    assert store.projects["alpha"]["name"] == "Alpha renamed"
    assert not page.has_unsaved_changes() and page.dirty_label.text() == "Saved"
    assert prefs.recent_projects("p1")[0] == "alpha"


def test_page_revert(tmp_path):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    page._select("alpha")
    page.notes_edit.setPlainText("changed")
    page.revert_button.click()
    assert page.notes_edit.toPlainText() == "a" and not page.has_unsaved_changes()


def test_switching_with_unsaved_edits_asks(tmp_path, monkeypatch):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    page._select("alpha")
    page.name_edit.setText("dirty")
    asked = answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    page._select("beta")
    assert asked and page.name_edit.text() == "dirty" and page._selected == "alpha"
    answer(monkeypatch, QMessageBox.StandardButton.Discard)
    page._select("beta")
    assert page.name_edit.text() == "Beta"


def test_conflict_keeps_edits_and_can_reload(tmp_path, monkeypatch):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    page._select("alpha")
    page.name_edit.setText("mine")
    store.projects["alpha"]["rev"] += 1  # someone else saved
    store.projects["alpha"]["name"] = "theirs"
    shown = []
    monkeypatch.setattr(page, "_conflict", lambda: shown.append(1))
    page.save_button.click()
    assert shown == [1] and page.name_edit.text() == "mine"
    page._service.open("alpha")
    assert page.name_edit.text() == "theirs"


def test_create_selects_new_project(tmp_path, monkeypatch):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    monkeypatch.setattr("morphorum_studio.ui.projects_page.QInputDialog.getText",
                        lambda *a, **k: ("Gamma Ray", True))
    page.new_button.click()
    assert "gamma-ray" in store.projects
    assert page.name_edit.text() == "Gamma Ray"
    assert any(page.project_list.item(i).data(0x100) == "gamma-ray" for i in range(page.project_list.count()))


def test_create_cancelled_does_nothing(tmp_path, monkeypatch):
    store, session, service, prefs, page = make(tmp_path)
    monkeypatch.setattr("morphorum_studio.ui.projects_page.QInputDialog.getText",
                        lambda *a, **k: ("", False))
    page.new_button.click()
    assert not any(c[0] == "POST" for c in store.calls)


def test_trash_confirmed_and_declined(tmp_path, monkeypatch):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    page._select("alpha")
    answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    page.trash_button.click()
    assert "alpha" in store.projects
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    page.trash_button.click()
    assert "alpha" not in store.projects
    assert page.detail_stack.currentIndex() == 0
    assert "alpha" not in prefs.recent_projects("p1")


def test_trash_refusal_is_shown(tmp_path, monkeypatch):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    page._select("alpha")
    asked = answer(monkeypatch, QMessageBox.StandardButton.Yes)
    store.fail["DELETE"] = BackendError("CONFLICT", "Project is rendering", 409)
    page.trash_button.click()
    assert ("warn", "Could not move to Trash", "Project is rendering") in asked
    assert "alpha" in store.projects


def test_open_failure_shows_message(tmp_path):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    store.fail["open"] = BackendError("NOT_FOUND", "gone", 404)
    page._select("alpha")
    assert "Could not open" in page.empty_detail.text() and page.detail_stack.currentIndex() == 0


def test_last_project_restored_per_connection(tmp_path):
    store, session, service, prefs, page = make(tmp_path, connect=False)
    prefs.remember_project("p1", "beta")
    session.connected(info(features=FEATURES), "tok")
    page.set_active(True)
    assert page._selected == "beta" and page.name_edit.text() == "Beta"


def test_reconnecting_keeps_unsaved_edits(tmp_path):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    page._select("alpha")
    page.name_edit.setText("edited")
    session.reconnecting()
    assert page.name_edit.text() == "edited" and page.has_unsaved_changes()
    assert not page.save_button.isEnabled()
    session.connected(info(features=FEATURES), "tok")
    assert page.name_edit.text() == "edited" and page.save_button.isEnabled()


def test_disconnect_clears_page(tmp_path):
    store, session, service, prefs, page = make(tmp_path)
    page.set_active(True)
    page._select("alpha")
    session.disconnected()
    assert page.project_list.count() == 0 and not page.has_unsaved_changes()
    assert "Connect to a Morphorum backend" in page.status_line.text()


def test_recents_helpers(tmp_path):
    prefs = StudioPreferences(QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat))
    for name in "abcdefghij":
        prefs.remember_project("p", name)
    prefs.remember_project("p", "c")
    recent = prefs.recent_projects("p")
    assert recent[0] == "c" and len(recent) == 8 and len(set(recent)) == 8
    prefs.forget_project("p", "c")
    assert "c" not in prefs.recent_projects("p")
    assert prefs.recent_projects("other") == []


def test_formatters():
    assert format_size(512, 768) == "512×768"
    assert format_size(None, 5) == "—"
    assert format_length(24, 12) == "24 frames at 12 fps (2.0 s)"
    assert format_length(None, 12) == "—"
    assert format_when(None) == "—" and format_when("garbage") == "—"
    assert len(format_when("2026-10-01T12:00:00Z")) == 16


def test_main_window_wiring(tmp_path):
    from morphorum_studio.ui.main_window import PAGES, StudioMainWindow

    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "w.ini"), QSettings.Format.IniFormat)
    window = StudioMainWindow(preferences=StudioPreferences(settings))
    try:
        names = [p[0] for p in PAGES]
        assert window.pages.widget(names.index("Projects")) is window.projects_page
        assert not window.projects_page._active
        window.navigation.setCurrentRow(names.index("Projects"))
        assert window.projects_page._active
        window.navigation.setCurrentRow(names.index("Home"))
        assert not window.projects_page._active
        window.projects_page.connect_button.click()
        assert window.navigation.currentRow() == names.index("Connections")
    finally:
        window.close()
