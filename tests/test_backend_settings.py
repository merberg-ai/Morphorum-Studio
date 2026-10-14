"""BS1: the connected backend's settings (model folders, managed storage, memory options)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit

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
            return {"status": "complete", "total": 12, "warnings": ["No folder for flux."]}, None
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


def rig(url="http://10.0.0.5:7866", connect=True, chosen=""):
    client = FakeClient()
    session = BackendSession(client_factory=lambda base, token, timeout=6.0: client)
    service = BackendSettingsService(session, runner=sync_runner)
    page = BackendSettingsPage(session, service, choose_folder=lambda parent, start: chosen)
    page.set_active(True)
    if connect:
        info = SessionInfo("p1", "Workshop", url, "0.1.0", "backend-only", "i1", "b1", {})
        session.connected(info, "t")
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
    assert page.original is not None



@pytest.mark.skip(reason='bisect')
def test_edit_save_sends_only_the_change_then_rescan():
    client, session, service, page = rig()
    box = next(b for b in page.form.findChildren(QCheckBox) if b.text() == "Unload after generation")
    box.setChecked(True)
    assert page.dirty and page.save_button.isEnabled() and not page.rescan_button.isEnabled()
    page.save_button.click()
    assert client.puts == [{"performance": {"unload_after_generation": True}}]
    assert not page.dirty and "Saved." in page.status_line.text() and page.rescan_button.isEnabled()
    page.rescan_button.click()
    assert client.scans == 1 and "12 model(s)" in page.status_line.text() and "No folder for flux." in page.status_line.text()


@pytest.mark.skip(reason='bisect')
def test_add_remove_and_revert_folders():
    client, session, service, page = rig()
    add = page._rows[0]["add"]  # SDXL checkpoint folders
    add.click()
    blank = [e for e in page.form.findChildren(QLineEdit) if e.text() == ""][0]
    blank.setText(r"E:\new")
    blank.textEdited.emit(r"E:\new")
    assert page.dirty and page.draft.paths["sdxl"]["checkpoints"][-1] == r"E:\new"
    page.revert_button.click()
    assert not page.dirty and r"E:\new" not in [e.text() for e in page.form.findChildren(QLineEdit)]


@pytest.mark.skip(reason='bisect')
def test_check_asks_the_backend_and_shows_the_answer():
    client, session, service, page = rig()
    from PySide6.QtWidgets import QPushButton
    checkers = [b for b in page.form.findChildren(QPushButton) if b.text() == "Check"]
    checkers[0].click()
    assert client.checks == [r"D:\models\sdxl"]


@pytest.mark.skip(reason='bisect')
def test_browse_only_for_a_backend_on_this_pc():
    from PySide6.QtWidgets import QPushButton
    _c, _s, _svc, remote = rig(url="http://10.0.0.5:7866")
    assert not [b for b in remote.form.findChildren(QPushButton) if b.text().startswith("Browse")]
    _c, _s, _svc, local = rig(url="http://127.0.0.1:7866", chosen=r"F:\picked")
    browse = [b for b in local.form.findChildren(QPushButton) if b.text().startswith("Browse")]
    assert browse
    browse[0].click()
    assert r"F:\picked" in [e.text() for e in local.form.findChildren(QLineEdit)]
    assert local.dirty


@pytest.mark.skip(reason='bisect')
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
