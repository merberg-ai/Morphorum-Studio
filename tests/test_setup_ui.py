"""New project wizard and model browser against a scripted fake backend (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.models_dialog import ModelsDialog, describe_lora
from morphorum_studio.ui.setup_dialog import NewProjectDialog
from morphorum_studio.ui.setup_service import ModelsService, SetupService

FEATURES = {"project_crud": True, "model_discovery": True}
TEMPLATE = {"name": "T", "animation": {"max_frames": 96, "fps": 12.0, "width": 768, "height": 768,
                                       "mode": "2d", "start_mode": "prompt"},
            "camera_3d": {"translation_z": "0:(0)"}, "tracks": {}}
MODELS = {
    "checkpoints": [{"id": "c1", "family": "sdxl", "kind": "checkpoints", "name": "Juggernaut", "variant": "base"}],
    "loras": [{"id": "l1", "family": "sdxl", "kind": "loras", "name": "Fox Style"},
              {"id": "l2", "family": "flux", "kind": "loras", "name": "Ink Wash"}],
}


class Backend:
    def __init__(self):
        self.calls = []
        self.issues = []
        self.fail = {}


class Client:
    def __init__(self, backend):
        self.b = backend

    def get_json(self, path, params=None):
        self.b.calls.append(("GET", path, params))
        if "get" in self.b.fail:
            raise self.b.fail["get"]
        if path == "/api/animation/project-template":
            return {"project": TEMPLATE}
        if path == "/api/models":
            return {"models": MODELS[params["kind"]]}
        if path.endswith("/inspect"):
            if "inspect" in self.b.fail:
                raise self.b.fail["inspect"]
            return {"name": path.split("/")[3], "family": "sdxl", "trigger_words": ["foxstyle"],
                    "ranks": [{"rank": 16, "modules": 480}], "warnings": ["old format"]}
        raise BackendError("NOT_FOUND", path, 404)

    def send_json(self, method, path, body=None, *, if_match=None, idempotency_key=None, max_bytes=0):
        self.b.calls.append((method, path, body))
        if path.endswith("/validate-schedules"):
            return {"valid": not any(i["severity"] == "error" for i in self.b.issues),
                    "issues": self.b.issues}, None
        if "create" in self.b.fail:
            raise self.b.fail["create"]
        return {"status": "created", "project": {"id": "my-film-1", "name": body["name"]}}, None


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
    setup = SetupService(session, runner=sync_runner)
    models = ModelsService(session, runner=sync_runner)
    session.connected(info(features=features), "tok")
    return backend, session, setup, models


def posts(backend, suffix):
    return [c for c in backend.calls if c[0] == "POST" and c[1].endswith(suffix)]


# ----------------------------------------------------------------------------- wizard

def test_wizard_loads_backend_defaults_and_checkpoints():
    backend, _, setup, _ = make()
    dialog = NewProjectDialog(setup)
    assert dialog.model.count() == 2 and "Juggernaut" in dialog.model.itemText(1)
    assert dialog.fps.value() == 12 and dialog.frames.value() == 96
    assert (dialog.width.value(), dialog.height.value()) == (768, 768)
    assert dialog.size_preset.currentText().startswith("Square 768")
    assert "8.0 seconds" in dialog.length_label.text()
    assert dialog.check_button.isEnabled() and not dialog.create_button.isEnabled()


def test_missing_checkpoint_is_reported_without_asking_the_backend():
    backend, _, setup, _ = make()
    dialog = NewProjectDialog(setup)
    dialog.check_button.click()
    assert not posts(backend, "/validate-schedules")
    assert "Fix the problems" in dialog.summary.text()
    assert "Choose a checkpoint" in dialog.issues.item(0).text() and not dialog.create_button.isEnabled()


def test_check_then_create_sends_only_the_wizards_choices():
    backend, _, setup, _ = make()
    dialog = NewProjectDialog(setup)
    made = []
    dialog.project_created.connect(made.append)
    dialog.name.setText("My Film")
    dialog.model.setCurrentIndex(1)
    dialog.mode.setCurrentIndex(1)  # 3D
    dialog.prompt.setPlainText("a fox")
    dialog.check_button.click()
    assert "Ready to create" in dialog.summary.text() and dialog.create_button.isEnabled()
    review = posts(backend, "/validate-schedules")[0][2]["project"]
    assert review["animation"]["mode"] == "3d" and "tracks" not in review
    dialog.create_button.click()
    sent = posts(backend, "/api/animation/projects")[0][2]
    assert sent["name"] == "My Film" and sent["model"]["model_id"] == "c1"
    assert sent["prompts"] == {"0": "a fox"} and "tracks" not in sent
    assert sent["camera_3d"] == TEMPLATE["camera_3d"]  # the camera schedule is never seeded
    assert made == ["my-film-1"] and not dialog.isVisible()


def test_backend_schedule_errors_block_creation_and_are_listed():
    backend, _, setup, _ = make()
    backend.issues = [{"field": "camera_3d.translation_z", "severity": "error", "message": "behind the camera"},
                      {"field": "generation.steps", "severity": "warning", "message": "very high"}]
    dialog = NewProjectDialog(setup)
    dialog.model.setCurrentIndex(1)
    dialog.prompt.setPlainText("x")
    dialog.check_button.click()
    texts = [dialog.issues.item(i).text() for i in range(dialog.issues.count())]
    assert any("behind the camera" in t and t.startswith("✖") for t in texts)
    assert any("very high" in t and t.startswith("⚠") for t in texts)
    assert "cannot be created" in dialog.summary.text() and not dialog.create_button.isEnabled()


def test_editing_after_a_review_discards_it():
    backend, _, setup, _ = make()
    dialog = NewProjectDialog(setup)
    dialog.model.setCurrentIndex(1)
    dialog.prompt.setPlainText("x")
    dialog.check_button.click()
    assert dialog.create_button.isEnabled()
    dialog.frames.setValue(200)
    assert not dialog.create_button.isEnabled() and dialog.issues.count() == 0
    assert "Choose Check" in dialog.summary.text()


def test_failed_create_is_shown_and_review_must_be_repeated():
    backend, _, setup, _ = make()
    backend.fail["create"] = BackendError("VALIDATION_ERROR", "name already used", 400)
    dialog = NewProjectDialog(setup)
    dialog.model.setCurrentIndex(1)
    dialog.prompt.setPlainText("x")
    dialog.check_button.click()
    dialog.create_button.click()
    assert "name already used" in dialog.summary.text() and not dialog.create_button.isEnabled()
    assert dialog.check_button.isEnabled()


def test_custom_size_selects_custom_preset_and_odd_sizes_warn():
    backend, _, setup, _ = make()
    dialog = NewProjectDialog(setup)
    dialog.width.setValue(1001)
    assert dialog.size_preset.currentText() == "Custom"
    dialog.model.setCurrentIndex(1)
    dialog.prompt.setPlainText("x")
    dialog.check_button.click()
    assert any("multiple of 8" in dialog.issues.item(i).text() for i in range(dialog.issues.count()))
    assert dialog.create_button.isEnabled()  # a warning does not block


def test_wizard_stays_disabled_when_template_cannot_load():
    backend, _, setup, _ = make()
    backend.fail["get"] = BackendError("NETWORK_ERROR", "down")
    dialog = NewProjectDialog(setup)
    assert "failed" in dialog.summary.text() and not dialog.check_button.isEnabled()


def test_service_is_unavailable_without_project_support():
    backend, _, setup, _ = make(features={})
    assert not setup.available
    NewProjectDialog(setup)
    assert backend.calls == []


# ----------------------------------------------------------------------------- models

def test_models_dialog_lists_and_filters_loras():
    backend, _, _, models = make()
    dialog = ModelsDialog(models)
    assert dialog.checkpoint_list.count() == 1 and dialog.lora_list.count() == 2
    assert "1 checkpoint(s) and 2 LoRA(s)" in dialog.note.text()
    dialog.family.setCurrentIndex(dialog.family.findData("flux"))
    assert [dialog.lora_list.item(i).text() for i in range(dialog.lora_list.count())] == ["Ink Wash  (flux)"]
    dialog.family.setCurrentIndex(0)
    dialog.search.setText("fox")
    assert dialog.lora_list.count() == 1 and dialog.lora_list.item(0).data(Qt.ItemDataRole.UserRole) == "l1"


def test_selecting_a_lora_inspects_it_read_only():
    backend, _, _, models = make()
    dialog = ModelsDialog(models)
    dialog.search.setText("fox")
    dialog.lora_list.setCurrentRow(0)
    text = dialog.detail.toPlainText()
    assert "foxstyle" in text and "16 × 480" in text and "⚠ old format" in text
    assert all(c[0] == "GET" for c in backend.calls)  # browsing never writes


def test_inspection_failure_is_shown_in_the_detail_pane():
    backend, _, _, models = make()
    backend.fail["inspect"] = BackendError("NOT_FOUND", "file moved", 404)
    dialog = ModelsDialog(models)
    dialog.lora_list.setCurrentRow(0)
    assert "file moved" in dialog.detail.toPlainText()


def test_models_dialog_clears_when_connection_changes():
    backend, session, _, models = make()
    dialog = ModelsDialog(models)
    session.connected(info(boot="z", features=FEATURES), "tok")
    assert dialog.lora_list.count() == 0 and "connection changed" in dialog.note.text()


def test_describe_lora_without_triggers():
    from morphorum_studio.backend.loras import LoraDetail
    text = describe_lora(LoraDetail(id="a", name="Plain", family="flux"))
    assert "No trigger words recorded." in text and "Family: flux" in text
