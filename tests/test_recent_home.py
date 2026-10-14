"""Layout step 2: Home hero, recent-project tiles with thumbnails, and the render queue card."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.projects import ProjectSummary, RenderSummary
from morphorum_studio.backend.session import BackendSession, SessionInfo
from morphorum_studio.ui.dashboard_service import DashboardService
from morphorum_studio.ui.home_page import HomePage, project_meta
from morphorum_studio.ui.recent_service import (
    RecentProject,
    RecentProjectsService,
    latest_with_frame,
    load_recent,
    make_thumbnail,
    newest_render,
    recent_first,
    status_chip,
)

QApplication.instance() or QApplication(["morphorum-studio-tests"])


def png(width=64, height=36, color="#3366ff") -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    out = QByteArray()
    buffer = QBuffer(out)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(out)


class Fake:
    """Minimal client: project list, per-project render lists and frame downloads."""

    def __init__(self, projects, renders, frame=None):
        self.projects, self.renders, self.frame = projects, renders, frame or png()
        self.downloads = []

    def get_json(self, path, params=None):
        if path == "/api/animation/projects":
            return {"projects": self.projects}
        for pid, result in self.renders.items():
            if path == f"/api/animation/projects/{pid}/renders":
                if isinstance(result, BackendError):
                    raise result
                return {"renders": result}
        raise BackendError("NOT_FOUND", path)

    def download(self, path, sink, limit):
        self.downloads.append(path)
        sink(self.frame)
        return len(self.frame), None, None


def project(pid, name, updated, **extra):
    return {"id": pid, "name": name, "updated_at": updated, "width": 1024, "height": 576,
            "fps": 12, "max_frames": 120, **extra}


PROJECTS = [project("alpha", "Alpha", "2026-10-01T10:00:00"),
            project("beta", "Beta", "2026-10-03T10:00:00"),
            project("gamma", "Gamma", "2026-10-02T10:00:00")]
RENDERS = {
    "alpha": [{"id": "r1", "status": "completed", "created_at": "2026-10-01T11:00:00",
               "latest_completed_frame": 7}],
    "beta": [{"id": "r2", "status": "completed", "created_at": "2026-10-02T09:00:00",
              "latest_completed_frame": 3},
             {"id": "r3", "status": "rendering", "created_at": "2026-10-03T09:00:00"}],
    "gamma": BackendError("NOT_FOUND", "x"),
}


def test_helpers_pick_newest_and_latest_framed_render_and_label_status():
    renders = (RenderSummary("a", "completed", "2026-10-01", 4),
               RenderSummary("b", "rendering", "2026-10-02", None),
               RenderSummary("c", "failed", None, None))
    assert newest_render(renders).id == "b"
    assert latest_with_frame(renders).id == "a"
    assert newest_render(()) is None and latest_with_frame(()) is None
    summaries = [ProjectSummary("a", "A", "2026-01-01"), ProjectSummary("b", "B", "2026-03-01"),
                 ProjectSummary("c", "C", None), ProjectSummary("d", "D", "2026-02-01")]
    assert [p.id for p in recent_first(summaries, 3)] == ["b", "d", "a"]
    assert status_chip(None) == ("Draft", "idle")
    assert status_chip("rendering") == ("Rendering", "busy") and status_chip("queued")[0] == "Queued"
    assert status_chip("completed") == ("Rendered", "ok") and status_chip("failed")[1] == "bad"
    assert status_chip("interrupted")[1] == "warn"
    assert status_chip("loading_model") == ("Rendering", "busy")


def test_thumbnail_is_scaled_png_and_garbage_gives_none():
    small = make_thumbnail(png(1000, 500), 100)
    image = QImage.fromData(small)
    assert (image.width(), image.height()) == (100, 50)
    assert make_thumbnail(b"not an image") is None


def test_load_recent_sorts_marks_status_and_downloads_each_thumbnail_once():
    client = Fake(PROJECTS, RENDERS)
    items, fresh = load_recent(client, {})
    assert [i.summary.id for i in items] == ["beta", "gamma", "alpha"]
    beta, gamma, alpha = items
    assert beta.status == "rendering" and beta.latest_frame == 3 and beta.thumb
    assert gamma.status is None and gamma.thumb is None  # its render list failed: still listed
    assert alpha.status == "completed" and alpha.thumb
    assert len(fresh) == 2 and len(client.downloads) == 2
    assert client.downloads[0].endswith("/beta/r2/frames/3")
    again, fresh2 = load_recent(client, fresh)
    assert fresh2 == {} and len(client.downloads) == 2 and again[0].thumb == beta.thumb


def test_a_bad_frame_leaves_a_tile_without_a_thumbnail():
    client = Fake(PROJECTS[:1], {"alpha": RENDERS["alpha"]}, frame=b"junk")
    items, fresh = load_recent(client, {})
    assert items[0].thumb is None and items[0].status == "completed" and fresh == {}


def sync_runner(client, fn, callback):
    try:
        result = fn(client)
    except BackendError as exc:
        callback(None, (exc.code, str(exc)))
    else:
        callback(result, None)


def info(boot="b1", features=None):
    return SessionInfo("p1", "Workshop", "http://10.0.0.5:7866", "0.1.0", "backend-only",
                       "i1", boot, {"project_crud": True} if features is None else features)


def rig(client=None):
    client = client or Fake(PROJECTS, RENDERS)
    session = BackendSession(client_factory=lambda base, token, timeout=6.0: client)
    service = RecentProjectsService(session, runner=sync_runner)
    return session, service, client


def test_service_loads_when_active_and_connected_and_resets_on_a_new_connection():
    session, service, client = rig()
    seen, cleared = [], []
    service.updated.connect(seen.append)
    service.cleared.connect(lambda: cleared.append(1))
    service.set_active(True)
    assert seen == []  # not connected yet
    session.connected(info(), "t")
    assert len(seen) == 1 and [i.summary.id for i in seen[0]][0] == "beta"
    assert service.last is seen[0]
    service.refresh()
    assert len(client.downloads) == 2  # thumbnails came from the cache the second time
    session.connected(info(boot="b2"), "t")  # backend restarted: a different connection
    assert cleared and len(seen) >= 2
    session.disconnected()
    assert service.last is None


def test_service_needs_project_support_and_reports_failures():
    session, service, _ = rig()
    failures = []
    service.failed.connect(failures.append)
    service.set_active(True)
    session.connected(info(features={}), "t")
    assert not service.available and failures == []
    broken = Fake(PROJECTS, {})
    broken.get_json = lambda path, params=None: (_ for _ in ()).throw(BackendError("TIMEOUT", "t"))
    session2, service2, _ = rig(broken)
    service2.failed.connect(failures.append)
    service2.set_active(True)
    session2.connected(info(), "t")
    assert failures == ["TIMEOUT"]


def home(features=None):
    session = BackendSession(client_factory=lambda base, token, timeout=6.0: Fake(PROJECTS, RENDERS))
    dash = DashboardService(session, runner=sync_runner)
    recent = RecentProjectsService(session, runner=sync_runner)
    page = HomePage(session, dash, recent=recent)
    return page, session, recent


def test_home_shows_tiles_with_chips_meta_and_queue_rows():
    page, session, recent = home()
    session.connected(info(), "t")
    recent.set_active(True)
    assert [t.project_id for t in page.tiles] == ["beta", "gamma", "alpha"]
    beta, gamma, alpha = page.tiles
    assert beta.chip.text() == "Rendering" and beta.chip.property("state") == "busy"
    assert gamma.chip.text() == "Draft" and not gamma.thumb.has_image
    assert alpha.chip.text() == "Rendered" and alpha.thumb.has_image
    assert beta.meta.text() == "1024×576 · 12 fps · 10.0 s"
    assert page.queue_rows.count() == 2  # drafts are not queue entries
    assert page.queue_note.text().startswith("Latest render")
    assert page.recent_note.isHidden()


def test_home_tile_click_and_hero_buttons_emit_navigation():
    page, session, recent = home()
    session.connected(info(), "t")
    recent.set_active(True)
    got = []
    page.open_project.connect(got.append)
    page.new_project.connect(lambda: got.append("new"))
    page.open_library.connect(lambda: got.append("library"))
    page.open_lab.connect(lambda: got.append("lab"))
    page.tiles[2].clicked.emit(page.tiles[2].project_id)
    page.new_button.click()
    page.open_button.click()
    page.generate_button.click()
    assert got == ["alpha", "new", "library", "lab"]


def test_home_empty_unavailable_and_cleared_states():
    page, session, recent = home()
    session.connected(info(features={}), "t")
    assert page.recent_section.isHidden()  # backend without project support: no empty promise
    page._recent_updated(())
    assert "No projects yet" in page.recent_note.text() and page.queue_rows.count() == 0
    page._recent_failed("TIMEOUT")
    assert "TIMEOUT" in page.recent_note.text()
    session.disconnected()
    assert page.tiles == [] and page.recent_note.text() == "Loading projects…"


def test_project_meta_never_invents_values():
    assert project_meta(ProjectSummary("a", "A")) == "—"
    assert project_meta(ProjectSummary("a", "A", width=640, height=360)) == "640×360"


def test_recentproject_defaults():
    item = RecentProject(ProjectSummary("a", "A"))
    assert item.status is None and item.thumb is None
