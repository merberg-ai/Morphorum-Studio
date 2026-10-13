"""Keyframe editing, undo/redo and the revision guard against a stateful fake (offscreen Qt, CI only)."""

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtWidgets import QApplication, QMessageBox
from test_timeline_api import SNAPSHOT, resolved_payload

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.editor_page import EditorPage
from morphorum_studio.ui.projects_service import ProjectsService
from morphorum_studio.ui.timeline_service import TimelineService

FEATURES = {"project_crud": True, "timeline": True}
RAW = {"id": "demo", "name": "Demo", "animation": {"width": 64, "height": 64, "fps": 24, "max_frames": 48}}


class Backend:
    def __init__(self):
        self.snapshot = copy.deepcopy(SNAPSHOT)
        self.rev = 1
        self.writes = []  # (method, path, body)
        self.fail_next = None

    def etag(self):
        return '"' + format(self.rev, "x").rjust(64, "0") + '"'

    def track(self, path):
        parts = path.split("/tracks/")[1].split("/")
        return self.snapshot["tracks"][parts[0]][parts[1]], parts[2:]


class Client:
    def __init__(self, backend):
        self.b = backend

    def get_json(self, path, params=None):
        if path == "/api/animation/projects":
            return {"projects": [{"id": "demo", "name": "Demo"}]}
        if path.endswith("/timeline"):
            return copy.deepcopy(self.b.snapshot)
        raise BackendError("NOT_FOUND", "no route", 404)

    def get_json_etag(self, path, params=None):
        return {"project": RAW}, self.b.etag()

    def send_json(self, method, path, body=None, *, if_match=None, idempotency_key=None, max_bytes=0):
        if path.endswith("/schedule-series"):
            return {"field": body["field"], "samples": [{"frame": 0, "value": 1.0}, {"frame": 47, "value": 2.0}]}, None
        if path.endswith("/resolve-timeline"):
            return resolved_payload(body["start_frame"]), None
        self.b.writes.append((method, path, body))
        if self.b.fail_next:
            error, self.b.fail_next = self.b.fail_next, None
            raise error
        track, rest = self.b.track(path)
        keys = {k["frame"]: k for k in track["keyframes"]}
        if rest[0] == "interpolation":
            track["interpolation"] = body["interpolation"]
        elif rest[0] == "keyframes":
            frame = int(rest[1])
            if len(rest) == 3:  # move
                moved = keys.pop(frame)
                moved["frame"] = body["frame"]
                moved["frame_expression"] = str(body["frame"])
                keys[body["frame"]] = moved
            elif method == "DELETE":
                keys.pop(frame)
            else:
                keys[frame] = {"frame": frame, "frame_expression": str(frame), "value": body["value"]}
        track["keyframes"] = [keys[f] for f in sorted(keys)]
        self.b.rev += 1
        return {"status": "saved"}, None


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def make():
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    backend = Backend()
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(backend))
    projects = ProjectsService(session, runner=sync_runner)
    service = TimelineService(session, runner=sync_runner)
    page = EditorPage(session, projects, service)
    session.connected(info(features=FEATURES), "tok")
    projects.refresh()
    page.project.setCurrentIndex(1)
    page._project_chosen(1)
    return backend, session, service, page


def keys_of(backend, group="camera_2d", name="zoom"):
    return [(k["frame"], k["value"]) for k in backend.snapshot["tracks"][group][name]["keyframes"]]


def playhead(page, frame):
    page.view.set_frame(frame)
    page._view_frame(frame)


def select_track(page, track_id="camera_2d.zoom"):
    page.view.track_selected.emit(track_id)


def test_set_undo_redo_round_trip():
    backend, _, service, page = make()
    select_track(page)
    playhead(page, 10)
    page.value_edit.setPlainText("2.5")
    page.set_button.click()
    assert keys_of(backend) == [(0, "1.0"), (10, "2.5"), (24, "1+0.5*sin(t)")]
    assert page.keys.rowCount() == 3 and page.edit_status.text() == "Saved."
    assert page.undo_button.isEnabled() and not page.redo_button.isEnabled()
    page.undo_button.click()
    assert keys_of(backend) == [(0, "1.0"), (24, "1+0.5*sin(t)")] and page.redo_button.isEnabled()
    page.redo_button.click()
    assert keys_of(backend)[1] == (10, "2.5")
    assert service.undo_label.startswith("Add 2D Zoom keyframe at 10")


