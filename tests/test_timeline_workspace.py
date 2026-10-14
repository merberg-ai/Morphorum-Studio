"""Layout step 4: Timeline workspace (preview player, transport, compact render card)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from test_editor_ui import Backend as EditorBackend
from test_editor_ui import Client as EditorClient
from test_render_ui import Backend as RenderBackend
from test_render_ui import Client as RenderClient
from test_render_ui import png, render_json

from morphorum_studio.backend.images import SubmissionJournal
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.editor_page import EditorPage
from morphorum_studio.ui.player_panel import PlayerPanel
from morphorum_studio.ui.projects_service import ProjectsService
from morphorum_studio.ui.render_service import RenderService
from morphorum_studio.ui.timeline_service import TimelineService

FEATURES = {"project_crud": True, "timeline": True, "animation_render": True}

QApplication.instance() or QApplication(["morphorum-studio-tests"])


class Both:
    """Timeline routes go to the editor double, render routes to the render double."""

    def __init__(self, editor, render):
        self.e, self.r = EditorClient(editor), RenderClient(render)

    @staticmethod
    def _render_path(path):
        return "/renders" in path and not path.endswith("/renders/") or path.startswith("/api/animation/renders")

    def get_json(self, path, params=None):
        return (self.r if self._render_path(path) else self.e).get_json(path, params)

    def get_json_etag(self, path, params=None):
        return self.e.get_json_etag(path, params)

    def send_json(self, method, path, body=None, **kwargs):
        return (self.r if path.startswith("/api/animation/renders") else self.e).send_json(
            method, path, body, **kwargs)

    def download(self, path, sink, max_bytes):
        return self.r.download(path, sink, max_bytes)


def sync_runner(client, fn, callback):
    from morphorum_studio.backend.client import BackendError
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def rig(tmp_path, renders=None, connect=True):
    editor, render = EditorBackend(), RenderBackend(tmp_path / "journal")
    render.renders = renders if renders is not None else {}
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Both(editor, render))
    projects = ProjectsService(session, runner=sync_runner)
    timeline = TimelineService(session, runner=sync_runner)
    rservice = RenderService(session, SubmissionJournal(tmp_path / "journal"), runner=sync_runner)
    page = EditorPage(session, projects, timeline, rservice)
    if connect:
        session.connected(info(features=FEATURES), "tok")
        projects.refresh()
    return render, session, projects, rservice, page


def downloads(render):
    return [c for c in render.calls if c[0] == "DOWNLOAD"]


# ----------------------------------------------------------------------------- the player

def test_player_transport_steps_clamps_and_reports_position():
    player = PlayerPanel()
    asked = []
    player.frame_requested.connect(asked.append)
    assert not player.play_button.isEnabled() and player.position.text() == ""
    player.set_range(10, 5.0)
    assert not player.first_button.isEnabled() and not player.prev_button.isEnabled()
    assert player.next_button.isEnabled() and player.position.text() == "Frame 1 / 10 · 0.00 s"
    player.next_button.click()
    player.next_button.click()
    assert asked == [1, 2] and player.frame == 2 and player.position.text() == "Frame 3 / 10 · 0.40 s"
    player.last_button.click()
    assert asked[-1] == 9 and not player.next_button.isEnabled()
    player.next_button.click()  # disabled at the end: nothing sent
    assert asked[-1] == 9
    player.first_button.click()
    assert asked[-1] == 0 and not player.prev_button.isEnabled()
    player.set_frame(99)  # owner moved the playhead: clamped, no signal
    assert player.frame == 9 and asked[-1] == 0
    player.set_range(0, 0.0)
    assert not player.last_button.isEnabled() and player.position.text() == ""


def test_player_play_advances_then_stops_at_the_last_frame():
    player = PlayerPanel()
    asked = []
    player.frame_requested.connect(asked.append)
    player.set_range(3, 24.0)
    player.toggle_play()
    assert player.playing and player.play_button.text() == "Pause"
    player._tick()
    player._tick()
    assert asked == [1, 2] and not player.playing and player.play_button.text() == "Play"
    player.toggle_play()  # already at the end: does not start
    assert not player.playing
    player.set_frame(0)
    player.toggle_play()
    player.toggle_play()
    assert not player.playing


def test_player_picture_and_messages():
    player = PlayerPanel()
    player.show_message("Frame 3 has not been rendered yet", "up to 2")
    assert not player.view.has_image and player.caption.text() == "up to 2"
    player.show_png(png(16, 9), "Render r1 · frame 1")
    assert player.view.has_image and player.caption.text() == "Render r1 · frame 1"
    player.show_png(b"junk")
    assert not player.view.has_image and "could not be read" in player.view.message


# ----------------------------------------------------------------------------- the workspace

def test_preview_shows_rendered_frames_once_and_says_when_a_frame_is_not_rendered(tmp_path):
    render, session, projects, rservice, page = rig(tmp_path, {"r1": [render_json("r1", "completed", 4)]})
    page.open_project("demo")
    assert page._player_job.id == "r1" and page.player.view.has_image
    assert page.player.caption.text() == "Render r1 · frame 1"
    assert len(downloads(render)) == 1
    page.frame_spin.setValue(10)
    page._settled()
    assert not page.player.view.has_image and "Frame 11 has not been rendered" in page.player.view.message
    assert page.player.position.text().startswith("Frame 11 /")
    page.frame_spin.setValue(2)
    page._settled()
    assert page.player.view.has_image and page.player.caption.text().endswith("frame 3")
    page.frame_spin.setValue(0)
    page._settled()
    assert len(downloads(render)) == 2  # frame 0 came from the cache the second time
    assert page.render_card._wanted_frame == 0


def test_transport_buttons_move_the_playhead_everywhere(tmp_path):
    render, session, projects, rservice, page = rig(tmp_path, {"r1": [render_json("r1", "completed", 4)]})
    page.open_project("demo")
    page.player.next_button.click()
    assert page.view.frame == 1 and page.frame_spin.value() == 1
    assert page.render_card._wanted_frame == 1 and page.player.caption.text().endswith("frame 2")
    page.player.last_button.click()
    assert page.view.frame == 47 and "has not been rendered" in page.player.view.message


def test_no_render_yet_says_how_to_get_one(tmp_path):
    render, session, projects, rservice, page = rig(tmp_path)
    page.open_project("demo")
    assert page._player_job is None and "No rendered frames" in page.player.view.message
    assert "Render the project" in page.player.caption.text()
    assert downloads(render) == []


def test_an_unreadable_frame_is_reported_and_not_refetched_forever(tmp_path):
    render, session, projects, rservice, page = rig(tmp_path, {"r1": [render_json("r1", "completed", 4)]})
    render.image = b"junk"  # not a PNG: the API refuses it
    page.open_project("demo")
    assert "not available" in page.player.view.message
    count = len(downloads(render))
    page._request_preview(0)
    page._request_preview(0)
    assert len(downloads(render)) == count


def test_a_newer_render_with_frames_replaces_the_previewed_one(tmp_path):
    from morphorum_studio.backend.renders import parse_render
    render, session, projects, rservice, page = rig(tmp_path, {"r1": [render_json("r1", "completed", 4)]})
    page.open_project("demo")
    assert page._player_job.id == "r1"
    newer = parse_render(render_json("r2", "rendering", 2, created_at="2026-10-14T08:00:00+00:00"))
    rservice.job_updated.emit(newer)
    assert page._player_job.id == "r2" and page.player.caption.text() == "Render r2 · frame 1"
    older = parse_render(render_json("r0", "completed", 4, created_at="2026-10-01T08:00:00+00:00"))
    rservice.job_updated.emit(older)
    assert page._player_job.id == "r2"


def test_open_project_waits_for_the_list_and_switching_projects_resets_the_preview(tmp_path):
    render, session, projects, rservice, page = rig(tmp_path, {"r1": [render_json("r1", "completed", 4)]},
                                                    connect=False)
    page.open_project("demo")
    assert page._pending_open == "demo"
    session.connected(info(features=FEATURES), "tok")
    projects.refresh()
    assert page._pending_open is None and page.project.currentData() == "demo"
    assert page.player.view.has_image
    page.project.setCurrentIndex(0)
    page._project_chosen(0)
    assert page._player_job is None and not page.player.view.has_image
    assert page.player.position.text() == ""


def test_compact_render_card_hides_its_picture_and_saves_only_rendered_playhead_frames(tmp_path):
    render, session, projects, rservice, page = rig(tmp_path, {"r1": [render_json("r1", "completed", 4)]})
    page.open_project("demo")
    card = page.render_card
    assert card.frame_view.isHidden() and card.slider.isHidden() and card.follow.isHidden()
    assert card.save_frame_button.isEnabled()  # frame 0 is rendered
    page.frame_spin.setValue(20)
    assert not card.save_frame_button.isEnabled()
    page.frame_spin.setValue(3)
    assert card.save_frame_button.isEnabled()
    assert all("frames/0" in c[1] for c in downloads(render))


def test_page_without_a_render_service_still_works(tmp_path):
    editor = EditorBackend()
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: EditorClient(editor))
    page = EditorPage(session, ProjectsService(session, runner=sync_runner),
                      TimelineService(session, runner=sync_runner))
    assert page.render_card is None and "once the backend can render" in page.player.view.message


# ----------------------------------------------------------------------------- library link

def test_library_button_opens_the_selected_project_in_the_timeline(tmp_path):
    from test_projects_ui import Client, Store
    from test_projects_ui import sync_runner as psync

    from morphorum_studio.ui.preferences import StudioPreferences
    from morphorum_studio.ui.projects_page import ProjectsPage
    store = Store()
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(store))
    service = ProjectsService(session, runner=psync)
    prefs = StudioPreferences(QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat))
    page = ProjectsPage(session, service, prefs, can_open_timeline=True)
    asked = []
    page.open_timeline.connect(asked.append)
    session.connected(info(features={"project_crud": True}), "tok")
    page.open_timeline_button.click()  # nothing selected yet
    assert asked == []
    page.open_project("alpha")
    page.open_timeline_button.click()
    assert asked == ["alpha"]
    assert not page.timeline_card.isHidden()
    plain = ProjectsPage(session, service, prefs)
    assert plain.timeline_card.isHidden()


def test_main_window_routes_library_to_timeline_and_shows_the_player(tmp_path):
    from morphorum_studio.ui.main_window import PAGES, StudioMainWindow
    from morphorum_studio.ui.preferences import StudioPreferences
    window = StudioMainWindow(
        preferences=StudioPreferences(QSettings(str(tmp_path / "w.ini"), QSettings.Format.IniFormat)),
        journal_dir=tmp_path / "j")
    try:
        names = [p[0] for p in PAGES]
        assert window.editor_page.render_card is not None and window.editor_page.player is not None
        window.projects_page.open_timeline.emit("demo")
        assert window.navigation.currentRow() == names.index("Editor")
        assert window.editor_page._pending_open == "demo"
    finally:
        window.close()
