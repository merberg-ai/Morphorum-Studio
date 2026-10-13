"""P2 persistence smoke tests using an isolated settings file."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from morphorum_studio.ui.preferences import StudioPreferences
from morphorum_studio.ui.startup_settings import StartupSettingsPanel


def test_preferences_and_ui_defaults(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = str(tmp_path / "settings.ini")
    prefs = StudioPreferences(QSettings(path, QSettings.Format.IniFormat))
    assert prefs.enabled("auto_connect", False) is False
    assert prefs.enabled("restore_geometry", True) is True
    prefs.set_enabled("auto_connect", True)
    prefs.set_workspace("Motion Lab")
    prefs.set_profile("last_selected", "profile-a")
    prefs.set_profile("last_successful", "profile-b")
    prefs.sync()
    restored = StudioPreferences(QSettings(path, QSettings.Format.IniFormat))
    assert restored.enabled("auto_connect", False)
    assert restored.workspace() == "Motion Lab"
    assert restored.profile("last_selected") == "profile-a"
    assert restored.profile("last_successful") == "profile-b"
    panel = StartupSettingsPanel(restored)
    try:
        assert panel.options["auto_connect"].isChecked()
        panel.options["show_splash"].setChecked(False)
        assert restored.enabled("show_splash", True) is False
    finally:
        panel.close()
        assert app is not None


def test_window_geometry_and_workspace_round_trip(tmp_path, monkeypatch):
    from morphorum_studio.ui import main_window
    from morphorum_studio.backend.profiles import ProfileStore
    from morphorum_studio.ui.connections_panel import ConnectionsPanel

    app = QApplication.instance() or QApplication([])
    original = main_window.ConnectionsPanel

    def test_panel(*args, **kwargs):
        return original(profile_store=ProfileStore(tmp_path / "profiles.json"), *args, **kwargs)

    monkeypatch.setattr(main_window, "ConnectionsPanel", test_panel)
    path = str(tmp_path / "ui.ini")
    prefs = StudioPreferences(QSettings(path, QSettings.Format.IniFormat))
    win = main_window.StudioMainWindow(preferences=prefs)
    try:
        win.resize(1044, 690)
        win.navigation.setCurrentRow(5)
        win.close()
        again = main_window.StudioMainWindow(
            preferences=StudioPreferences(QSettings(path, QSettings.Format.IniFormat))
        )
        try:
            assert again.navigation.currentRow() == 5
            assert again.size().width() == 1044
            assert again.size().height() == 690
        finally:
            again.close()
    finally:
        win.close()
        assert app is not None


def test_http_consent_is_pinned_to_exact_profile_and_url(tmp_path):
    from PySide6.QtCore import QSettings
    prefs = StudioPreferences(QSettings(str(tmp_path / "consent.ini"), QSettings.Format.IniFormat))
    assert not prefs.trusted_http("alpha", "http://host:7866")
    prefs.set_trusted_http("alpha", "http://host:7866", True)
    prefs.sync()
    again = StudioPreferences(QSettings(str(tmp_path / "consent.ini"), QSettings.Format.IniFormat))
    assert again.trusted_http("alpha", "http://host:7866")
    assert not again.trusted_http("alpha", "http://other-host:7866")
    assert not again.trusted_http("beta", "http://host:7866")
    again.set_trusted_http("alpha", "http://host:7866", False)
    assert not again.trusted_http("alpha", "http://host:7866")


def test_saved_profile_trust_survives_selection(tmp_path):
    from PySide6.QtCore import QSettings
    from morphorum_studio.backend.profiles import ProfileStore
    from morphorum_studio.ui.connections_panel import ConnectionsPanel
    app = QApplication.instance() or QApplication([])
    prefs = StudioPreferences(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    panel = ConnectionsPanel(
        profile_store=ProfileStore(tmp_path / "profiles.json"),
        preferences=prefs,
    )
    try:
        panel.name.setText("Omen")
        panel.url.setText("http://127.0.0.1:7866")
        panel.trust_http.setChecked(True)
        panel.save_profile()
        assert panel.trust_http.isChecked()
        profile = panel.selected()
        panel.selector.setCurrentIndex(0)
        panel.select_by_id(profile.id)
        assert panel.trust_http.isChecked()
        assert prefs.trusted_http(profile.id, profile.url)
    finally:
        panel.close()
        assert app is not None
