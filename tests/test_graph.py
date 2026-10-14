"""S5.3: the pipeline graph model, its loader and the Graph page (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import QApplication
from test_timeline_api import SNAPSHOT

from morphorum_studio.backend.assets import Soundtrack
from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.graph import build_graph, duration_text
from morphorum_studio.backend.projects import parse_project
from morphorum_studio.backend.session import BackendSession, SessionInfo
from morphorum_studio.backend.timeline import parse_timeline
from morphorum_studio.ui.graph_page import GraphCanvas, GraphPage, layout
from morphorum_studio.ui.graph_service import GraphService

QApplication.instance() or QApplication(["morphorum-studio-tests"])

FEATURES = {"project_crud": True, "timeline": True}
SHA = "a" * 64


def project_payload(pid="demo", **extra):
    project = {
        "id": pid, "name": pid.title(),
        "animation": {"width": 512, "height": 768, "fps": 24, "max_frames": 48, "mode": "3D",
                      "start_mode": "image", "source_image_name": "cat.png"},
        "model": {"model_id": "sdxl-aaa", "family": "sdxl", "variant": "base"},
        "prompts": {"0": "a cat", "24": "a dog"},
        "motion_lab": {"layers": [{"type": "preset"}, {"type": "audio"}, {"type": "audio"}]},
        "hybrid": {"enabled": False},
    }
    project.update(extra)
    return {"project": project}


def soundtrack_payload():
    return {"soundtrack": {"filename": "song.mp3", "format": "mp3", "bytes": 1234,
                           "offset_seconds": 0.5, "sha256": SHA}}


def timeline_payload(pid="demo"):
    return {**SNAPSHOT, "project_id": pid}


class Fake:
    def __init__(self):
        self.fail_timeline = self.fail_soundtrack = False
        self.soundtrack = soundtrack_payload()

    def get_json(self, path, params=None):
        if path == "/api/animation/projects":
            return {"projects": [{"id": "demo", "name": "Demo", "updated_at": "2026-10-02T00:00:00Z"},
                                 {"id": "other", "name": "Other", "updated_at": "2026-10-03T00:00:00Z"}]}
        pid = path.split("/")[4] if path.startswith("/api/animation/projects/") else None
        if path.endswith("/timeline"):
            if self.fail_timeline:
                raise BackendError("UNAVAILABLE", "down")
            return timeline_payload(pid)
        if path.endswith("/motion-import/soundtrack"):
            if self.fail_soundtrack:
                raise BackendError("UNAVAILABLE", "down")
            return self.soundtrack
        raise BackendError("NOT_FOUND", path)

    def get_json_etag(self, path):
        pid = path.rsplit("/", 1)[1]
        return project_payload(pid), '"' + "e" * 64 + '"'


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def rig(features=None, client=None):
    client = client or Fake()
    session = BackendSession(client_factory=lambda base, token, timeout=6.0: client)
    service = GraphService(session, runner=sync_runner)
    page = GraphPage(session, service)
    info = SessionInfo("p1", "Workshop", "http://10.0.0.5:7866", "0.1.0", "backend-only", "i1", "b1",
                       FEATURES if features is None else features)
    session.connected(info, "t")
    return client, session, service, page


def graph_of(payload=None, timeline=True, soundtrack=True):
    detail = parse_project(payload or project_payload())
    return build_graph(detail, parse_timeline(timeline_payload()) if timeline else None,
                       Soundtrack("song.mp3", "mp3", 1, 0.5, SHA) if soundtrack else None)


def test_graph_shape_and_states():
    graph = graph_of()
    assert [n.id for n in graph.nodes] == ["source", "checkpoint", "prompts", "schedules", "camera",
                                           "motion", "audio", "export"]
    assert graph.node("prompts").state == "on" and graph.node("prompts").summary == "2 prompt keyframes"
    assert graph.node("camera").summary.startswith("3D")
    assert graph.node("motion").summary == "1 layer"  # audio layers are counted under Audio
    assert graph.node("audio").summary == "2 audio layers" and graph.node("audio").state == "on"
    assert ("Soundtrack", "song.mp3") in graph.node("audio").rows
    assert graph.node("export").summary == "512×768 · 48 frames · 2.0 s at 24 fps"
    assert all(a in {n.id for n in graph.nodes} and b in {n.id for n in graph.nodes}
               for a, b in graph.edges)


def test_unused_stages_are_off_and_missing_pieces_warn():
    bare = project_payload(motion_lab={"layers": []}, prompts={},
                           model={}, animation={"mode": "2D", "start_mode": "image"})
    graph = graph_of(bare, timeline=False, soundtrack=False)
    assert graph.node("motion").state == "off" and graph.node("audio").state == "off"
    assert graph.node("checkpoint").state == "warn" and graph.node("prompts").state == "warn"
    assert graph.node("source").state == "warn"  # image start but no image
    assert graph.node("camera").summary == "2D · still"
    only_audio = graph_of(timeline=True, soundtrack=False)
    assert only_audio.node("audio").state == "warn"  # audio layers without a soundtrack


def test_camera_and_schedule_rows_come_from_the_timeline():
    graph = graph_of()
    assert ("2D Zoom", "2 keyframes") in graph.node("camera").rows
    assert graph.node("camera").summary == "3D · 1 animated track"
    assert duration_text(None, None) == "unknown length"


def test_layout_keeps_nodes_inside_and_apart():
    graph = graph_of()
    rects = layout(graph, 900, 400)
    assert set(rects) == {n.id for n in graph.nodes}
    for rect in rects.values():
        assert 0 <= rect.left() and rect.right() <= 900 and 0 <= rect.top() and rect.bottom() <= 400
    ids = list(rects)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            assert not rects[a].intersects(rects[b])


def test_page_loads_the_project_list_then_the_newest_project():
    client, session, service, page = rig()
    page.set_active(True)
    assert page.project.count() == 2 and page.project.currentData() == "other"  # newest first
    assert page.canvas.graph is not None and page.canvas.graph.project_id == "other"
    assert page.node_title.text() == "Source"
    assert page.open_button.text() == "Open in Library"


def test_selecting_a_stage_fills_the_inspector_and_opens_its_workspace():
    client, session, service, page = rig()
    page.set_active(True)
    page.canvas.select("camera")
    assert page.node_title.text() == "Camera" and page.rows_box.count() >= 2
    assert page.open_button.text() == "Edit in Timeline"
    seen = []
    page.open_target.connect(lambda key, pid: seen.append((key, pid)))
    page.open_button.click()
    assert seen == [("Editor", "other")]


def test_clicking_and_arrow_keys_select_stages():
    client, session, service, page = rig()
    page.set_active(True)
    page.canvas.resize(900, 400)
    rect = page.canvas.rects()["prompts"]
    assert page.canvas.node_at(rect.center() + QPointF(10, 10)) == "prompts"
    assert page.canvas.node_at(QPointF(0, 0)) is None
    canvas = page.canvas
    canvas.select("prompts")
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    assert canvas.current == "camera"
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier))
    assert canvas.current == "prompts"
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
    assert canvas.current == "schedules"


def test_timeline_and_soundtrack_failures_do_not_hide_the_pipeline():
    client = Fake()
    client.fail_timeline = client.fail_soundtrack = True
    _c, _s, service, page = rig(client=client)
    page.set_active(True)
    graph = page.canvas.graph
    assert graph is not None and graph.node("camera").state == "off"
    assert ("Soundtrack", "none attached") in graph.node("audio").rows


def test_choose_project_and_show_project():
    client, session, service, page = rig()
    page.set_active(True)
    page.project.setCurrentIndex(page.project.findData("demo"))
    page._chosen(page.project.currentIndex())
    assert page.canvas.graph.project_id == "demo"
    page.show_project("other")
    assert page.project.currentData() == "other" and page.canvas.graph.project_id == "other"


def test_stale_answer_for_another_project_is_ignored():
    client, session, service, page = rig()
    page.set_active(True)
    page.project.setCurrentIndex(page.project.findData("demo"))
    page.canvas.set_graph(None)
    page._loaded(graph_of(project_payload("other")))  # an answer for the project we left
    assert page.canvas.graph is None
    page._loaded(graph_of(project_payload("demo")))
    assert page.canvas.graph.project_id == "demo"


def test_unsupported_backend_and_disconnect():
    client, session, service, page = rig(features={})
    page.set_active(True)
    assert not service.available and "does not offer" in page.status_line.text()
    assert not page.body.isVisibleTo(page)
    client2, session2, service2, page2 = rig()
    page2.set_active(True)
    session2.disconnected()
    assert not service2.available and page2.canvas.graph is None
    assert "Connect to a Morphorum backend" in page2.status_line.text()


def test_empty_canvas_and_failure_message_paint_without_error():
    canvas = GraphCanvas()
    canvas.resize(600, 300)
    pixmap = QPixmap(600, 300)
    canvas.render(pixmap)
    canvas.set_graph(graph_of())
    canvas.render(pixmap)
    assert canvas.accessibleDescription().startswith("Source")
    client, session, service, page = rig()
    page._failed("graph", "UNAVAILABLE", "down")
    assert "down" in page.status_line.text()
