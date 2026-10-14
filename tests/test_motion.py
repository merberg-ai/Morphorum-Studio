"""S5.1 Motion Lab: backend helpers, service and panel (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.motion import (
    AXES,
    describe_layer,
    editable,
    is_conflict,
    new_curve_layer,
    new_preset_layer,
    parse_preview,
    state_of,
    unique_id,
)
from morphorum_studio.backend.session import BackendSession, SessionInfo
from morphorum_studio.ui.motion_panel import MotionPanel
from morphorum_studio.ui.motion_service import MotionService

QApplication.instance() or QApplication(["morphorum-studio-tests"])

AUDIO_LAYER = {"id": "audio-1", "type": "audio", "name": "Kick pulses", "enabled": True,
               "blend": "add", "start_frame": 0, "end_frame": 24, "axis": "translation_z"}


def raw_project(mode="3d", layers=None):
    return {"id": "demo", "animation": {"mode": mode, "max_frames": 24, "fps": 12},
            "motion_lab": {"layers": layers if layers is not None else [dict(AUDIO_LAYER)],
                           "limits": {"translation_x": 0.12}, "last_applied_tracks": None}}


def series(value=0.01):
    return {axis: [value * i for i in range(24)] for axis in AXES}


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


class Fake:
    def __init__(self, project=None):
        self.project = project or raw_project()
        self.posts = []
        self.fail = {}  # "preview"/"apply" -> BackendError

    def get_json(self, path, params=None):
        if path == "/api/animation/motion-lab/presets":
            return {"presets": ["still", "wave", "push-in"]}
        raise BackendError("NOT_FOUND", path)

    def get_json_etag(self, path, params=None):
        return {"project": self.project}, '"' + "a" * 64 + '"'

    def send_json(self, method, path, body=None, **kwargs):
        step = path.rsplit("/", 1)[-1]
        self.posts.append((step, body))
        if step in self.fail:
            error = self.fail[step]
            if error.code != "CONFLICT" or not body.get("rebase_current"):
                raise error
        if step == "preview":
            return {"status": "preview", "layers": body["layers"],
                    "diagnostics": {"series": series(), "limited": {"translation_x": 3},
                                    "camera_changed": False, "rebased": False,
                                    "frames": 24, "fps": 12.0}}, None
        return {"status": "applied", "project": self.project, "diagnostics": {}}, None


def info(features=None):
    return SessionInfo("p1", "Workshop", "http://10.0.0.5:7866", "0.1.0", "backend-only", "i1", "b1",
                       {"timeline": True} if features is None else features)


def rig(project=None):
    client = Fake(project)
    session = BackendSession(client_factory=lambda base, token, timeout=6.0: client)
    service = MotionService(session, runner=sync_runner)
    panel = MotionPanel(service)
    session.connected(info(), "t")
    return client, session, service, panel


# ----------------------------------------------------------------------------- helpers

def test_state_of_reads_mode_layers_and_tolerates_junk():
    state = state_of(raw_project())
    assert state.usable and state.frames == 24 and state.fps == 12.0
    assert state.layers[0]["id"] == "audio-1" and state.limits == {"translation_x": 0.12}
    assert not state_of(raw_project(mode="2d")).usable
    assert not state_of("nonsense").usable and state_of(None).layers == ()


def test_new_layers_have_unique_ids_and_valid_shape():
    layers = [{"id": "layer-1"}, {"id": "layer-3"}]
    assert unique_id(layers) == "layer-4"
    preset = new_preset_layer(layers, 24, "wave")
    assert preset["type"] == "preset" and preset["end_frame"] == 24 and preset["preset"] == "wave"
    curve = new_curve_layer(layers, 24, "rotation_y")
    assert curve["keys"][0]["frame"] == 12 and curve["keys"][0]["value"] == 0.4
    assert curve["keys"][0]["frame"] != 0  # frame 0 must stay still
    for bad in (lambda: new_preset_layer([], 24, "bogus"), lambda: new_curve_layer([], 24, "bogus")):
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_describe_and_editable():
    assert describe_layer({"type": "preset", "preset": "push-in"}) == "Push in"
    assert describe_layer({"type": "keyframes", "axis": "rotation_y"}) == "Curve · Pan (Y)"
    assert describe_layer(AUDIO_LAYER) == "Kick pulses"
    assert editable({"type": "preset"}) and not editable(AUDIO_LAYER)


def test_parse_preview_and_conflict_detection():
    preview = parse_preview({"layers": [{"id": "a"}], "diagnostics": {
        "series": series(), "limited": {"rotation_x": 2, "bogus": 1}, "frames": 24, "fps": 12}})
    assert set(preview.series) == set(AXES) and preview.limited == {"rotation_x": 2}
    try:
        parse_preview({"diagnostics": {}})
    except BackendError as exc:
        assert exc.code == "INVALID_RESPONSE"
    else:
        raise AssertionError("expected BackendError")
    assert is_conflict("CONFLICT", "") and is_conflict("X", "Camera schedules changed since Motion Lab last")
    assert not is_conflict("INVALID_REQUEST", "nope")


# ----------------------------------------------------------------------------- service and panel

def test_panel_loads_layers_and_keeps_unknown_layers():
    client, session, service, panel = rig()
    panel.set_project("demo")
    assert panel.layer_list.count() == 1 and "Kick pulses" in panel.layer_list.item(0).text()
    assert not panel.dirty and panel.preview_button.isEnabled()
    assert panel.preset_combo.count() == 3
    assert not panel.blend_combo.isVisibleTo(panel) and panel.kept_note.text()


def test_2d_project_explains_and_disables():
    client, session, service, panel = rig(raw_project(mode="2d"))
    panel.set_project("demo")
    assert "2D mode" in panel.status.text()
    assert not panel.add_preset_button.isEnabled() and not panel.apply_button.isEnabled()


def test_add_edit_move_remove_layers():
    client, session, service, panel = rig()
    panel.set_project("demo")
    panel.add_preset_button.click()
    assert panel.layer_list.count() == 2 and panel.dirty
    layer = panel.layers[1]
    assert layer["type"] == "preset" and layer["preset"] == "wave" and layer["end_frame"] == 24
    panel.strength_spin.setValue(0.8)
    panel.end_spin.setValue(12)
    panel.blend_combo.setCurrentIndex(1)
    panel.blend_combo.activated.emit(1)
    edited = panel.layers[1]
    assert edited["strength"] == 0.8 and edited["end_frame"] == 12 and edited["blend"] == "replace"
    panel.up_button.click()
    assert panel.layers[0]["id"] == edited["id"] and panel.layers[1]["id"] == "audio-1"
    panel.duplicate_button.click()
    assert len(panel.layers) == 3 and len({x["id"] for x in panel.layers}) == 3
    panel.remove_button.click()
    assert len(panel.layers) == 2
    panel.revert_button.click()
    assert not panel.dirty and panel.layer_list.count() == 1


def test_range_cannot_invert():
    client, session, service, panel = rig()
    panel.set_project("demo")
    panel.add_preset_button.click()
    panel.start_spin.setValue(20)
    layer = panel.layers[1]
    assert layer["start_frame"] == 20 and layer["end_frame"] > 20


def test_curve_layer_keys():
    client, session, service, panel = rig()
    panel.set_project("demo")
    panel.add_curve_button.click()
    assert panel.forms.currentIndex() == 2 and panel.key_table.rowCount() == 1
    panel.add_key_button.click()
    assert panel.key_table.rowCount() == 2
    panel.key_table.item(1, 1).setText("0.05")
    assert panel.layers[1]["keys"][-1]["value"] == 0.05 or panel.layers[1]["keys"][0]["value"] == 0.05
    panel.key_table.item(0, 0).setText("not a number")
    assert "whole frame" in panel.status.text()
    panel.key_table.selectRow(0)
    panel.remove_key_button.click()
    assert panel.key_table.rowCount() == 1
    panel.key_table.selectRow(0)
    panel.remove_key_button.click()  # the last key stays
    assert panel.key_table.rowCount() == 1 and "at least one keyframe" in panel.status.text()
    panel.axis_combo.setCurrentIndex(3)
    panel.axis_combo.activated.emit(3)
    assert panel.layers[1]["axis"] == "rotation_x"


def test_toggle_enabled_marks_dirty():
    client, session, service, panel = rig()
    panel.set_project("demo")
    from PySide6.QtCore import Qt
    panel.layer_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert panel.layers[0]["enabled"] is False and panel.dirty


def test_preview_sends_draft_and_draws_chart():
    client, session, service, panel = rig()
    panel.set_project("demo")
    panel.add_preset_button.click()
    panel.preview_button.click()
    step, body = client.posts[-1]
    assert step == "preview" and len(body["layers"]) == 2 and body["layers"][0]["id"] == "audio-1"
    assert panel.chart.has_data and "Clipped" in panel.limit_note.text()
    panel.strength_spin.setValue(0.9)
    assert panel.chart._stale is True
    panel.axis_boxes["translation_x"].setChecked(False)
    assert "translation_x" not in panel.chart._shown


def test_apply_reloads_and_signals():
    client, session, service, panel = rig()
    panel.set_project("demo")
    got = []
    panel.applied.connect(got.append)
    panel.apply_button.click()
    assert client.posts[-1][0] == "apply" and "rebase_current" not in client.posts[-1][1]
    assert got == ["demo"]


def test_conflict_asks_before_rebasing(monkeypatch):
    client, session, service, panel = rig()
    panel.set_project("demo")
    client.fail["apply"] = BackendError("CONFLICT", "Camera schedules changed since Motion Lab last applied")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))
    panel.apply_button.click()
    assert [s for s, _ in client.posts].count("apply") == 1 and "cancelled" in panel.status.text()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    panel.apply_button.click()
    assert client.posts[-1][0] == "apply" and client.posts[-1][1]["rebase_current"] is True


def test_backend_error_is_shown():
    client, session, service, panel = rig()
    panel.set_project("demo")
    client.fail["preview"] = BackendError("INVALID_REQUEST", "Frame 0 must have zero camera movement.")
    panel.preview_button.click()
    assert "Frame 0" in panel.status.text()


def test_stale_answers_are_dropped_after_project_change():
    client, session, service, panel = rig()
    pending = []
    service._run = lambda c, fn, cb: pending.append((c, fn, cb))
    panel.set_project("demo")
    panel.set_project("other")
    assert len(pending) == 2
    for c, fn, cb in pending:
        cb(fn(c), None)
    assert panel.layer_list.count() == 1  # only the newest load was applied; the older was dropped
