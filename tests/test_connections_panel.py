"""S1.2 native panel acceptance without network access."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from morphorum_studio.backend.profiles import ProfileStore
from morphorum_studio.ui.connections_panel import ConnectionsPanel


class FakeVault:
    def __init__(self):
        self.items = {}

    def get(self, key):
        return self.items.get(key)

    def set(self, key, value):
        self.items[key] = value

    def delete(self, key):
        self.items.pop(key, None)


def test_native_profiles_and_safe_offline(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = ProfileStore(tmp_path / "profiles.json")
    vault = FakeVault()
    panel = ConnectionsPanel(profile_store=store, credential_store=vault)
    try:
        assert panel.selector.count() == 1
        panel.name.setText("Omen backend")
        panel.url.setText("http://127.0.0.1:7866/")
        panel.save_profile()
        assert panel.selector.count() == 2
        assert store.load()[0].name == "Omen backend"
        panel.disconnect()
        assert "Disconnected" in panel.details.text()
        panel.new_profile()
        assert panel.name.text() == ""
    finally:
        panel.close()
        assert app is not None


def test_import_host_token_file(tmp_path, monkeypatch):
    from morphorum_studio.ui import connections_panel as module

    app = QApplication.instance() or QApplication([])
    store = ProfileStore(tmp_path / "profiles.json")
    vault = FakeVault()
    panel = ConnectionsPanel(profile_store=store, credential_store=vault)
    token_file = tmp_path / "issued.token"
    token_file.write_text("local-test-secret-token", encoding="utf-8")
    try:
        panel.name.setText("GPU host")
        panel.url.setText("http://127.0.0.1:7866")
        panel.save_profile()
        profile = panel.selected()
        assert not panel.trust_http.isChecked()
        monkeypatch.setattr(module.QFileDialog, "getOpenFileName",
                            lambda *a, **k: (str(token_file), "Token files"))
        panel.import_token_file()
        assert vault.get(profile.id) == "local-test-secret-token"
        assert not panel.trust_http.isChecked()  # Browsing a local file needs no network approval
        assert "token" not in store.path.read_text().lower()
        assert "imported" in panel.details.text().lower()
    finally:
        panel.close()
        assert app is not None


def test_disconnect_ignores_late_probe_result(tmp_path):
    from types import SimpleNamespace
    app = QApplication.instance() or QApplication([])
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"),
        credential_store=FakeVault(),
    )
    try:
        panel.name.setText("Backend")
        panel.url.setText("http://127.0.0.1:7866")
        panel.save_profile()
        profile = panel.selected()
        panel._epoch = 4
        panel.disconnect()
        result = SimpleNamespace(
            instance_id="a" * 32, boot_id="b" * 32, version="0.1",
            mode="backend-only", features={"render": True},
        )
        panel._discovery_done(profile.id, 4, False, result, None)
        assert not panel._monitor.isActive()
        assert panel._connected_profile is None
        assert "OFFLINE" not in panel.details.text()  # Disconnected message stays.
        assert not profile.instance_id
    finally:
        panel.close()
        assert app is not None


def test_auth_failure_stops_monitor(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"),
        credential_store=FakeVault(),
    )
    try:
        panel.name.setText("Backend")
        panel.url.setText("http://127.0.0.1:7866")
        panel.save_profile()
        profile = panel.selected()
        panel._connected_profile = profile.id
        panel._monitor.start()
        panel._epoch = 10
        panel._discovery_done(profile.id, 10, True, None, ("AUTH_REQUIRED", "401"))
        assert not panel._monitor.isActive()
        assert panel._connected_profile is None
        assert "Authentication rejected" in panel.details.text()
    finally:
        panel.close()
        assert app is not None


def test_network_outage_retries_without_reauthentication_prompt(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"),
        credential_store=FakeVault(),
    )
    try:
        panel.name.setText("Omen")
        panel.url.setText("http://127.0.0.1:7866")
        panel.save_profile()
        profile = panel.selected()
        panel._connected_profile = profile.id
        panel._epoch = 20
        panel._discovery_done(profile.id, 20, True, None, ("NETWORK_ERROR", "offline"))
        assert panel._connected_profile == profile.id
        assert panel._monitor.isActive()
        assert panel._monitor.interval() == 10000
        assert "Retrying" in panel.details.text()
        panel.disconnect()
        assert not panel._monitor.isActive()
    finally:
        panel.close()
        assert app is not None


def test_wrong_and_revoked_tokens_fail_closed(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"),
        credential_store=FakeVault(),
    )
    messages = []
    panel.status_changed.connect(messages.append)
    try:
        panel.name.setText("Test")
        panel.url.setText("http://127.0.0.1:7866")
        panel.save_profile()
        profile = panel.selected()
        for reason in ("AUTH_REQUIRED", "FORBIDDEN"):
            panel._connected_profile = profile.id
            panel._monitor.start()
            panel._epoch += 1
            panel._discovery_done(profile.id, panel._epoch, True, None, (reason, "Unauthorized"))
            assert messages[-1] == "BACKEND UNAUTHORIZED"
            assert not panel._monitor.isActive()
            assert panel._connected_profile is None
            assert not profile.instance_id
    finally:
        panel.close()
        assert app is not None


def test_identity_mismatch_refusal_preserves_pinned_host(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QMessageBox
    app = QApplication.instance() or QApplication([])
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"),
        credential_store=FakeVault(),
    )
    statuses = []
    panel.status_changed.connect(statuses.append)
    try:
        panel.name.setText("Test")
        panel.url.setText("http://127.0.0.1:7866")
        panel.save_profile()
        profile = panel.selected()
        profile.instance_id = "a" * 32
        profile.boot_id = "b" * 32
        panel.store.save(panel.profiles)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No)
        result = SimpleNamespace(
            instance_id="c" * 32, boot_id="d" * 32, version="0.1",
            mode="backend-only", features={"render": True},
        )
        panel._epoch += 1
        panel._discovery_done(profile.id, panel._epoch, False, result, None)
        assert statuses[-1] == "BACKEND IDENTITY MISMATCH"
        assert profile.instance_id == "a" * 32
        assert profile.boot_id == "b" * 32
        assert panel.store.load()[0].instance_id == "a" * 32
        assert not panel._monitor.isActive()
    finally:
        panel.close()
        assert app is not None