def test_update_selected_and_delete_then_undo_restore_exact_values():
    backend, _, service, page = make()
    select_track(page)
    page.keys.setCurrentCell(1, 0)
    page.value_edit.setPlainText("3")
    page.update_button.click()
    assert keys_of(backend)[1] == (24, "3")
    page.keys.setCurrentCell(1, 0)
    page.delete_button.click()
    assert keys_of(backend) == [(0, "1.0")]
    page.undo_button.click()
    assert keys_of(backend)[1] == (24, "3")
    page.undo_button.click()
    assert keys_of(backend)[1] == (24, "1+0.5*sin(t)")


def test_move_with_overwrite_confirmation_and_full_undo(monkeypatch):
    backend, _, service, page = make()
    select_track(page)
    page.keys.setCurrentCell(1, 0)
    playhead(page, 0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    page.move_button.click()
    assert not backend.writes
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page.move_button.click()
    assert keys_of(backend) == [(0, "1+0.5*sin(t)")]
    page.undo_button.click()
    assert keys_of(backend) == [(0, "1.0"), (24, "1+0.5*sin(t)")]


def test_interpolation_change_and_undo():
    backend, _, service, page = make()
    select_track(page)
    page.interp.setCurrentIndex(page.interp.findData("hold"))
    page.interp.activated.emit(page.interp.currentIndex())
    assert backend.snapshot["tracks"]["camera_2d"]["zoom"]["interpolation"] == "hold"
    assert page.interp.currentData() == "hold"
    page.undo_button.click()
    assert backend.snapshot["tracks"]["camera_2d"]["zoom"]["interpolation"] == "linear"
    assert page.interp.currentData() == "linear"


def test_local_refusals_send_nothing():
    backend, _, service, page = make()
    select_track(page)
    playhead(page, 10)
    page.value_edit.setPlainText("   ")
    page.set_button.click()
    assert "needs a value" in page.edit_status.text() and not backend.writes


def test_revision_guard_refuses_after_an_outside_change():
    backend, _, service, page = make()
    conflicts = []
    service.conflict.connect(conflicts.append)
    select_track(page)
    playhead(page, 10)
    page.value_edit.setPlainText("2")
    page.set_button.click()
    backend.rev += 1  # someone else saved the project
    n = len(backend.writes)
    page.value_edit.setPlainText("3")
    page.set_button.click()
    assert len(backend.writes) == n and conflicts and "changed elsewhere" in page.edit_status.text()
    assert not service.undo_label  # history no longer describes the backend
    assert service.timeline is not None  # reloaded
    select_track(page)
    playhead(page, 10)
    page.value_edit.setPlainText("3")
    page.set_button.click()
    assert keys_of(backend)[1] == (10, "3")


def test_backend_refusal_keeps_history_but_unknown_failure_resets_it():
    backend, _, service, page = make()
    select_track(page)
    playhead(page, 10)
    page.value_edit.setPlainText("2")
    page.set_button.click()
    backend.fail_next = BackendError("INVALID_REQUEST", "Backend returned HTTP 400: bad expression", 400)
    playhead(page, 12)
    page.value_edit.setPlainText("oops(")
    page.set_button.click()
    assert "bad expression" in page.edit_status.text() and service.undo_label
    backend.fail_next = BackendError("NETWORK_ERROR", "Unable to reach backend")
    page.value_edit.setPlainText("4")
    page.set_button.click()
    assert "Edit failed" in page.edit_status.text() and not service.undo_label
    assert service.timeline is not None


def test_controls_follow_state():
    backend, session, service, page = make()
    assert not page.set_button.isEnabled()  # no track selected
    select_track(page)
    assert page.set_button.isEnabled() and not page.update_button.isEnabled()
    session.disconnected()
    assert not service.can_edit and not page.set_button.isEnabled()


def test_new_connection_drops_history():
    backend, session, service, page = make()
    select_track(page)
    playhead(page, 10)
    page.value_edit.setPlainText("2")
    page.set_button.click()
    assert service.undo_label
    session.connected(info(boot="z", features=FEATURES), "tok")
    assert service.undo_label is None and service.timeline is None
