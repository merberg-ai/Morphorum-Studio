"""Home dashboard: real values, honest unavailable states, no fake data."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from fakes import default_routes, info
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from test_dashboard import Deferred, make

from morphorum_studio.backend.client import BackendError
from morphorum_studio.ui.home_page import (
    NA,
    HomePage,
    MeterBar,
    Sparkline,
    format_bytes,
    format_mib,
    format_percent,
)


def page(routes=None, runner=None):
    kwargs = {"runner": runner} if runner else {}
    session, service, log, events, _ = make(routes, **kwargs)
    return HomePage(session, service), session, service, events


def test_format_helpers_never_invent_values():
    assert format_bytes(None) == NA and format_mib(None) == NA and format_percent(None) == NA
    assert format_bytes(512) == "512 B" and format_bytes(1536) == "1.5 KiB"
    assert format_mib(8192) == "8.0 GiB" and format_percent(71.4) == "71%"
    assert format_percent(0.0) == "0%"  # a real zero is still shown


def test_meter_clamps_and_distinguishes_unknown_from_zero():
    QApplication.instance() or QApplication([])
    meter = MeterBar()
    assert meter.fraction is None
    for given, expected in ((0.0, 0.0), (0.4, 0.4), (3.0, 1.0), (-1.0, 0.0), (None, None)):
        meter.set_fraction(given)
        assert meter.fraction == expected


def test_sparkline_keeps_only_what_it_is_given():
    QApplication.instance() or QApplication([])
    line = Sparkline()
    line.set_values([])
    assert line.values == []
    line.set_values([10, 20.5])
    assert line.values == [10.0, 20.5]


def test_offline_shows_the_empty_state_and_a_way_to_connect():
    home, session, service, events = page()
    asked = []
    home.open_connections.connect(lambda: asked.append(1))
    assert home.body.currentIndex() == 0
    assert "Connect to a Morphorum GPU backend" in home.status_line.text()
    home.connect_button.click()
    assert asked == [1]


def test_connected_page_shows_real_telemetry_and_inventory():
    home, session, service, events = page()
    session.connected(info(), "t")
    service.set_active(True)
    assert home.body.currentIndex() == 1
    values = home._backend_values
    assert values["Profile"].text() == "Workshop GPU" and values["Version"].text() == "0.1.0a1"
    assert values["Address"].text() == "http://127.0.0.1:7866" and values["Mode"].text() == "backend-only"
    assert values["Features"].text() == "3 enabled"
    assert home.gpu_name.text() == "NVIDIA GeForce RTX 4080"
    assert home.gpu_util_value.text() == "71%" and home.gpu_util_bar.fraction == pytest.approx(0.71)
    assert home.gpu_vram_value.text() == "8.0 GiB / 16.0 GiB" and home.gpu_vram_bar.fraction == 0.5
    assert home.gpu_temp.text() == "Temperature 64 °C"
    assert home.cpu_value.text() == "12%" or home.cpu_value.text() == "13%"
    assert home.ram_value.text() == "12.0 GiB / 32.0 GiB" and home.ram_bar.fraction == 0.375
    assert home.sparkline.values == [71.0]
    assert home.notice.isHidden()
    assert home.model_tree.topLevelItemCount() == 3
    assert home.model_tree.topLevelItem(0).text(0) == "Juggernaut XL"
    assert "3 indexed" in home.model_summary.text() and "SDXL 2" in home.model_summary.text()
    assert [home.family_combo.itemText(i) for i in range(home.family_combo.count())] == [
        "All families", "SDXL", "Z-Image"]


def test_no_gpu_is_stated_plainly_and_bars_stay_empty():
    routes = default_routes()
    routes["/api/system/telemetry"] = {"cpu_percent": 5.0, "gpu": {"backend": None, "devices": []}}
    home, session, service, events = page(routes)
    session.connected(info(), "t")
    service.set_active(True)
    assert home.gpu_name.text() == "No NVIDIA GPU reported"
    assert home.gpu_util_value.text() == NA and home.gpu_util_bar.fraction is None
    assert home.gpu_vram_value.text() == NA and home.gpu_vram_bar.fraction is None
    assert home.ram_value.text() == NA and home.ram_bar.fraction is None  # backend sent no RAM block
    assert home.cpu_value.text() == "5%"
    assert home.sparkline.values == []


def test_partial_gpu_data_shows_unknowns_not_zeroes():
    routes = default_routes()
    routes["/api/system/telemetry"] = {"gpu": {"backend": "nvidia", "devices": [
        {"index": 0, "name": "RTX", "memory_total_mib": 8192.0}]}}
    home, session, service, events = page(routes)
    session.connected(info(), "t")
    service.set_active(True)
    assert home.cpu_value.text() == NA and home.cpu_bar.fraction is None
    assert home.gpu_util_value.text() == NA and home.gpu_vram_value.text() == NA
    assert home.gpu_temp.text() == "Temperature " + NA


def test_telemetry_failure_warns_and_dims_the_values():
    routes = default_routes()
    home, session, service, events = page(routes)
    session.connected(info(), "t")
    service.set_active(True)
    routes["/api/system/telemetry"] = BackendError("NETWORK_ERROR", "down")
    service._poll_telemetry()
    assert not home.notice.isHidden() and "NETWORK_ERROR" in home.notice.text()
    assert home.gpu_util_value.property("stale") is True
    routes["/api/system/telemetry"] = default_routes()["/api/system/telemetry"]
    service._poll_telemetry()
    assert home.notice.isHidden() and home.gpu_util_value.property("stale") is False


def test_outage_keeps_the_last_readings_and_says_so():
    home, session, service, events = page()
    session.connected(info(), "t")
    service.set_active(True)
    session.reconnecting()
    assert home.body.currentIndex() == 1 and not home.notice.isHidden()
    assert "retrying" in home.notice.text().lower() and home.gpu_util_value.text() == "71%"
    session.connected(info(), "t")
    assert home.notice.isHidden()


def test_disconnect_returns_to_the_empty_state_and_forgets_readings():
    home, session, service, events = page()
    session.connected(info(), "t")
    service.set_active(True)
    session.disconnected()
    assert home.body.currentIndex() == 0
    assert home.gpu_util_value.text() == NA and home.model_tree.topLevelItemCount() == 0
    assert home.sparkline.values == []


def test_backend_restart_clears_old_readings_before_new_ones_arrive():
    deferred = Deferred()
    home, session, service, events = page(runner=deferred)
    session.connected(info(boot="b"), "t")
    service.set_active(True)
    deferred.complete_all()
    assert home.gpu_util_value.text() == "71%"
    session.connected(info(boot="c"), "t")
    assert home.gpu_util_value.text() == NA and home.model_tree.topLevelItemCount() == 0
    deferred.complete_all()
    assert home.gpu_util_value.text() == "71%" and home.model_tree.topLevelItemCount() == 3


def test_family_choice_filters_models_and_shows_backend_defaults():
    home, session, service, events = page()
    session.connected(info(), "t")
    home.family_combo.setCurrentIndex(1)  # SDXL
    assert service.selected_family == "sdxl"
    assert home.model_tree.topLevelItemCount() == 2
    text = home.family_defaults.text()
    assert "25 steps" in text and "CFG 6" in text and "1024×1024" in text and "euler" in text
    home.family_combo.setCurrentIndex(2)  # Z-Image: backend gave no defaults for it
    assert "did not provide" in home.family_defaults.text()
    home.family_combo.setCurrentIndex(0)
    assert home.model_tree.topLevelItemCount() == 3


def test_empty_inventory_and_failures_are_explained():
    routes = default_routes()
    routes["/api/models"] = {"models": []}
    routes["/api/models/summary"] = {"total": 0, "counts": {}}
    home, session, service, events = page(routes)
    session.connected(info(), "t")
    assert home.model_tree.topLevelItemCount() == 1
    assert "No models are indexed" in home.model_tree.topLevelItem(0).text(0)
    assert "0 indexed" in home.model_summary.text()

    routes["/api/models/families"] = BackendError("AUTH_REQUIRED", "no")
    service.refresh_now()
    assert "AUTH_REQUIRED" in home.model_summary.text()


def test_no_control_claims_to_load_or_run_a_model():
    home, *_ = page()
    from PySide6.QtWidgets import QPushButton

    labels = {b.text().lower() for b in home.findChildren(QPushButton)}
    assert labels == {"open connection settings", "refresh", "new project", "open project",
                      "generate image"}
    assert "image generation (s3)" in home.model_footer.text().lower()


def test_main_window_wires_home_session_and_polling(tmp_path):
    from morphorum_studio.ui.main_window import PAGES, StudioMainWindow
    from morphorum_studio.ui.preferences import StudioPreferences

    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat)
    window = StudioMainWindow(preferences=StudioPreferences(settings))
    try:
        names = [p[0] for p in PAGES]
        assert window.connections_panel.session is window.session
        assert window.pages.widget(names.index("Home")) is window.home_page
        assert window.dashboard._active  # Home is the start page
        window.navigation.setCurrentRow(names.index("Settings"))
        assert not window.dashboard._active
        window.navigation.setCurrentRow(names.index("Home"))
        assert window.dashboard._active
        window.home_page.connect_button.click()
        assert window.navigation.currentRow() == names.index("Settings")
    finally:
        window.close()
