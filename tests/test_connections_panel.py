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
        panel.trust_http.setChecked(True)
        monkeypatch.setattr(module.QFileDialog, "getOpenFileName",
                            lambda *a, **k: (str(token_file), "Token files"))
        panel.import_token_file()
        assert vault.get(profile.id) == "local-test-secret-token"
        assert "token" not in store.path.read_text().lower()
        assert "imported" in panel.details.text().lower()
    finally:
        panel.close()
        assert app is not None
