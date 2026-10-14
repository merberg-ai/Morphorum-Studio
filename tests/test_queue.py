"""Layout step 6: the Queue page and service (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession, SessionInfo
from morphorum_studio.ui.queue_page import QueuePage, keep, summary_text
from morphorum_studio.ui.queue_service import QueueService, chip_for, load_queue

QApplication.instance() or QApplication(["morphorum-studio-tests"])

FEATURES = {"sdxl_generation": True, "animation_render": True, "project_crud": True}


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def image(jid, status, created, **extra):
    data = {"id": jid, "status": status, "message": status, "progress": 0.5, "current_image": 0,
            "current_step": 5, "total_steps": 25, "seeds": [], "results": [], "error": None,
            "cancel_requested": False, "request": {"images": 1, "prompt": f"prompt {jid}"},
            "model": {"name": "Juggernaut"}, "created_at": created}
    data.update(extra)
    return data


def render(rid, pid, status, created, **extra):
    data = {"id": rid, "project_id": pid, "status": status, "message": status, "progress": 0.25,
            "current_frame": 1, "total_frames": 4, "created_at": created, "results": [],
            "resumable": status in ("failed", "cancelled", "interrupted")}
    data.update(extra)
    return data


class Fake:
    def __init__(self):
        self.images = [image("i1", "completed", "2026-10-13T08:00:00"),
                       image("i2", "generating", "2026-10-14T08:00:00")]
        self.projects = [{"id": "alpha", "name": "Alpha", "updated_at": "2026-10-02T10:00:00"},
                         {"id": "beta", "name": "Beta", "updated_at": "2026-10-03T10:00:00"}]
        self.renders = {"alpha": [render("r1", "alpha", "interrupted", "2026-10-12T08:00:00")],
                        "beta": [render("r2", "beta", "rendering", "2026-10-14T09:00:00"),
                                 render("r3", "beta", "queued", "2026-10-14T10:00:00")]}
        self.posts, self.fail_post, self.fail_images = [], None, False

    def get_json(self, path, params=None):
        if path == "/api/generation/jobs":
            if self.fail_images:
                raise BackendError("UNAVAILABLE", "down")
            return {"jobs": self.images}
        if path == "/api/animation/projects":
            return {"projects": self.projects}
        for pid, items in self.renders.items():
            if path == f"/api/animation/projects/{pid}/renders":
                return {"renders": items}
        raise BackendError("NOT_FOUND", path)

    def send_json(self, method, path, body=None, **kwargs):
        self.posts.append((method, path))
        if self.fail_post:
            raise BackendError("CONFLICT", self.fail_post)
        if "/renders/" in path:
            return render("r2", "beta", "cancelled", "2026-10-14T09:00:00"), None
        return image("i2", "cancelled", "2026-10-14T08:00:00"), None


def info(features=None):
    return SessionInfo("p1", "Workshop", "http://10.0.0.5:7866", "0.1.0", "backend-only", "i1", "b1",
                       FEATURES if features is None else features)


def rig(features=None, client=None):
    client = client or Fake()
    session = BackendSession(client_factory=lambda base, token, timeout=6.0: client)
    service = QueueService(session, runner=sync_runner)
    page = QueuePage(session, service)
    session.connected(info(features), "t")
    return client, session, service, page


def test_chip_labels():
    assert chip_for("queued") == ("Waiting", "idle")
    assert chip_for("generating")[1] == "busy" and chip_for("rendering")[1] == "busy"
    assert chip_for("failed") == ("Failed", "bad") and chip_for("interrupted")[1] == "warn"


def test_load_merges_sources_and_puts_active_first():
    entries = load_queue(Fake(), True, True)
    assert [e.id for e in entries][:3] == ["i2", "r2", "r3"]  # running/waiting, oldest first
    assert [e.id for e in entries][3:] == ["i1", "r1"]  # finished, newest first
    by_id = {e.id: e for e in entries}
    assert by_id["r2"].detail == "Beta" and by_id["r2"].can_cancel and not by_id["r2"].can_resume
    assert by_id["r1"].can_resume and not by_id["r1"].can_cancel
    assert by_id["i2"].kind == "image" and by_id["i2"].title == "prompt i2"


def test_one_failing_source_does_not_hide_the_other():
    fake = Fake()
    fake.fail_images = True
    entries = load_queue(fake, True, True)
    assert {e.kind for e in entries} == {"render"}


def test_all_sources_failing_raises():
    fake = Fake()
    fake.fail_images = True
    try:
        load_queue(fake, True, False)
    except BackendError as exc:
        assert exc.code == "UNAVAILABLE"
    else:
        raise AssertionError("expected BackendError")


def test_only_advertised_sources_are_read():
    fake = Fake()
    fake.fail_images = True  # would raise if the image list were read
    assert {e.kind for e in load_queue(fake, False, True)} == {"render"}


def test_page_lists_rows_with_buttons_and_summary():
    client, session, service, page = rig()
    service.set_active(True)
    assert len(page.rows) == 5
    r2 = next(r for r in page.rows if r.entry.id == "r2")
    assert r2.chip.text() == "Running" and r2.cancel_button.isVisibleTo(page) is True
    assert not r2.resume_button.isVisibleTo(page) and r2.open_button.text() == "Open in Timeline"
    r1 = next(r for r in page.rows if r.entry.id == "r1")
    assert r1.resume_button.isVisibleTo(page) and not r1.cancel_button.isVisibleTo(page)
    assert page.summary.text() == "2 running · 1 waiting · 2 finished"
    assert summary_text(()) == "Nothing in the queue"


def test_filters():
    client, session, service, page = rig()
    service.set_active(True)
    page.set_filter("active")
    assert sorted(r.entry.id for r in page.rows) == ["i2", "r2", "r3"]
    page.set_filter("finished")
    assert sorted(r.entry.id for r in page.rows) == ["i1", "r1"]
    page.set_filter("all")
    assert len(page.rows) == 5 and keep(page.rows[0].entry, "all")


def test_cancel_and_resume_hit_the_right_endpoints_and_refresh():
    client, session, service, page = rig()
    service.set_active(True)
    next(r for r in page.rows if r.entry.id == "r2").cancel_button.click()
    next(r for r in page.rows if r.entry.id == "i2").cancel_button.click()
    next(r for r in page.rows if r.entry.id == "r1").resume_button.click()
    paths = [p for _, p in client.posts]
    assert paths == ["/api/animation/renders/r2/cancel", "/api/generation/jobs/i2/cancel",
                     "/api/animation/renders/alpha/r1/resume"]


def test_refused_action_is_reported():
    client, session, service, page = rig()
    service.set_active(True)
    client.fail_post = "That render already finished"
    next(r for r in page.rows if r.entry.id == "r2").cancel_button.click()
    assert "already finished" in page.note.text() and page.note.isVisibleTo(page)


def test_open_signals():
    client, session, service, page = rig()
    service.set_active(True)
    got = []
    page.open_timeline.connect(got.append)
    page.open_lab.connect(lambda: got.append("lab"))
    next(r for r in page.rows if r.entry.id == "r2").open_button.click()
    next(r for r in page.rows if r.entry.id == "i1").open_button.click()
    assert got == ["beta", "lab"]


def test_unsupported_backend_and_disconnect():
    client, session, service, page = rig(features={})
    service.set_active(True)
    assert page.rows == [] and not page.scroll.isVisibleTo(page)
    assert "does not report" in page.status_line.text() and page.connect_button.isVisibleTo(page)


def test_empty_queue_message():
    fake = Fake()
    fake.images, fake.renders = [], {"alpha": [], "beta": []}
    client, session, service, page = rig(client=fake)
    service.set_active(True)
    assert page.rows == [] and "Nothing here yet" in page.note.text()
