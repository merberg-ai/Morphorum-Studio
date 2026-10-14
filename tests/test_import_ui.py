"""Deforum import service and dialog against a scripted fake backend (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtWidgets import QApplication, QFileDialog
from test_import_validation_api import PREVIEW

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.deforum_dialog import DeforumImportDialog
from morphorum_studio.ui.import_service import ImportService

FEATURES = {"project_crud": True, "model_discovery": True}


class Backend:
    def __init__(self):
        self.posts = []
        self.preview = dict(PREVIEW)
        self.fail = None


class Client:
    def __init__(self, backend):
        self.b = backend

    def get_json(self, path, params=None):
        assert path == "/api/models" and params["kind"] == "checkpoints"
        return {"models": [{"id": "m1", "family": "sdxl", "kind": "checkpoints", "name": "Juggernaut"},
                           {"id": "m2", "family": "flux", "kind": "checkpoints", "name": "Flux Dev"}]}

    def send_json(self, method, path, body=None, *, if_match=None, idempotency_key=None, max_bytes=0):
        self.b.posts.append((path, body))
        if self.b.fail:
            raise self.b.fail
        if path.endswith("/preview"):
            ready = bool(body.get("model_id"))
            return {**self.b.preview, "model_required": not ready, "can_create": ready}, None
        return {"status": "created", "project": {"id": "imported-1", "name": "Imported"},
                "import": {"warnings": ["w"]}}, None


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def make(tmp_path, monkeypatch, content='{"max_frames": 120}'):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    backend = Backend()
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(backend))
    service = ImportService(session, runner=sync_runner)
    session.connected(info(features=FEATURES), "tok")
    settings = tmp_path / "settings.txt"
    settings.write_text(content)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(settings), ""))
    dialog = DeforumImportDialog(service)
    return backend, session, service, dialog


def test_checkpoints_load_and_nothing_is_enabled_without_a_file(tmp_path, monkeypatch):
    backend, _, service, dialog = make(tmp_path, monkeypatch)
    assert dialog.model.count() == 3 and "Juggernaut" in dialog.model.itemText(1)
    assert not dialog.preview_button.isEnabled() and not dialog.create_button.isEnabled()


def test_preview_without_checkpoint_cannot_create_and_explains(tmp_path, monkeypatch):
    backend, _, service, dialog = make(tmp_path, monkeypatch)
    dialog.file_button.click()
    assert dialog.preview_button.isEnabled()
    dialog.preview_button.click()
    assert "Choose a checkpoint" in dialog.summary.text() and not dialog.create_button.isEnabled()
    assert dialog.table.rowCount() == 3 and dialog.table.item(1, 2).text().startswith("ignored path")
    assert "120 frames" in dialog.summary.text() and "512×768" in dialog.summary.text()
    assert dialog.warnings.count() >= 3  # the validation warning plus the backend warnings


def test_preview_with_checkpoint_enables_create_and_changes_invalidate(tmp_path, monkeypatch):
    backend, _, service, dialog = make(tmp_path, monkeypatch)
    created = []
    dialog.project_created.connect(created.append)
    dialog.file_button.click()
    dialog.model.setCurrentIndex(1)
    dialog.preview_button.click()
    assert backend.posts[-1][1]["model_id"] == "m1" and dialog.create_button.isEnabled()
    dialog.model.setCurrentIndex(2)  # a different checkpoint: the preview no longer applies
    assert not dialog.create_button.isEnabled() and dialog.table.rowCount() == 0
    dialog.preview_button.click()
    dialog.name.setText("Another")
    assert not dialog.create_button.isEnabled()
    dialog.preview_button.click()
    dialog.create_button.click()
    path, body = backend.posts[-1]
    assert path.endswith("/import/deforum/create") and body["model_id"] == "m2" and body["name"] == "Another"
    assert created == ["imported-1"]


def test_bad_file_is_reported_and_backend_errors_are_shown(tmp_path, monkeypatch):
    backend, _, service, dialog = make(tmp_path, monkeypatch, content="")
    dialog.file_button.click()
    assert "between 1 byte and 1 MiB" in dialog.summary.text() and not dialog.preview_button.isEnabled()
    settings = tmp_path / "ok.txt"
    settings.write_text("{}")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(settings), ""))
    dialog.file_button.click()
    backend.fail = BackendError("INVALID_REQUEST", "Backend returned HTTP 400: not Deforum settings", 400)
    dialog.preview_button.click()
    assert "not Deforum settings" in dialog.summary.text()


def test_disconnect_disables_actions(tmp_path, monkeypatch):
    backend, session, service, dialog = make(tmp_path, monkeypatch)
    dialog.file_button.click()
    session.disconnected()
    dialog._update()
    assert not dialog.preview_button.isEnabled() and not dialog.create_button.isEnabled()
