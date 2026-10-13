"""Dashboard refresh service: polling rules, stale results and failure handling."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from fakes import FakeClient, default_routes, info
from PySide6.QtWidgets import QApplication

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import DashboardService


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


class Deferred:
    """Collects requests so a test decides when (and whether) each one completes."""

    def __init__(self):
        self.pending = []

    def __call__(self, client, fn, callback):
        self.pending.append((client, fn, callback))

    def complete_all(self):
        batch, self.pending = self.pending, []
        for client, fn, callback in batch:
            try:
                callback(fn(client), None)
            except BackendError as exc:
                callback(None, (exc.code, str(exc)))


def make(routes=None, runner=sync_runner):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    log, tokens = [], []

    def factory(url, token, timeout=6.0):
        tokens.append(token)
        return FakeClient(routes if routes is not None else default_routes(), log)

    session = BackendSession(client_factory=factory)
    service = DashboardService(session, runner=runner)
    events = {"telemetry": [], "failed": [], "models": [], "models_failed": [], "cleared": []}
    service.telemetry_updated.connect(events["telemetry"].append)
    service.telemetry_failed.connect(events["failed"].append)
    service.models_updated.connect(lambda c, sel: events["models"].append((c, sel)))
    service.models_failed.connect(events["models_failed"].append)
    service.cleared.connect(lambda: events["cleared"].append(1))
    return session, service, log, events, tokens


def paths(log):
    return [p for p, _ in log]


def test_models_load_on_connect_but_telemetry_waits_until_the_page_is_active():
    session, service, log, events, tokens = make()
    session.connected(info(), "secret")
    assert len(events["models"]) == 1 and events["telemetry"] == []
    assert "/api/system/telemetry" not in paths(log)
    assert tokens and set(tokens) == {"secret"}
    catalog, (family, models) = events["models"][0]
    assert family is None and len(models) == 3
    assert [f.id for f in catalog.families] == ["sdxl", "zimage"] and catalog.summary.total == 3
    assert catalog.defaults["sdxl"].steps_default == 25

    service.set_active(True)
    assert len(events["telemetry"]) == 1 and service._telemetry_timer.isActive()
    service.set_active(False)
    assert not service._telemetry_timer.isActive() and not service._models_timer.isActive()


def test_offline_session_makes_no_requests():
    session, service, log, events, _ = make()
    service.set_active(True)
    service.refresh_now()
    service.select_family("sdxl")
    assert log == [] and events["telemetry"] == [] and events["models"] == []


def test_late_results_from_a_dropped_connection_are_discarded():
    deferred = Deferred()
    session, service, log, events, _ = make(runner=deferred)
    session.connected(info(), "t")
    service.set_active(True)
    assert len(deferred.pending) == 2  # models + telemetry
    cleared = len(events["cleared"])
    session.disconnected()
    deferred.complete_all()
    assert events["telemetry"] == [] and events["models"] == []
    assert len(events["cleared"]) == cleared + 1 and service.catalog is None


def test_late_results_from_a_previous_boot_are_discarded_and_state_reloads():
    deferred = Deferred()
    session, service, log, events, _ = make(runner=deferred)
    session.connected(info(boot="b"), "t")
    service.set_active(True)
    old = deferred.pending[:]
    deferred.pending = []
    cleared = len(events["cleared"])
    session.connected(info(boot="c"), "t")  # backend restarted
    assert len(events["cleared"]) == cleared + 1
    for client, fn, callback in old:
        callback(fn(client), None)  # arrives late
    assert events["telemetry"] == [] and events["models"] == []
    deferred.complete_all()  # the requests made for the new boot
    assert len(events["models"]) == 1 and len(events["telemetry"]) == 1


def test_outage_pauses_polling_and_recovery_resumes_without_clearing():
    session, service, log, events, _ = make()
    session.connected(info(), "t")
    service.set_active(True)
    before, cleared = len(log), len(events["cleared"])
    session.reconnecting()
    assert not service._telemetry_timer.isActive()
    service._poll_telemetry()
    service.refresh_models()
    assert len(log) == before
    session.connected(info(), "t")
    assert len(log) > before and len(events["cleared"]) == cleared
    assert len(events["telemetry"]) == 2


def test_telemetry_failures_back_off_and_report_the_code():
    routes = default_routes()
    routes["/api/system/telemetry"] = BackendError("NETWORK_ERROR", "down")
    session, service, log, events, _ = make(routes)
    session.connected(info(), "t")
    service.set_active(True)
    assert events["failed"] == ["NETWORK_ERROR"] and service._telemetry_timer.interval() == 6000
    service._poll_telemetry()
    assert service._telemetry_timer.interval() == 12000
    service._poll_telemetry()
    assert service._telemetry_timer.interval() == 15000  # capped
    routes["/api/system/telemetry"] = default_routes()["/api/system/telemetry"]
    service._poll_telemetry()
    assert len(events["telemetry"]) == 1 and service._telemetry_timer.interval() == 3000


def test_requests_never_overlap():
    deferred = Deferred()
    session, service, log, events, _ = make(runner=deferred)
    session.connected(info(), "t")
    service.set_active(True)
    count = len(deferred.pending)
    service._poll_telemetry()
    service._poll_telemetry()
    service.refresh_models()
    assert len(deferred.pending) == count


def test_features_the_backend_does_not_advertise_are_not_requested():
    session, service, log, events, _ = make()
    session.connected(info(features={"model_discovery": True}), "t")
    service.set_active(True)
    assert "/api/system/telemetry" not in paths(log) and "/api/models" in paths(log)

    session2, service2, log2, events2, _ = make()
    session2.connected(info(features={"gpu_telemetry": True}), "t")
    service2.set_active(True)
    assert not any(p.startswith("/api/models") for p in paths(log2))
    assert len(events2["telemetry"]) == 1


def test_choosing_a_family_while_a_request_runs_fetches_the_chosen_family():
    deferred = Deferred()
    session, service, log, events, _ = make(runner=deferred)
    session.connected(info(), "t")
    service.select_family("sdxl")  # first request still in flight: ignored for now
    deferred.complete_all()  # finishes the "all families" request, notices the new choice
    assert events["models"] == [] and len(deferred.pending) == 1
    deferred.complete_all()
    family, models = events["models"][0][1]
    assert family == "sdxl" and {m.family for m in models} == {"sdxl"} and len(models) == 2
    assert ("/api/models", {"family": "sdxl", "limit": 1000}) in [
        (p, {k: v for k, v in q.items() if v is not None}) for p, q in log]


def test_missing_generation_defaults_do_not_block_the_inventory():
    routes = default_routes()
    routes["/api/generation/capabilities"] = BackendError("NOT_FOUND", "old backend", 404)
    session, service, _, events, _ = make(routes)
    session.connected(info(), "t")
    assert events["models"][0][0].defaults is None and len(events["models"][0][1][1]) == 3


@pytest.mark.parametrize("code", ["AUTH_REQUIRED", "NETWORK_ERROR", "INVALID_RESPONSE"])
def test_model_errors_are_reported_and_retried_later(code):
    routes = default_routes()
    routes["/api/models/families"] = BackendError(code, "x")
    session, service, _, events, _ = make(routes)
    session.connected(info(), "t")
    assert events["models_failed"] == [code] and service.catalog is None
    assert service._models_timer.isActive()


def test_refresh_now_reloads_the_catalogue_and_telemetry():
    session, service, log, events, _ = make()
    session.connected(info(), "t")
    service.set_active(True)
    service.refresh_now()
    assert paths(log).count("/api/models/families") == 2
    assert paths(log).count("/api/system/telemetry") == 2
