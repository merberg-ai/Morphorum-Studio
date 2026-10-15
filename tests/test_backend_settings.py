"""BS1: the connected backend's settings (model folders, managed storage, memory options)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QPushButton

from morphorum_studio.backend.backend_settings import (
    SettingsApi,
    build_update,
    parse_settings,
)
from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession, SessionInfo
from morphorum_studio.ui.backend_settings_page import BackendSettingsPage
from morphorum_studio.ui.backend_settings_service import BackendSettingsService

QApplication.instance() or QApplication(["morphorum-studio-tests"])

FAMILIES = [
    {"id": "sdxl", "label": "SDXL", "supports_loras": True, "source": "external", "lora_source": "external"},
    {"id": "flux", "label": "Flux", "supports_loras": True, "source": "external", "lora_source": "external"},
    {"id": "zimage", "label": "Z-Image", "supports_loras": True, "source": "managed", "lora_source": "external"},
]


def payload():
    return {
        "settings": {
            "ui": {"theme": "midnight-glass", "image_preview_limit": 5},
            "models": {
                "sdxl": {"label": "SDXL", "checkpoints": [r"D:\models\sdxl"], "loras": []},
                "flux": {"label": "Flux", "checkpoints": [], "loras": []},
                "zimage": {"label": "Z-Image", "loras": [r"D:\loras"]},
            },
            "managed_models": {"locations": {"zimage": r".\ckpts\z-image"}},
            "performance": {"unload_after_generation": False, "sdxl_vae_tiling": True},
        },
        "validation": [
            {"path": r"D:\models\sdxl", "family": "sdxl", "kind": "checkpoints", "exists": True,
             "is_directory": True, "readable": True},
            {"path": r"D:\loras", "family": "zimage", "kind": "loras", "exists": False,
             "is_directory": False, "readable": False},
        ],
        "model_families": FAMILIES,
    }


class FakeClient:
    def __init__(self):
        self.puts, self.checks, self.scans, self.fail = [], [], 0, None
        self.scan_total = 12
        self.state = payload()

    def get_json(self, path, params=None):
        if self.fail:
            raise BackendError("UNAVAILABLE", self.fail)
        assert path == "/api/settings"
        return copy.deepcopy(self.state)

    def send_json(self, method, path, body=None, **kw):
        if self.fail:
            raise BackendError("UNAVAILABLE", self.fail)
        if path == "/api/settings":
            assert method == "PUT"
            self.puts.append(copy.deepcopy(body))
            _merge(self.state["settings"], body)
            return {"status": "saved", **copy.deepcopy(self.state)}, None
        if path == "/api/settings/validate-path":
            self.checks.append(body["path"])
            return {"path": body["path"], "exists": True, "is_directory": True, "readable": True}, None
        if path == "/api/models/scan":
            self.scans += 1
            return {"status": "complete", "total": self.scan_total, "warnings": ["No folder for flux."],
                    "counts": {"sdxl": {"checkpoints": 8, "loras": 4}}}, None
        raise AssertionError(path)


def _merge(base, update):
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


_MADE = []


@pytest.fixture(autouse=True)
def _destroy_widgets():
    """Delete each test's Qt objects before the next test, while Qt is healthy (see tests/conftest.py)."""
    yield
    from shiboken6 import delete, isValid

    while _MADE:
        for obj in _MADE.pop():
            if isValid(obj):
                delete(obj)
    QApplication.processEvents()


def rig(url="http://10.0.0.5:7866", connect=True, chosen=""):
    client = FakeClient()
    def factory(base, token, timeout=6.0):
        if not 0 < timeout <= 60:  # the real BackendClient refuses anything else
            raise ValueError("timeout must be in (0, 60] seconds")
        return client

    session = BackendSession(client_factory=factory)
    service = BackendSettingsService(session, runner=sync_runner)
    page = BackendSettingsPage(session, service, choose_folder=lambda parent, start: chosen)
    page.set_active(True)
    if connect:
        info = SessionInfo("p1", "Workshop", url, "0.1.0", "backend-only", "i1", "b1", {})
        session.connected(info, "t")
    _MADE.append((page, service, session))
    return client, session, service, page


