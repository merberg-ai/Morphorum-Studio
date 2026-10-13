"""Video export service and panel against a scripted fake backend (offscreen Qt, CI only)."""

import hashlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtWidgets import QApplication, QFileDialog

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.images import SubmissionJournal
from morphorum_studio.backend.renders import parse_render
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.video_panel import VideoPanel
from morphorum_studio.ui.video_service import VideoService

FEATURES = {"animation_render": True, "project_crud": True, "video_export": True}
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"v" * 2000
SHA = hashlib.sha256(MP4).hexdigest()
BASE = "/api/animation/renders/demo/r1"


def export(status="completed", audio=True, **extra):
    data = {"id": "video-0123456789ab", "project_id": "demo", "render_id": "r1", "format": "mp4",
            "quality": "balanced", "fps": 12, "status": status, "progress": 1.0 if status == "completed" else 0.3,
            "message": status, "total_frames": 4, "audio_included": audio,
            "audio_source": "imported_soundtrack" if audio else None, "audio_offset_seconds": 0.0}
    if status == "completed":
        data.update(bytes=len(MP4), sha256=SHA)
    data.update(extra)
    return data


def render(soundtrack=True, status="completed"):
    data = {"id": "r1", "project_id": "demo", "status": status, "progress": 1.0, "total_frames": 4,
            "results": [{"frame": i} for i in range(4)], "latest_completed_frame": 3}
    if soundtrack:
        data["imported_soundtrack"] = {"enabled": True, "filename": "song.wav"}
    return parse_render(data)


class Backend:
    def __init__(self):
        self.available = True
        self.exports = []
        self.jobs = [export("encoding"), export("completed")]
        self.posts, self.fail_post, self.data = [], None, MP4


class Client:
    def __init__(self, backend):
        self.b = backend

    def get_json(self, path, params=None):
        if path == "/api/animation/video/availability":
            return {"available": self.b.available, "formats": ["mp4", "webm"],
                    "qualities": ["high", "balanced", "compact"],
                    "message": "" if self.b.available else "FFmpeg not found"}
        if path == BASE + "/videos":
            return {"exports": self.b.exports}
        if path.startswith("/api/animation/video/jobs/"):
            return self.b.jobs.pop(0) if len(self.b.jobs) > 1 else self.b.jobs[0]
        raise BackendError("NOT_FOUND", "no route", 404)

    def send_json(self, method, path, body=None, *, if_match=None, idempotency_key=None, max_bytes=0):
        self.b.posts.append((path, body, idempotency_key))
        if self.b.fail_post:
            raise self.b.fail_post
        return export("queued"), None

    def download(self, path, sink, max_bytes):
        sink(self.b.data)
        return len(self.b.data), hashlib.sha256(self.b.data).hexdigest(), SHA


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def make(tmp_path, features=FEATURES):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    backend = Backend()
    def factory(url, token, timeout=6.0):
        assert 0 < timeout <= 60, "BackendClient rejects timeouts above 60 s"
        return Client(backend)

    session = BackendSession(client_factory=factory)
    journal = SubmissionJournal(tmp_path / "journal")
    service = VideoService(session, journal, tmp_path / "cache", runner=sync_runner)
    session.connected(info(features=features), "tok")
    return backend, session, service, journal


def test_start_journals_and_tracks_to_completion(tmp_path):
    backend, session, service, journal = make(tmp_path)
    seen = []
    service.export_updated.connect(seen.append)
    service.start("demo", "r1", "mp4", "balanced", None)
    path, body, key = backend.posts[0]
    assert path == BASE + "/video" and body == {"format": "mp4", "quality": "balanced"}
    assert key.startswith("studio-") and journal.entries("p1", "video")[0].state == "submitted"
    service.poll_now()
    service.poll_now()
    assert [e.status for e in seen][-2:] == ["encoding", "completed"]
    assert journal.entries() == [] and service.watched is None


def test_fps_override_is_sent_only_when_asked(tmp_path):
    backend, _, service, _ = make(tmp_path)
    service.start("demo", "r1", "webm", "high", 30)
    assert backend.posts[0][1] == {"format": "webm", "quality": "high", "fps": 30}


