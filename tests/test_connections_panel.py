"""S1.2 native panel acceptance without network access."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
from morphorum_studio.backend.profiles import ProfileStore
from morphorum_studio.ui.connections_panel import TRANSIENT_ERRORS, ConnectionsPanel
from morphorum_studio.ui.preferences import StudioPreferences


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


# --- Hardening regressions -------------------------------------------------------------

def _result(instance="a", boot="b"):
    from types import SimpleNamespace
    return SimpleNamespace(
        instance_id=instance * 32, boot_id=boot * 32, version="0.1",
        mode="backend-only", features={"render": True},
    )


def _saved_panel(tmp_path, preferences=None):
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"),
        credential_store=FakeVault(),
        preferences=preferences,
    )
    panel.name.setText("Omen")
    panel.url.setText("http://127.0.0.1:7866")
    panel.save_profile()
    return panel, panel.selected()


@pytest.mark.parametrize("code", sorted(TRANSIENT_ERRORS))
def test_transient_backend_errors_keep_monitoring(tmp_path, code):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    try:
        panel._connected_profile = profile.id
        panel._epoch = 1
        panel._discovery_done(profile.id, 1, True, None, (code, "backend restarting"))
        assert panel._monitor.isActive()
        assert panel._connected_profile == profile.id
        assert "Retrying" in panel.details.text() and code in panel.details.text()
    finally:
        panel.close()
        assert app is not None


@pytest.mark.parametrize("code", ["NOT_FOUND", "VALIDATION_ERROR", "REDIRECT_REJECTED"])
def test_non_transient_errors_stop_monitoring(tmp_path, code):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    try:
        panel._connected_profile = profile.id
        panel._monitor.start()
        panel._epoch = 1
        panel._discovery_done(profile.id, 1, True, None, (code, "nope"))
        assert not panel._monitor.isActive()
        assert panel._connected_profile is None
    finally:
        panel.close()
        assert app is not None


def test_profile_file_is_written_only_when_identity_changes(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    saves = []
    real_save = panel.store.save
    monkeypatch.setattr(panel.store, "save", lambda profiles: (saves.append(1), real_save(profiles)))
    try:
        for _ in range(3):  # Three identical health probes.
            panel._epoch += 1
            panel._discovery_done(profile.id, panel._epoch, True, _result(), None)
        assert len(saves) == 1
        panel._epoch += 1
        panel._discovery_done(profile.id, panel._epoch, True, _result(boot="c"), None)
        assert len(saves) == 2
    finally:
        panel.close()
        assert app is not None


def test_failed_profile_save_does_not_drop_a_working_connection(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    statuses = []
    panel.status_changed.connect(statuses.append)

    def locked(profiles):
        raise OSError("file is locked")

    monkeypatch.setattr(panel.store, "save", locked)
    try:
        panel._epoch += 1
        panel._discovery_done(profile.id, panel._epoch, False, _result(), None)
        assert statuses[-1] == "BACKEND CONNECTED"
        assert panel._connected_profile == profile.id
        assert panel._monitor.isActive()
        assert "could not be saved" in panel.details.text()
    finally:
        panel.close()
        assert app is not None


def test_backend_restart_notice_survives_later_probes(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    try:
        for boot in ("b", "b", "c", "c", "c"):
            panel._epoch += 1
            panel._discovery_done(profile.id, panel._epoch, True, _result(boot=boot), None)
        assert "Backend restarted" in panel.details.text()
        panel.disconnect()
        assert not panel._restart_notice
        assert "restarted" not in panel.details.text()
    finally:
        panel.close()
        assert app is not None


def test_connection_succeeded_is_emitted_once_per_connection(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    seen = []
    panel.connection_succeeded.connect(seen.append)
    try:
        for _ in range(3):
            panel._epoch += 1
            panel._discovery_done(profile.id, panel._epoch, True, _result(), None)
        assert seen == [profile.id]
    finally:
        panel.close()
        assert app is not None


def test_identity_dialog_pauses_health_probes(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    profile.instance_id, profile.boot_id = "a" * 32, "b" * 32
    monitor_active_while_dialog_open = []

    def fake_warning(*args, **kwargs):
        monitor_active_while_dialog_open.append(panel._monitor.isActive())
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    try:
        panel._connected_profile = profile.id
        panel._monitor.start()
        panel._epoch += 1
        panel._discovery_done(profile.id, panel._epoch, True, _result(instance="c"), None)
        assert monitor_active_while_dialog_open == [False]  # No stacked dialogs.
        assert not panel._monitor.isActive()
    finally:
        panel.close()
        assert app is not None


def test_editing_url_withdraws_http_trust(tmp_path):
    app = QApplication.instance() or QApplication([])
    prefs = StudioPreferences(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"),
        credential_store=FakeVault(), preferences=prefs,
    )
    try:
        panel.name.setText("Omen")
        panel.url.setText("http://127.0.0.1:7866")
        panel.trust_http.setChecked(True)
        panel.save_profile()
        profile = panel.selected()
        assert panel.trust_http.isChecked() and prefs.trusted_http(profile.id, profile.url)
        panel.url.setText("http://127.0.0.1:7866/")  # Same address, different spelling.
        assert panel.trust_http.isChecked()
        panel.url.setText("http://10.0.0.9:7866")
        assert not panel.trust_http.isChecked()
        panel.save_profile()
        profile = panel.selected()
        assert profile.url == "http://10.0.0.9:7866"
        assert not prefs.trusted_http(profile.id, profile.url)
        assert not panel.trust_http.isChecked()
    finally:
        panel.close()
        assert app is not None


def test_background_probe_does_not_block_profile_actions(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    try:
        panel._monitor_inflight = True  # A health probe is running in the background.
        panel.name.setText("Renamed")
        panel.save_profile()
        assert panel.selected().name == "Renamed"
    finally:
        panel.close()
        assert app is not None


def test_actions_explain_themselves_while_connecting(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    try:
        panel._connecting = True
        panel.remove_profile()
        assert "in progress" in panel.details.text()
        assert panel.selected() is not None and len(panel.profiles) == 1
        panel.disconnect()  # Disconnect cancels the attempt and unlocks the form.
        assert not panel._connecting and panel.selector.isEnabled()
    finally:
        panel.close()
        assert app is not None


def test_monitor_tick_never_overlaps_another_probe(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel, profile = _saved_panel(tmp_path)
    calls = []
    monkeypatch.setattr(panel, "_probe", lambda *a, **k: calls.append(k))
    try:
        panel._connected_profile = profile.id
        panel._monitor_inflight = True
        panel._monitor_tick()
        panel._monitor_inflight, panel._connecting = False, True
        panel._monitor_tick()
        assert calls == []
        panel._connecting = False
        panel._monitor_tick()
        assert calls == [{"monitoring": True}]
    finally:
        panel.close()
        assert app is not None


def test_panel_starts_with_a_warning_when_profile_file_is_corrupt(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "profiles.json"
    path.write_text("{not json", encoding="utf-8")
    panel = ConnectionsPanel(profile_store=ProfileStore(path), credential_store=FakeVault())
    try:
        assert panel.selector.count() == 1
        assert "could not be read" in panel.details.text()
        assert list(tmp_path.glob("profiles.json.recovered-*"))
    finally:
        panel.close()
        assert app is not None


def _layout_panel(tmp_path):
    from morphorum_studio.ui.theme import DARK_STYLESHEET

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(DARK_STYLESHEET)
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"), credential_store=FakeVault()
    )
    panel.resize(1000, 760)
    panel.show()
    app.processEvents()
    return app, panel


def test_buttons_keep_their_natural_size_instead_of_stretching(tmp_path):
    app, panel = _layout_panel(tmp_path)
    try:
        for button in (panel.import_button, panel.save_button, panel.test_button,
                       panel.disconnect_button, panel.remove_button, panel.new_button):
            assert button.width() <= button.sizeHint().width() + 40, button.text()
        # Actions share one row, in order, without overlapping.
        row = [panel.remove_button, panel.save_button, panel.disconnect_button, panel.test_button]
        lefts = [b.mapTo(panel, b.rect().topLeft()).x() for b in row]
        assert lefts == sorted(lefts)
        for left, right in zip(row, row[1:]):
            gap = right.mapTo(panel, right.rect().topLeft()).x() - (
                left.mapTo(panel, left.rect().topLeft()).x() + left.width())
            assert gap >= 8
    finally:
        panel.close()
        app.setStyleSheet("")
        assert app is not None


def test_token_help_is_collapsed_until_asked_for_and_command_copies(tmp_path):
    app, panel = _layout_panel(tmp_path)
    try:
        assert not panel.help_panel.isVisible()
        panel.help_toggle.click()
        assert panel.help_panel.isVisible()
        panel.copy_button.click()
        assert QApplication.clipboard().text() == panel.issue_command.text()
        assert "morphorum clients issue" in panel.issue_command.text()
        panel.help_toggle.click()
        assert not panel.help_panel.isVisible()
    finally:
        panel.close()
        app.setStyleSheet("")
        assert app is not None