# ------------------------------------------------------------------ parsing and updates

def test_parse_reads_families_paths_storage_flags_and_checks():
    data = parse_settings(payload())
    assert [f.id for f in data.families] == ["sdxl", "flux", "zimage"]
    assert data.paths["sdxl"] == {"checkpoints": [r"D:\models\sdxl"], "loras": []}
    assert "checkpoints" not in data.paths["zimage"] and data.paths["zimage"]["loras"] == [r"D:\loras"]
    assert data.managed == {"zimage": r".\ckpts\z-image"}
    assert data.flags == {"unload_after_generation": False, "sdxl_vae_tiling": True}
    assert data.checks[("sdxl", "checkpoints")][0].ok
    assert not data.checks[("zimage", "loras")][0].ok and "does not exist" in data.checks[("zimage", "loras")][0].message


def test_parse_is_defensive():
    with pytest.raises(BackendError):
        parse_settings([])
    bad = payload()
    bad["model_families"] = []
    with pytest.raises(BackendError):
        parse_settings(bad)
    odd = payload()
    odd["settings"]["models"] = {"sdxl": {"checkpoints": "not a list"}}
    odd["settings"]["performance"] = {"sdxl_vae_tiling": "yes"}
    odd["validation"] = "nope"
    data = parse_settings(odd)
    assert data.paths["sdxl"]["checkpoints"] == [] and data.flags["sdxl_vae_tiling"] is False


def test_only_changes_are_sent():
    before = parse_settings(payload())
    assert build_update(before, before.copy()) == {}
    after = before.copy()
    after.paths["sdxl"]["checkpoints"].append("  E:\\more  ")
    after.paths["flux"]["checkpoints"].append("   ")  # a blank row is nothing
    after.managed["zimage"] = r"E:\z"
    after.flags["unload_after_generation"] = True
    assert build_update(before, after) == {
        "models": {"sdxl": {"checkpoints": [r"D:\models\sdxl", r"E:\more"]}},
        "managed_models": {"locations": {"zimage": r"E:\z"}},
        "performance": {"unload_after_generation": True},
    }
    cleared = before.copy()
    cleared.managed["zimage"] = ""
    assert build_update(before, cleared) == {}  # the backend always keeps a storage folder


def test_web_only_settings_are_never_sent():
    before = parse_settings(payload())
    assert "ui" not in build_update(before, before.copy())


# ------------------------------------------------------------------ page

def test_not_connected_shows_a_message_and_no_form():
    _c, _s, _svc, page = rig(connect=False)
    assert "Connect to a backend" in page.status_line.text()
    assert not page.form.isVisibleTo(page) and not page.footer.isVisibleTo(page)


def test_loads_when_shown_active_and_builds_the_form():
    client, session, service, page = rig(connect=False)
    info = SessionInfo("p1", "W", "http://10.0.0.5:7866", "0.1.0", "backend-only", "i1", "b1", {})
    session.connected(info, "t")  # visible page + connected -> loads
    assert page.original is not None and page.form.isVisibleTo(page)
    assert [e.text() for e in page.form.findChildren(QLineEdit)] == [r"D:\models\sdxl", "", "", "", r"D:\loras", r".\ckpts\z-image"]
    boxes = {b.text(): b.isChecked() for b in page.form.findChildren(QCheckBox)}
    assert boxes == {"Unload after generation": False, "SDXL VAE tiling": True}
    assert not page.save_button.isEnabled()
    messages = " ".join(label.text() for label in page.form.findChildren(QLabel))
    assert r"OK: D:\models\sdxl - Folder found." in messages
    assert r"Problem: D:\loras - This folder does not exist yet." in messages



