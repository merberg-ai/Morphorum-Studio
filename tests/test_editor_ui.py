"""Editor timeline service and page against a scripted fake backend (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtWidgets import QApplication
from test_timeline_api import SNAPSHOT, resolved_payload

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.editor_page import EditorPage
from morphorum_studio.ui.projects_service import ProjectsService
from morphorum_studio.ui.timeline_service import TimelineService
from morphorum_studio.ui.timeline_view import HEAD_H, RULER_H

FEATURES = {"project_crud": True, "timeline": True}
RAW = {"id": "demo", "name": "Demo", "animation": {"width": 64, "height": 64, "fps": 24, "max_frames": 48}}


class Backend:
    def __init__(self):
        self.calls = []
        self.fail = {}


class Client:
    def __init__(self, backend):
        self.b = backend

    def get_json(self, path, params=None):
        self.b.calls.append(("GET", path))
        if "get" in self.b.fail:
            raise self.b.fail["get"]
        if path == "/api/animation/projects":
            return {"projects": [{"id": "demo", "name": "Demo"}]}
        if path.endswith("/timeline"):
            return SNAPSHOT
        raise BackendError("NOT_FOUND", "no route", 404)

    def get_json_etag(self, path, params=None):
        return {"project": RAW}, '"' + "a" * 64 + '"'

    def send_json(self, method, path, body=None, *, if_match=None, idempotency_key=None, max_bytes=0):
        self.b.calls.append((method, path, body))
        if path.endswith("/schedule-series"):
            if "series" in self.b.fail:
                raise self.b.fail["series"]
            return {"field": body["field"], "interpolation": "linear",
                    "samples": [{"frame": 0, "value": 1.0}, {"frame": 47, "value": 1.4}]}, None
        if path.endswith("/resolve-timeline"):
            return resolved_payload(body["start_frame"]), None
        raise BackendError("NOT_FOUND", "no route", 404)


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def make(features=FEATURES):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    backend = Backend()
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(backend))
    projects = ProjectsService(session, runner=sync_runner)
    service = TimelineService(session, runner=sync_runner)
    page = EditorPage(session, projects, service)
    session.connected(info(features=features), "tok")
    return backend, session, projects, service, page


def open_demo(page, projects):
    projects.refresh()
    page.project.setCurrentIndex(1)
    page._project_chosen(1)


def test_service_loads_timeline_with_project_and_frame_zero():
    backend, session, projects, service, page = make()
    open_demo(page, projects)
    assert service.timeline.max_frames == 48
    assert [c for c in backend.calls if c[0] == "POST"][0][1].endswith("/resolve-timeline")
    assert page.frame_spin.maximum() == 47 and "48 frames" in page.status.text()
    assert page.values.rowCount() == 2 and page.values.item(0, 1).text().startswith("1.25")
    assert "a cat" in page.prompt_view.toPlainText()


def test_scrubbing_resolves_the_chosen_frame_after_debounce():
    backend, session, projects, service, page = make()
    open_demo(page, projects)
    page._view_frame(12)
    page.view.set_frame(12)
    page._debounce.timeout.emit()
    posts = [c for c in backend.calls if c[0] == "POST" and c[1].endswith("/resolve-timeline")]
    assert posts[-1][2]["start_frame"] == 12 and posts[-1][2]["end_frame"] == 12
    assert page.frame_spin.value() == 12 and page.time_label.text() == "0.50 s"


def test_selecting_a_numeric_track_loads_keys_and_curve_once():
    backend, session, projects, service, page = make()
    open_demo(page, projects)
    page.view.track_selected.emit("camera_2d.zoom")
    assert page.keys.rowCount() == 2 and page.keys.item(1, 1).text() == "1+0.5*sin(t)"
    page.view.track_selected.emit("camera_2d.zoom")
    series_calls = [c for c in backend.calls if c[0] == "POST" and c[1].endswith("/schedule-series")]
    assert len(series_calls) == 1 and series_calls[0][2]["field"] == "motion.zoom"


def test_prompt_track_shows_keys_but_no_curve_request():
    backend, session, projects, service, page = make()
    open_demo(page, projects)
    page.view.track_selected.emit("prompts.positive")
    assert page.keys.rowCount() == 2
    assert not [c for c in backend.calls if c[0] == "POST" and c[1].endswith("/schedule-series")]


def test_refused_curve_is_reported_not_drawn():
    backend, session, projects, service, page = make()
    open_demo(page, projects)
    backend.fail["series"] = BackendError("INVALID_REQUEST", "Backend returned HTTP 400: bad schedule", 400)
    page.view.track_selected.emit("camera_2d.angle")
    assert "Series failed" in page.status.text() or "failed" in page.status.text()


def test_unsupported_and_offline_states():
    backend, session, projects, service, page = make(features={"project_crud": True})
    assert "does not provide the timeline" in page.status.text()
    session.disconnected()
    assert "Connect to a backend" in page.status.text()


def test_new_connection_clears_the_timeline():
    backend, session, projects, service, page = make()
    open_demo(page, projects)
    session.connected(info(boot="z", features=FEATURES), "tok")
    assert service.timeline is None and page.values.rowCount() == 0 and page.keys.rowCount() == 0


def test_load_failure_is_shown():
    backend, session, projects, service, page = make()
    projects.refresh()
    backend.fail["get"] = BackendError("NETWORK_ERROR", "Unable to reach backend")
    page.project.setCurrentIndex(1)
    page._project_chosen(1)
    assert "Load failed" in page.status.text()


def test_timeline_view_hit_testing_and_keyboard():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    backend, session, projects, service, page = make()
    open_demo(page, projects)
    view = page.view
    view.resize(800, view.height())
    frames = []
    view.frame_changed.connect(frames.append)
    assert view._frame_at(view._x(24)) == 24 and view._frame_at(-50) == 0 and view._frame_at(10_000) == 47
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier))
    assert frames == [1, 11]
    kind, item = view._row_at(RULER_H + HEAD_H + 2)
    assert kind == "track" and item.id == "prompts.positive"
