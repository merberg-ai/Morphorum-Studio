"""Render service and card against a scripted fake backend (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtCore import QBuffer, QByteArray, QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.images import SubmissionJournal
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.preferences import StudioPreferences
from morphorum_studio.ui.render_card import PreviewDialog, RenderCard
from morphorum_studio.ui.render_service import RenderService

FEATURES = {"animation_render": True, "project_crud": True}
RAW = {"id": "demo", "name": "Demo", "animation": {"width": 64, "height": 64, "fps": 12, "max_frames": 4},
       "prompts": {"0": "a cat"}, "extra": {"keep": [1, 2, 3]}}


def png(w=8, h=8):
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(0x884422)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data)


def gif():
    """A valid 1x1 GIF (Qt cannot write GIFs)."""
    return (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00"
            b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")


def render_json(rid="r1", status="queued", frames=0, total=4, **extra):
    data = {"id": rid, "project_id": "demo", "status": status, "message": status,
            "progress": frames / total, "eta_seconds": None, "current_frame": frames, "total_frames": total,
            "current_step": 0, "current_step_total": 0, "created_at": "2026-10-13T08:00:00+00:00",
            "results": [{"frame": i} for i in range(frames)],
            "latest_completed_frame": frames - 1 if frames else None,
            "preview_url": "/p" if status == "completed" else None,
            "resumable": status in ("failed", "cancelled", "interrupted"), "average_frame_seconds": 10.0}
    data.update(extra)
    return data


class Backend:
    def __init__(self, journal_dir):
        self.journal_dir = journal_dir
        self.calls, self.posts = [], []
        self.renders = {}  # id -> list of states (last repeats)
        self.fail_post = None
        self.validation = {"valid": True, "issues": []}
        self.journal_during_post = None
        self.image, self.gif = png(), gif()

    def state(self, rid):
        states = self.renders.get(rid)
        if not states:
            raise BackendError("NOT_FOUND", "Backend returned HTTP 404", 404)
        return states.pop(0) if len(states) > 1 else states[0]


class Client:
    def __init__(self, backend):
        self.b = backend

    def get_json_etag(self, path, params=None):
        self.b.calls.append(("GET", path))
        return {"project": RAW}, '"' + "a" * 64 + '"'

    def get_json(self, path, params=None):
        self.b.calls.append(("GET", path))
        if path.endswith("/renders") and path.startswith("/api/animation/projects/"):
            return {"renders": [states[0] for states in self.b.renders.values()]}
        if path.startswith("/api/animation/renders/"):
            return self.b.state(path.rsplit("/", 1)[1])
        raise BackendError("NOT_FOUND", "no route", 404)

    def send_json(self, method, path, body=None, *, if_match=None, idempotency_key=None, max_bytes=0):
        self.b.calls.append((method, path, body, idempotency_key))
        if path.endswith("/validate-schedules"):
            return self.b.validation, None
        if path.endswith("/cancel"):
            rid = path.split("/")[-2]
            self.b.renders[rid] = [render_json(rid, "cancelled", 2)]
            return self.b.renders[rid][0], None
        if path.endswith("/resume"):
            rid = path.split("/")[-2]
            self.b.renders[rid] = [render_json(rid, "queued", 2, resumed=True), render_json(rid, "completed", 4)]
            return self.b.renders[rid][0], None
        self.b.posts.append((idempotency_key, body))
        self.b.journal_during_post = [e.key for e in SubmissionJournal(self.b.journal_dir).entries()]
        if self.b.fail_post:
            raise self.b.fail_post
        rid = "r" + str(len(self.b.posts))
        self.b.renders.setdefault(rid, [render_json(rid, "queued")])
        return self.b.renders[rid][0], None

    def download(self, path, sink, max_bytes):
        self.b.calls.append(("DOWNLOAD", path))
        data = self.b.gif if path.endswith("/preview") else self.b.image
        sink(data)
        return len(data), "0" * 64, None


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def make(tmp_path, features=FEATURES, connect=True, card=True):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    backend = Backend(tmp_path / "journal")
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(backend))
    journal = SubmissionJournal(tmp_path / "journal")
    service = RenderService(session, journal, runner=sync_runner)
    widget = RenderCard(service) if card else None
    if connect:
        session.connected(info(features=features), "tok")
    return backend, session, service, journal, widget


def yes(monkeypatch, answer=QMessageBox.StandardButton.Yes):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append((a[1], a[2])) or answer)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: asked.append(("warn", a[1], a[2])))
    return asked


# ----------------------------------------------------------------------------- service

def test_start_sends_whole_project_journalled_first(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, card=False)
    seen = []
    service.job_updated.connect(seen.append)
    service.start("demo")
    key, body = backend.posts[0]
    assert body == {"project": RAW} and key.startswith("studio-")
    assert backend.journal_during_post == [key]  # on disk before the POST
    entry = journal.entries("p1", "animation")[0]
    assert entry.state == "submitted" and entry.job_id == "r1" and entry.kind == "animation"
    backend.renders["r1"] = [render_json("r1", "rendering", 2), render_json("r1", "completed", 4)]
    service.poll_now()
    service.poll_now()
    assert [j.status for j in seen][-2:] == ["rendering", "completed"]
    assert journal.entries() == [] and service.watched is None


def test_refused_start_cleans_journal_and_reports(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, card=False)
    failures = []
    service.failed.connect(lambda *a: failures.append(a))
    backend.fail_post = BackendError("INVALID_REQUEST", "Backend returned HTTP 400: Save the project first", 400)
    service.start("demo")
    assert failures[0][:2] == ("start", "INVALID_REQUEST") and journal.entries() == [] and not service.busy


def test_ambiguous_start_keeps_entry_and_retry_reuses_key_and_body(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, card=False)
    pending = []
    service.pending_ready.connect(pending.append)
    backend.fail_post = BackendError("NETWORK_ERROR", "Unable to reach backend")
    service.start("demo")
    entry = journal.entries("p1", "animation")[0]
    assert entry.state == "pending" and pending[0][0].key == entry.key
    backend.fail_post = None
    service.retry(entry)
    assert backend.posts[0] == backend.posts[1]  # same key, same body
    assert journal.entries("p1", "animation")[0].state == "submitted"


def test_image_and_animation_journals_do_not_mix(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, card=False)
    journal.begin("p1", {"prompt": "img"})  # an image entry in the same journal
    pending = []
    service.pending_ready.connect(pending.append)
    service.check_pending()
    assert pending == []


def test_check_pending_reconciles_and_reattaches(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, card=False)
    gone = journal.submitted(journal.begin("p1", {"project": RAW}, "animation"), "r-gone")
    done = journal.submitted(journal.begin("p1", {"project": RAW}, "animation"), "r-done")
    live = journal.submitted(journal.begin("p1", {"project": RAW}, "animation"), "r-live")
    unknown = journal.begin("p1", {"project": RAW}, "animation")
    backend.renders["r-done"] = [render_json("r-done", "completed", 4)]
    backend.renders["r-live"] = [render_json("r-live", "rendering", 1)]
    pending, updates = [], []
    service.pending_ready.connect(pending.append)
    service.job_updated.connect(updates.append)
    service.check_pending()
    keys = {e.key for e in journal.entries("p1", "animation")}
    assert keys == {live.key, unknown.key} and gone.key not in keys and done.key not in keys
    assert [e.key for e in pending[0]] == [unknown.key]
    assert service.watched == "r-live" and updates[-1].id == "r-live"


def test_epoch_change_stops_watching(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, card=False)
    service.start("demo")
    assert service.watched == "r1"
    session.disconnected()
    assert service.watched is None and not service._timer.isActive()


def test_cancel_and_resume(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, card=False)
    service.start("demo")
    seen = []
    service.job_updated.connect(seen.append)
    service.cancel("r1")
    assert seen[-1].status == "cancelled" and service.watched is None
    service.resume("demo", "r1")
    assert seen[-1].status in ("queued", "completed") and any(j.resumed for j in seen)
    service.poll_now()
    assert seen[-1].status == "completed"


def test_unavailable_without_feature(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, features={"project_crud": True}, card=False)
    service.start("demo")
    service.load_list("demo")
    assert backend.calls == [] and not service.available


# ----------------------------------------------------------------------------- card

def open_card(tmp_path, monkeypatch=None):
    backend, session, service, journal, card = make(tmp_path)
    return backend, session, service, journal, card


def test_card_disabled_without_project_or_connection(tmp_path):
    backend, session, service, journal, card = make(tmp_path, connect=False)
    assert not card.start_button.isEnabled()
    session.connected(info(features=FEATURES), "tok")
    assert not card.start_button.isEnabled()  # still no project
    card.set_project("demo")
    assert card.start_button.isEnabled() and card.status.text() == "No render yet."


def test_start_confirmation_and_progress_flow(tmp_path, monkeypatch):
    backend, session, service, journal, card = open_card(tmp_path)
    card.set_project("demo")
    asked = yes(monkeypatch, QMessageBox.StandardButton.Cancel)
    card.start_button.click()
    assert asked and backend.posts == []
    yes(monkeypatch)
    card.start_button.click()
    assert len(backend.posts) == 1 and card.status.text() == "Waiting in the queue"
    assert not card.start_button.isEnabled() and card.cancel_button.isEnabled()
    backend.renders["r1"] = [render_json("r1", "rendering", 2, current_step=5, current_step_total=20, eta_seconds=30)]
    service.poll_now()
    assert card.progress.value() == 500 and "frame 3 of 4" in card.status.text()
    assert card.slider.maximum() == 1 and card.slider.value() == 1  # follows the newest frame
    assert ("DOWNLOAD", "/api/animation/renders/demo/r1/frames/1") in backend.calls
    assert card.frame_view.pixmap() is not None and not card.frame_view.pixmap().isNull()
    backend.renders["r1"] = [render_json("r1", "completed", 4)]
    service.poll_now()
    assert card.start_button.isEnabled() and not card.cancel_button.isEnabled()
    assert card.status.text() == "Done: 4 frames" and card.play_button.isEnabled()


def test_unsaved_edits_pause_rendering(tmp_path):
    backend, session, service, journal, card = open_card(tmp_path)
    card.set_project("demo")
    card.set_locked(True)
    assert not card.start_button.isEnabled() and "Save or revert" in card.note.text()
    card.set_locked(False)
    assert card.start_button.isEnabled()


def test_slider_stops_following_and_resumes(tmp_path, monkeypatch):
    backend, session, service, journal, card = open_card(tmp_path)
    backend.renders["r1"] = [render_json("r1", "rendering", 3)]
    card.set_project("demo")  # list_ready picks the live render and watches it
    assert card.slider.maximum() == 2 and card.slider.value() == 2 and card.follow.isChecked()
    card.slider.setValue(0)
    assert not card.follow.isChecked() and card._wanted_frame == 0
    backend.renders["r1"] = [render_json("r1", "rendering", 4)]
    service.poll_now()
    assert card.slider.maximum() == 3 and card.slider.value() == 0  # did not jump
    card.follow.setChecked(True)
    assert card.slider.value() == 3


def test_cancel_button(tmp_path, monkeypatch):
    backend, session, service, journal, card = open_card(tmp_path)
    backend.renders["r1"] = [render_json("r1", "rendering", 1)]
    card.set_project("demo")
    card.cancel_button.click()
    assert card.status.text().startswith("Cancelled after 2 frames") and card.resume_button.isEnabled()


def test_resume_needs_confirmation(tmp_path, monkeypatch):
    backend, session, service, journal, card = open_card(tmp_path)
    backend.renders["r1"] = [render_json("r1", "interrupted", 2)]
    card.set_project("demo")
    assert "can be resumed" in card.status.text() and card.resume_button.isEnabled()
    asked = yes(monkeypatch, QMessageBox.StandardButton.Cancel)
    card.resume_button.click()
    assert asked and not any(c[0] == "POST" for c in backend.calls)
    asked = yes(monkeypatch)
    card.resume_button.click()
    assert "2 frames already rendered" in asked[0][1]
    assert any(c[0] == "POST" and c[1].endswith("/demo/r1/resume") for c in backend.calls)
    assert card.status.text() == "Waiting in the queue (resuming)"
    service.poll_now()
    assert card.status.text() == "Done: 4 frames"


def test_existing_active_render_is_reattached_on_open(tmp_path):
    backend, session, service, journal, card = open_card(tmp_path)
    backend.renders["old"] = [render_json("old", "completed", 4, created_at="2026-10-12T08:00:00+00:00")]
    backend.renders["live"] = [render_json("live", "rendering", 1)]
    card.set_project("demo")
    assert service.watched == "live" and card.render_combo.count() == 2
    assert "frame 2 of 4" in card.status.text()


def test_choose_earlier_render(tmp_path):
    backend, session, service, journal, card = open_card(tmp_path)
    backend.renders["a"] = [render_json("a", "completed", 4, created_at="2026-10-13T09:00:00+00:00")]
    backend.renders["b"] = [render_json("b", "failed", 1, error="out of memory", created_at="2026-10-13T08:00:00+00:00")]
    card.set_project("demo")
    card._combo_chosen(1)
    assert card.status.text() == "Failed: out of memory" and card.resume_button.isEnabled()
    card._combo_chosen(0)
    assert card.status.text() == "Done: 4 frames" and not card.resume_button.isEnabled()


def test_refused_start_shows_reason(tmp_path, monkeypatch):
    backend, session, service, journal, card = open_card(tmp_path)
    card.set_project("demo")
    asked = yes(monkeypatch)
    backend.fail_post = BackendError("INVALID_REQUEST", "Backend returned HTTP 400: Source image required", 400)
    card.start_button.click()
    assert ("warn", "Could not start the render", "Backend returned HTTP 400: Source image required") in asked
    assert journal.entries() == [] and card.start_button.isEnabled()


def test_pending_banner_retry_and_discard(tmp_path, monkeypatch):
    backend, session, service, journal, card = open_card(tmp_path)
    card.set_project("demo")
    yes(monkeypatch)
    backend.fail_post = BackendError("NETWORK_ERROR", "Unable to reach backend")
    card.start_button.click()
    assert card.pending_label.isVisibleTo(card) and "Demo" in card.pending_label.text()
    backend.fail_post = None
    card.pending_retry.click()
    assert backend.posts[0][0] == backend.posts[1][0] and not card.pending_label.isVisibleTo(card)
    card._pending = [journal.begin("p1", {"project": RAW}, "animation")]
    card._show_pending()
    card.pending_discard.click()
    assert not card.pending_label.isVisibleTo(card)
    assert all(e.state == "submitted" for e in journal.entries("p1", "animation"))


def test_preview_and_saving(tmp_path, monkeypatch):
    from morphorum_studio.ui import render_card as module
    backend, session, service, journal, card = open_card(tmp_path)
    backend.renders["r1"] = [render_json("r1", "completed", 4)]
    card.set_project("demo")
    shown = []
    monkeypatch.setattr(module.PreviewDialog, "exec", lambda self: shown.append(self) or 0)
    card.play_button.click()
    assert shown and isinstance(shown[0], PreviewDialog)
    out = tmp_path / "frame.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    saved = []
    service.copy_saved.connect(saved.append)
    card.save_frame_button.click()
    assert out.read_bytes() == backend.image and saved == [str(out)]
    gif_out = tmp_path / "p.gif"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(gif_out), ""))
    card.save_preview_button.click()
    assert gif_out.read_bytes() == backend.gif


def test_disconnect_clears_card(tmp_path):
    backend, session, service, journal, card = open_card(tmp_path)
    backend.renders["r1"] = [render_json("r1", "rendering", 1)]
    card.set_project("demo")
    session.disconnected()
    assert card.render_combo.count() == 0 and card.status.text() == "No render yet."
    assert not card.start_button.isEnabled() and service.watched is None


def test_page_and_window_wiring(tmp_path):
    from morphorum_studio.ui.main_window import PAGES, StudioMainWindow
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "w.ini"), QSettings.Format.IniFormat)
    window = StudioMainWindow(preferences=StudioPreferences(settings), journal_dir=tmp_path / "j")
    try:
        page = window.editor_page
        assert page.render_card is not None and page.render_card._service is window.render_service
        assert page.render_card._compact and page._render_service is window.render_service
        assert not hasattr(window.projects_page, "render_card")
        assert window.render_service._journal is window.image_service._journal
        assert [p[0] for p in PAGES].count("Projects") == 1
    finally:
        window.close()


def test_start_is_blocked_by_schedule_errors_before_anything_is_journalled(tmp_path):
    backend, session, service, journal, _ = make(tmp_path, card=False)
    backend.validation = {"valid": False, "issues": [
        {"field": "motion.zoom", "severity": "error", "message": "zoom must be positive"}]}
    failures = []
    service.failed.connect(lambda *a: failures.append(a))
    service.start("demo")
    assert not backend.posts and journal.entries() == []
    assert failures[0][1] == "INVALID_REQUEST" and "zoom must be positive" in failures[0][2]