def test_edit_save_sends_only_the_change_then_rescan():
    client, session, service, page = rig()
    box = next(b for b in page.form.findChildren(QCheckBox) if b.text() == "Unload after generation")
    box.setChecked(True)
    assert page.dirty and page.save_button.isEnabled() and not page.rescan_button.isEnabled()
    page.save_button.click()
    assert client.puts == [{"performance": {"unload_after_generation": True}}]
    assert not page.dirty and "Saved." in page.status_line.text() and page.rescan_button.isEnabled()
    assert client.scans == 0  # a memory option does not change what is on disk
    changed = []
    page.models_changed.connect(lambda: changed.append(1))
    page.rescan_button.click()
    text = page.status_line.text()
    assert client.scans == 1 and changed == [1]
    assert "12 file(s)" in text and "SDXL checkpoints: 8" in text and "SDXL loras: 4" in text
    assert "No folder for flux." in text


def test_saving_folders_rescans_by_itself_and_tells_the_app():
    client, session, service, page = rig()
    changed = []
    page.models_changed.connect(lambda: changed.append(1))
    edit = page._rows[0]["edit"]
    page._rows[0]["add_path"](r"E:\more")
    page._rows[0]["edits"][1].setText(r"E:\more")
    page._rows[0]["edits"][1].textEdited.emit(r"E:\more")
    page.save_button.click()
    assert client.puts and client.scans == 1 and changed == [1]
    assert "Rescan finished" in page.status_line.text()


def test_an_empty_scan_explains_what_files_are_expected():
    client, session, service, page = rig()
    client.scan_total = 0
    page._rows[0]["edit"].setText(r"D:\empty")
    page._rows[0]["edit"].textEdited.emit(r"D:\empty")
    page.save_button.click()
    assert ".safetensors" in page.status_line.text() and "no models" in page.status_line.text()


def test_edit_folders_and_revert():
    client, session, service, page = rig()
    edit = page._rows[0]["edit"]  # SDXL checkpoint folders
    page._rows[0]["add_path"](r"E:\new")
    page._rows[0]["edits"][1].textEdited.emit(r"E:\new")
    assert page.dirty and page.draft.paths["sdxl"]["checkpoints"] == [r"D:\models\sdxl", r"E:\new"]
    page.save_button.click()
    assert client.puts == [{"models": {"sdxl": {"checkpoints": [r"D:\models\sdxl", r"E:\new"]}}}]
    page._rows[0]["edit"].setText("")
    page._rows[0]["edit"].textEdited.emit("")
    assert page.dirty
    page.revert_button.click()
    assert not page.dirty and [e.text() for e in page._rows[0]["edits"]] == [r"D:\models\sdxl", r"E:\new"]


def test_check_asks_the_backend_and_shows_the_answer():
    client, session, service, page = rig()
    checkers = [b for b in page.form.findChildren(QPushButton) if b.text() == "Check folders"]
    checkers[0].click()
    assert client.checks == [r"D:\models\sdxl"]
    assert "Folder found." in page._rows[0]["message"].text()


def test_browse_only_for_a_backend_on_this_pc():
    _c, _s, _svc, remote = rig(url="http://10.0.0.5:7866")
    assert not [b for b in remote.form.findChildren(QPushButton) if b.text().startswith("Browse")]
    _c, _s, _svc, local = rig(url="http://127.0.0.1:7866", chosen=r"F:\picked")
    add = [b for b in local.form.findChildren(QPushButton) if b.text().startswith("Add folder")]
    assert add
    add[0].click()
    assert local.draft.paths["sdxl"]["checkpoints"] == [r"D:\models\sdxl", r"F:\picked"] and local.dirty
    browse = [b for b in local.form.findChildren(QPushButton) if b.text().startswith("Browse")]
    assert browse  # the managed storage row


def test_failures_are_explained_and_a_disconnect_clears_the_form():
    client, session, service, page = rig()
    client.fail = "backend is busy"
    page.reload_button.click()
    assert "backend is busy" in page.status_line.text()
    session.disconnected()
    assert page.original is None and not page.form.isVisibleTo(page)
    assert "Connect to a backend" in page.status_line.text()


def test_api_save_requires_confirmation():
    class Odd(FakeClient):
        def send_json(self, method, path, body=None, **kw):
            return {"status": "nope"}, None

    with pytest.raises(BackendError):
        SettingsApi(Odd()).save({"performance": {"sdxl_vae_tiling": True}})