def test_refused_export_cleans_up_and_ambiguous_keeps_for_retry(tmp_path):
    backend, _, service, journal = make(tmp_path)
    failures, pending = [], []
    service.failed.connect(lambda *a: failures.append(a))
    service.pending_ready.connect(pending.append)
    backend.fail_post = BackendError("INVALID_REQUEST", "HTTP 400: ffmpeg missing", 400)
    service.start("demo", "r1", "mp4", "high", None)
    assert failures[0][:2] == ("start", "INVALID_REQUEST") and journal.entries() == []
    backend.fail_post = BackendError("NETWORK_ERROR", "Unable to reach backend")
    service.start("demo", "r1", "mp4", "high", None)
    entry = journal.entries("p1", "video")[0]
    assert pending[0][0].key == entry.key
    backend.fail_post = None
    service.retry(entry)
    assert backend.posts[-1][2] == entry.key and backend.posts[-1][1] == backend.posts[-2][1]


def test_save_is_verified_and_playback_cache_is_reused(tmp_path):
    backend, _, service, _ = make(tmp_path)
    saved, ready = [], []
    service.copy_saved.connect(saved.append)
    service.playback_ready.connect(lambda e, p: ready.append(p))
    from morphorum_studio.backend.videos import parse_export
    e = parse_export(export())
    dest = tmp_path / "out.mp4"
    service.save(e, str(dest))
    assert saved == [str(dest)] and dest.read_bytes() == MP4
    service.prepare_playback(e)
    assert len(ready) == 1 and os.path.exists(ready[0])
    backend.data = b"corrupt"  # a second request must come from the intact cache
    service.prepare_playback(e)
    assert ready[1] == ready[0]


def test_corrupt_download_saves_nothing(tmp_path):
    backend, _, service, _ = make(tmp_path)
    failures = []
    service.failed.connect(lambda *a: failures.append(a))
    backend.data = MP4[:-1] + b"X"
    from morphorum_studio.backend.videos import parse_export
    dest = tmp_path / "bad.mp4"
    service.save(parse_export(export()), str(dest))
    assert failures and failures[0][0] == "copy" and not dest.exists()
    assert not list(tmp_path.glob("*.part"))


def test_panel_ffmpeg_unavailable_blocks_export(tmp_path):
    backend, _, service, _ = make(tmp_path)
    backend.available = False
    panel = VideoPanel(service)
    panel.set_render("demo", render())
    assert not panel.export_button.isEnabled()
    assert "FFmpeg" in panel.availability.text()


def test_panel_warns_without_soundtrack_and_locks_fps_with_one(tmp_path):
    backend, _, service, _ = make(tmp_path)
    panel = VideoPanel(service)
    panel.set_render("demo", render(soundtrack=False))
    assert panel.export_button.isEnabled() and "no frozen soundtrack" in panel.audio_note.text()
    assert panel.same_fps.isEnabled()
    panel.set_render("demo", render(soundtrack=True))
    assert "song.wav" in panel.audio_note.text()
    assert not panel.same_fps.isEnabled() and panel.same_fps.isChecked() and not panel.fps.isEnabled()


def test_panel_reports_audio_only_from_the_export_record(tmp_path):
    backend, _, service, _ = make(tmp_path)
    backend.exports = [export(audio=False), export(audio=True, quality="high")]
    panel = VideoPanel(service)
    panel.set_render("demo", render(soundtrack=True))
    texts = [panel.listing.item(i).text() for i in range(panel.listing.count())]
    assert "No audio track" in texts[0] and "With audio" in texts[1]


def test_panel_exports_then_saves_selected(tmp_path, monkeypatch):
    backend, _, service, _ = make(tmp_path)
    panel = VideoPanel(service)
    panel.set_render("demo", render(soundtrack=False))
    panel.quality.setCurrentIndex(0)
    panel.export_button.click()
    assert backend.posts[0][1]["quality"] == "high"
    service.poll_now()
    service.poll_now()
    assert panel.listing.count() == 1 and "Export finished" in panel.status.text()
    dest = tmp_path / "saved.mp4"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), ""))
    panel.listing.setCurrentRow(0)
    panel.save_button.click()
    assert dest.read_bytes() == MP4


def test_interrupted_export_is_not_downloadable(tmp_path):
    backend, _, service, _ = make(tmp_path)
    backend.exports = [export("interrupted", audio=False)]
    panel = VideoPanel(service)
    panel.set_render("demo", render())
    panel.listing.setCurrentRow(0)
    assert not panel.save_button.isEnabled() and "interrupted" in panel.listing.item(0).text()


def test_session_change_clears_stale_state(tmp_path):
    backend, session, service, _ = make(tmp_path)
    panel = VideoPanel(service)
    panel.set_render("demo", render())
    session.connected(info(boot="z", features=FEATURES), "tok")
    assert not panel.isVisible() or panel.listing.count() == 0
