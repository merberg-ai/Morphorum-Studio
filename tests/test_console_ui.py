"""Console service and page against a scripted fake backend (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtWidgets import QApplication

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.console_page import ConsolePage
from morphorum_studio.ui.console_service import ConsoleService

FEATURES = {"console_sse": True}


def entry(i, level="info", category="api", message="hello"):
    return {"id": i, "timestamp": f"2026-10-13T08:00:{i:02d}.000+00:00", "level": level,
            "category": category, "message": message}


class Backend:
    def __init__(self):
        self.history = [entry(1), entry(2, "warning", "model", "slow load")]
        self.streams = []  # each: list of items (dicts for entries, "gap", "reset", or an Exception)
        self.stream_calls = []
        self.waits = 0


class Client:
    def __init__(self, backend):
        self.b = backend

    def get_json(self, path, params=None):
        return {"events": self.b.history, "boot_id": "boot1"}

    def stream_lines(self, path, params=None, max_line=0, stop=None):
        self.b.stream_calls.append(dict(params or {}))
        script = self.b.streams.pop(0) if self.b.streams else []
        for item in script:
            if isinstance(item, Exception):
                raise item
            if item == "gap":
                yield "event: console_gap"
                yield 'data: {"first_available": 9}'
            elif item == "reset":
                yield "event: console_reset"
                yield 'data: {"reason": "backend_restarted"}'
            else:
                import json
                yield "event: console"
                yield "data: " + json.dumps(item)
            yield ""


def make(tmp_path=None, features=FEATURES, stop_after=1):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    backend = Backend()
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(backend))
    holder = {}

    def wait(seconds):
        backend.waits += 1
        if backend.waits >= stop_after:
            holder["service"].stop()

    service = ConsoleService(session, spawn=lambda fn: fn(), wait=wait)
    holder["service"] = service
    return backend, session, service


def connect(session, features=FEATURES, **kw):
    session.connected(info(features=features, **kw), "tok")


def test_history_then_stream_resumes_from_last_id():
    backend, session, service = make()
    backend.streams = [[entry(3, "error", "api", "boom")]]
    connect(session)
    assert [e.id for e in service.entries] == [1, 2, 3]
    assert backend.stream_calls[0] == {"after_id": 2, "boot_id": "boot1"}


def test_duplicate_or_old_ids_are_ignored():
    backend, session, service = make()
    backend.streams = [[entry(2), entry(3), entry(3)]]
    connect(session)
    assert [e.id for e in service.entries] == [1, 2, 3]


def test_reconnect_after_drop_resumes_with_cursor():
    backend, session, service = make(stop_after=2)
    backend.streams = [[entry(3), BackendError("NETWORK_ERROR", "Unable to reach backend")],
                       [entry(4)]]
    markers = []
    service.marker.connect(markers.append)
    connect(session)
    assert [e.id for e in service.entries] == [1, 2, 3, 4]
    assert backend.stream_calls[1]["after_id"] == 3
    assert any("reconnecting" in m for m in markers)


def test_gap_and_reset_are_reported_not_hidden():
    backend, session, service = make(stop_after=2)
    backend.streams = [["gap", entry(3), "reset"], [entry(1, message="after restart")]]
    markers = []
    service.marker.connect(markers.append)
    connect(session)
    assert any("dropped" in m for m in markers) and any("restarted" in m for m in markers)
    assert [e.message for e in service.entries] == ["after restart"]


def test_auth_refusal_stops_with_a_message():
    backend, session, service = make()
    backend.streams = [[BackendError("AUTH_REQUIRED", "Backend returned HTTP 401", 401)]]
    markers = []
    service.marker.connect(markers.append)
    connect(session)
    assert service.state == "stopped" and any("refused" in m for m in markers)
    assert backend.waits == 0


def test_new_connection_identity_clears_history():
    backend, session, service = make()
    backend.streams = [[], []]
    connect(session)
    assert len(service.entries) == 2
    backend.history = [entry(1, message="other backend")]
    connect(session, boot="z")
    assert [e.message for e in service.entries] == ["other backend"]


def test_disconnect_stops_streaming():
    backend, session, service = make()
    backend.streams = [[]]
    connect(session)
    session.disconnected()
    assert service.state == "stopped"


def test_clear_view_keeps_streaming_state():
    backend, session, service = make()
    connect(session)
    cleared = []
    service.cleared.connect(lambda: cleared.append(1))
    service.clear_view()
    assert not service.entries and cleared


def page_with(backend_entries):
    backend, session, service = make()
    backend.history = backend_entries
    connect(session)
    page = ConsolePage(session, service)
    page._flush()
    return page, service


def test_page_filters_by_level_category_and_search():
    page, _ = page_with([entry(1, "info", "api", "GET /a"), entry(2, "warning", "model", "slow load"),
                         entry(3, "error", "api", "boom")])
    assert len(page.visible_text().splitlines()) == 3
    page.level.setCurrentIndex(page.level.findData("warning"))
    assert [ln.split()[1] for ln in page.visible_text().splitlines()] == ["WARNING", "ERROR"]
    page.level.setCurrentIndex(0)
    page.category.setCurrentIndex(page.category.findData("model"))
    assert "slow load" in page.visible_text() and "GET /a" not in page.visible_text()
    page.category.setCurrentIndex(0)
    page.search.setText("BOOM")
    assert page.visible_text().count("\n") == 0 and "boom" in page.visible_text()


def test_page_shows_new_entries_and_status():
    backend, session, service = make()
    connect(session)
    page = ConsolePage(session, service)
    assert page.status.text()
    session.disconnected()
    assert "Connect to a backend" in page.status.text()


def test_page_markers_and_clear():
    page, service = page_with([entry(1)])
    service.marker.emit("Console stream interrupted; reconnecting…")
    assert "interrupted" in page.view.toPlainText()
    service.clear_view()
    assert page.view.toPlainText().strip() == "" and not page.visible_text()
