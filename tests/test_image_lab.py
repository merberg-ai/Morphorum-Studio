"""Image Lab service and page against a scripted fake backend (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


from fakes import info
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.images import SubmissionJournal
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.image_lab_page import ImageLabPage
from morphorum_studio.ui.image_service import ImageLabService
from morphorum_studio.ui.preferences import StudioPreferences

FEATURES = {"sdxl_generation": True, "model_discovery": True, "idempotent_submissions": True}
CAPS = {"families": {
    "sdxl": {"supported": True, "label": "SDXL", "steps": {"default": 25, "min": 1, "max": 100},
             "guidance": {"label": "CFG", "default": 6.0, "min": 1.0, "max": 30.0},
             "negative_prompt": True, "default_resolution": {"width": 1024, "height": 1024},
             "samplers": {"default": "euler", "options": [{"id": "euler"}, {"id": "dpmpp_2m"}]},
             "resolutions": [{"label": "Square", "width": 1024, "height": 1024},
                             {"label": "Portrait", "width": 832, "height": 1216}]},
    "flux": {"supported": True, "label": "Flux", "steps": {"default": 28, "min": 1, "max": 50},
             "guidance": {"label": "CFG", "default": 1.0, "min": 0.0, "max": 10.0},
             "negative_prompt": False, "default_resolution": {"width": 1024, "height": 1024},
             "samplers": {"default": "flowmatch_euler", "options": [{"id": "flowmatch_euler"}]},
             "variants": {"schnell": {"label": "Flux Schnell", "steps": {"default": 4, "min": 1, "max": 8},
                                      "guidance": {"default": 0.0, "min": 0.0, "max": 0.0}}}},
    "other": {"supported": False, "label": "Other"},
}}


def model(mid, family, name, kind="checkpoints", filename="f.safetensors"):
    return {"id": mid, "family": family, "kind": kind, "name": name, "filename": filename,
            "path": "D:\\secret", "size_bytes": 1, "variant": None, "source": "external"}


MODELS = [model("sdxl-1", "sdxl", "Juggernaut"), model("flux-1", "flux", "Flux Schnell", filename="schnell.safetensors"),
          model("odd-1", "other", "Odd"),
          model("lora-1", "sdxl", "Ink Style", kind="loras"), model("lora-2", "sdxl", "bad:name", kind="loras"),
          model("lora-3", "flux", "Flux Lora", kind="loras")]


def png_bytes(w=8, h=8):
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    from PySide6.QtCore import QBuffer, QByteArray
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data)


def job_json(job_id="img-1", status="queued", results=0, progress=0.0, **extra):
    data = {"id": job_id, "status": status, "message": status, "progress": progress,
            "current_image": 0, "current_step": 0, "total_steps": 25, "eta_seconds": None,
            "seeds": [], "error": None, "cancel_requested": False,
            "request": {"images": max(results, 1), "prompt": "a cat"}, "model": {"name": "Juggernaut"},
            "created_at": "2026-10-13T08:00:00+00:00",
            "results": [{"index": i + 1, "seed": 100 + i, "filename": f"img-{i + 1}.png"} for i in range(results)]}
    data.update(extra)
    return data


class Backend:
    def __init__(self, journal_dir):
        self.journal_dir = journal_dir
        self.calls, self.posts = [], []
        self.jobs = {}  # id -> list of states served in order (last repeats)
        self.fail_post = None
        self.journal_during_post = None
        self.image = png_bytes()

    def next_state(self, job_id):
        states = self.jobs.get(job_id)
        if not states:
            raise BackendError("NOT_FOUND", "Backend returned HTTP 404", 404)
        return states.pop(0) if len(states) > 1 else states[0]


class Client:
    def __init__(self, backend):
        self.b = backend

    def get_json(self, path, params=None):
        self.b.calls.append(("GET", path, params))
        if path == "/api/models":
            kind = (params or {}).get("kind")
            return {"models": [m for m in MODELS if not kind or m["kind"] == kind]}
        if path == "/api/generation/capabilities":
            return CAPS
        if path == "/api/generation/jobs":
            return {"jobs": [job_json("old-1", "completed", 2, 1.0)]}
        if path.startswith("/api/generation/jobs/"):
            return self.b.next_state(path.rsplit("/", 1)[1])
        raise BackendError("NOT_FOUND", "no route", 404)

    def send_json(self, method, path, body=None, *, if_match=None, idempotency_key=None):
        self.b.calls.append((method, path, body, idempotency_key))
        if path.endswith("/cancel"):
            job_id = path.split("/")[-2]
            self.b.jobs[job_id] = [job_json(job_id, "cancelled")]
            return job_json(job_id, "cancelled"), None
        self.b.posts.append((idempotency_key, body))
        self.b.journal_during_post = [e.key for e in SubmissionJournal(self.b.journal_dir).entries()]
        if self.b.fail_post:
            raise self.b.fail_post
        job_id = "img-" + str(len(self.b.posts))
        self.b.jobs.setdefault(job_id, [job_json(job_id, "queued")])
        return self.b.jobs[job_id][0], None

    def download(self, path, sink, max_bytes):
        self.b.calls.append(("DOWNLOAD", path))
        sink(self.b.image)
        return len(self.b.image), "0" * 64, None


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def make(tmp_path, features=FEATURES, connect=True, page=True):
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    backend = Backend(tmp_path / "journal")
    session = BackendSession(client_factory=lambda url, token, timeout=6.0: Client(backend))
    journal = SubmissionJournal(tmp_path / "journal")
    service = ImageLabService(session, journal, runner=sync_runner)
    prefs = StudioPreferences(QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat))
    widget = ImageLabPage(session, service, prefs) if page else None
    if connect:
        session.connected(info(features=features), "tok")
    return backend, session, service, journal, prefs, widget


def ready_page(tmp_path):
    backend, session, service, journal, prefs, page = make(tmp_path)
    page.set_active(True)
    return backend, session, service, journal, prefs, page


# ----------------------------------------------------------------------------- service

def test_submit_is_journalled_before_post_and_cleared_when_job_ends(tmp_path):
    backend, session, service, journal, *_ = make(tmp_path, page=False)
    seen = []
    service.job_updated.connect(seen.append)
    service.submit({"prompt": "a cat"})
    assert len(backend.journal_during_post) == 1  # the entry existed on disk during the POST
    key, body = backend.posts[0]
    assert key == backend.journal_during_post[0] and body == {"prompt": "a cat"}
    assert journal.entries()[0].state == "submitted" and journal.entries()[0].job_id == "img-1"
    backend.jobs["img-1"] = [job_json("img-1", "generating", progress=0.5), job_json("img-1", "completed", 1, 1.0)]
    service.poll_now()
    service.poll_now()
    assert [j.status for j in seen][-2:] == ["generating", "completed"] and seen[0].status == "queued"
    assert journal.entries() == [] and service.watched is None


def test_definitive_refusal_removes_journal_entry(tmp_path):
    backend, session, service, journal, *_ = make(tmp_path, page=False)
    failures = []
    service.failed.connect(lambda *a: failures.append(a))
    backend.fail_post = BackendError("INVALID_REQUEST", "Backend returned HTTP 400: Prompt cannot be empty.", 400)
    service.submit({"prompt": ""})
    assert failures[0][:2] == ("submit", "INVALID_REQUEST") and journal.entries() == []
    assert not service.submitting


def test_ambiguous_failure_keeps_entry_and_retry_reuses_key(tmp_path):
    backend, session, service, journal, *_ = make(tmp_path, page=False)
    pending, failures = [], []
    service.pending_ready.connect(pending.append)
    service.failed.connect(lambda *a: failures.append(a))
    backend.fail_post = BackendError("NETWORK_ERROR", "Unable to reach backend")
    service.submit({"prompt": "a cat"})
    entry = journal.entries()[0]
    assert entry.state == "pending" and pending and failures[0][1] == "NETWORK_ERROR"
    backend.fail_post = None
    service.retry(entry)
    assert [p[0] for p in backend.posts] == [entry.key, entry.key]
    assert backend.posts[0][1] == backend.posts[1][1]
    assert journal.entries()[0].state == "submitted"


def test_check_pending_reconciles(tmp_path):
    backend, session, service, journal, *_ = make(tmp_path, page=False)
    gone = journal.submitted(journal.begin("p1", {"a": 1}), "img-gone")
    done = journal.submitted(journal.begin("p1", {"a": 2}), "img-done")
    live = journal.submitted(journal.begin("p1", {"a": 3}), "img-live")
    unknown = journal.begin("p1", {"a": 4})
    journal.begin("other-profile", {"a": 5})
    backend.jobs["img-done"] = [job_json("img-done", "completed", 1, 1.0)]
    backend.jobs["img-live"] = [job_json("img-live", "generating", progress=0.2)]
    pending, updates = [], []
    service.pending_ready.connect(pending.append)
    service.job_updated.connect(updates.append)
    service.check_pending()
    keys = {e.key for e in journal.entries("p1")}
    assert gone.key not in keys and done.key not in keys and live.key in keys and unknown.key in keys
    assert [e.key for e in pending[0]] == [unknown.key]
    assert service.watched == "img-live" and updates[-1].id == "img-live"
    assert len(journal.entries("other-profile")) == 1


def test_epoch_change_stops_watching(tmp_path):
    backend, session, service, journal, *_ = make(tmp_path, page=False)
    service.submit({"prompt": "x"})
    assert service.watched == "img-1"
    cleared = []
    service.cleared.connect(lambda: cleared.append(1))
    session.disconnected()
    assert service.watched is None and cleared and not service._timer.isActive()


def test_polling_gives_up_after_repeated_failures(tmp_path):
    backend, session, service, *_ = make(tmp_path, page=False)
    failures = []
    service.failed.connect(lambda *a: failures.append(a))
    service.watch("img-x")  # backend has no such job: 404 ends it at once
    assert failures[0][:2] == ("job", "NOT_FOUND") and service.watched is None


def test_cancel_updates_job(tmp_path):
    backend, session, service, *_ = make(tmp_path, page=False)
    service.submit({"prompt": "x"})
    seen = []
    service.job_updated.connect(seen.append)
    service.cancel("img-1")
    assert seen[-1].status == "cancelled" and service.watched is None


def test_not_available_without_feature(tmp_path):
    backend, session, service, *_ = make(tmp_path, features={}, page=False)
    service.submit({"prompt": "x"})
    service.load_setup()
    assert backend.calls == [] and not service.available


# ----------------------------------------------------------------------------- page

def test_page_states_without_connection_or_feature(tmp_path):
    *_, page = make(tmp_path, connect=False)
    assert "Connect to a Morphorum backend" in page.status_line.text() and not page.generate_button.isEnabled()
    *_, page = make(tmp_path, features={"model_discovery": True})
    assert "does not advertise image generation" in page.status_line.text()


def test_page_loads_models_and_applies_limits(tmp_path):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    names = [page.model_combo.itemText(i) for i in range(page.model_combo.count())]
    assert len(names) == 2 and "Odd" not in " ".join(names)  # unsupported family is hidden
    assert page.steps_spin.value() == 25 and page.guidance_spin.value() == 6.0
    assert page.size_combo.currentText().startswith("Square") and page.negative_edit.isVisibleTo(page)
    page.model_combo.setCurrentIndex(1)  # Flux Schnell
    assert (page.steps_spin.minimum(), page.steps_spin.maximum(), page.steps_spin.value()) == (1, 8, 4)
    assert not page.guidance_spin.isEnabled() and not page.negative_edit.isVisibleTo(page)
    assert page.width_spin.singleStep() == 16
    assert [page.lora_combo.itemText(i) for i in range(page.lora_combo.count())] == ["Flux Lora"]
    page.model_combo.setCurrentIndex(0)
    assert [page.lora_combo.itemText(i) for i in range(page.lora_combo.count())] == ["Ink Style"]  # bad:name hidden


def test_selected_model_is_remembered(tmp_path):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    page.model_combo.setCurrentIndex(1)
    assert prefs.image_model("p1") == "flux-1"
    page._cleared()
    service.load_setup()
    assert page.model_combo.currentData() == "flux-1"


def test_lora_button_inserts_tag(tmp_path):
    *_, page = ready_page(tmp_path)
    page.prompt_edit.setPlainText("a cat")
    page.lora_weight.setValue(0.65)
    page.lora_button.click()
    assert page.prompt_edit.toPlainText() == "a cat <lora:Ink Style:0.65>"


def test_generate_validation_messages(tmp_path):
    backend, *_, page = ready_page(tmp_path)
    page.generate_button.click()
    assert "prompt" in page.problem_label.text().lower() and backend.posts == []
    page.prompt_edit.setPlainText("a cat")
    page.width_spin.setValue(1020)
    page.generate_button.click()
    assert "multiple of 8" in page.problem_label.text()
    page.width_spin.setValue(1024)
    page.seed_edit.setText("-")
    page.generate_button.click()
    assert "Seed" in page.problem_label.text() and backend.posts == []


def test_generate_sends_exact_payload_and_shows_progress_and_results(tmp_path):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    page.prompt_edit.setPlainText("  a cat  ")
    page.negative_edit.setPlainText("blurry")
    page.count_spin.setValue(2)
    page.seed_edit.setText("42")
    page.seed_mode.setCurrentIndex(1)
    page.increment_spin.setValue(3)
    page.generate_button.click()
    key, body = backend.posts[0]
    assert body == {"model_id": "sdxl-1", "prompt": "a cat", "negative_prompt": "blurry", "width": 1024,
                    "height": 1024, "steps": 25, "guidance_scale": 6.0, "sampler": "euler", "seed": 42,
                    "seed_mode": "increment", "seed_increment": 3, "images": 2}
    assert key.startswith("studio-") and not page.problem_label.isVisibleTo(page)
    assert page.job_status.text() == "Waiting in the queue" and not page.generate_button.isEnabled()
    assert page.cancel_button.isEnabled()
    backend.jobs["img-1"] = [job_json("img-1", "generating", progress=0.4, current_step=10, eta_seconds=30)]
    service.poll_now()
    assert page.progress.value() == 400 and "step 10 of 25" in page.job_status.text()
    backend.jobs["img-1"] = [job_json("img-1", "completed", 2, 1.0)]
    service.poll_now()
    assert page.generate_button.isEnabled() and not page.cancel_button.isEnabled()
    assert page.results_grid.count() == 2 and page.job_status.text() == "Done, 2 images"
    assert ("DOWNLOAD", "/api/generation/jobs/img-1/images/img-1.png") in backend.calls
    assert ("img-1", "img-1.png") in page._pixmaps  # thumbnails arrived


def test_cancel_button(tmp_path):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    page.prompt_edit.setPlainText("a cat")
    page.generate_button.click()
    page.cancel_button.click()
    assert page.job_status.text() == "Cancelled" and page.generate_button.isEnabled()


def test_refused_submission_shows_reason(tmp_path, monkeypatch):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append((a[1], a[2])))
    backend.fail_post = BackendError("INVALID_REQUEST", "Backend returned HTTP 400: The selected checkpoint file no longer exists.", 400)
    page.prompt_edit.setPlainText("a cat")
    page.generate_button.click()
    assert shown == [("Could not start the job", "Backend returned HTTP 400: The selected checkpoint file no longer exists.")]
    assert journal.entries() == [] and page.generate_button.isEnabled()


def test_pending_banner_retry_and_discard(tmp_path, monkeypatch):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    backend.fail_post = BackendError("NETWORK_ERROR", "Unable to reach backend")
    page.prompt_edit.setPlainText("a lonely cat")
    page.generate_button.click()
    assert page.pending_card.isVisibleTo(page) and "a lonely cat" in page.pending_label.text()
    backend.fail_post = None
    page.pending_retry.click()
    assert backend.posts[0][0] == backend.posts[1][0]  # same idempotency key
    assert not page.pending_card.isVisibleTo(page) and page.job_status.text() == "Waiting in the queue"
    # discard path
    page._pending = [journal.begin("p1", {"prompt": "x"})]
    page._show_pending()
    page.pending_discard.click()
    assert journal.entries("p1") == [e for e in journal.entries("p1") if e.job_id] and not page.pending_card.isVisibleTo(page)


def test_earlier_jobs_list_and_selection(tmp_path):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    assert page.recent_combo.count() == 2
    page.recent_combo.setCurrentIndex(1)
    page._recent_chosen(1)
    assert page.results_grid.count() == 2 and page.job_status.text() == "Done, 2 images"


def test_viewer_opens_and_saves_copy(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from morphorum_studio.ui import image_lab_page as module
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    page.recent_combo.setCurrentIndex(1)
    page._recent_chosen(1)
    opened = []
    monkeypatch.setattr(module.ImageViewer, "exec", lambda self: opened.append(self) or 0)
    page._open("old-1", "img-1.png")
    assert opened and opened[0]._pixmap.width() == 8
    out = tmp_path / "copy.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    saved = []
    service.copy_saved.connect(saved.append)
    # The fake client's download writes through the sink; save_copy checks the PNG header.
    opened[0].save_requested.emit()
    assert out.read_bytes() == backend.image and saved == [str(out)]


def test_viewer_zoom_steps(tmp_path):
    from PySide6.QtGui import QPixmap

    from morphorum_studio.ui.image_viewer import ImageViewer
    QApplication.instance() or QApplication([])
    pixmap = QPixmap()
    pixmap.loadFromData(png_bytes(40, 20))
    viewer = ImageViewer("t", pixmap)
    viewer.set_zoom(1.0)
    viewer.in_button.click()
    assert viewer.current_zoom() == 1.5
    viewer.out_button.click()
    viewer.out_button.click()
    assert viewer.current_zoom() == 0.75
    viewer.show_fit()
    assert "40×20" in viewer.zoom_label.text()


def test_disconnect_clears_page(tmp_path):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    page.prompt_edit.setPlainText("a cat")
    page.generate_button.click()
    session.disconnected()
    assert page.model_combo.count() == 0 and page.results_grid.count() == 0
    assert not page.generate_button.isEnabled() and page.job_title.text() == "No job yet."


def test_main_window_wiring(tmp_path):
    from morphorum_studio.ui.main_window import PAGES, StudioMainWindow
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "w.ini"), QSettings.Format.IniFormat)
    window = StudioMainWindow(preferences=StudioPreferences(settings), journal_dir=tmp_path / "j")
    try:
        names = [p[0] for p in PAGES]
        assert window.pages.widget(names.index("Image Lab")) is window.image_lab_page
        assert not window.image_lab_page._active
        window.navigation.setCurrentRow(names.index("Image Lab"))
        assert window.image_lab_page._active
        window.navigation.setCurrentRow(names.index("Home"))
        assert not window.image_lab_page._active
        window.navigation.setCurrentRow(names.index("Image Lab"))
        window.image_lab_page.connect_button.click()
        assert window.navigation.currentRow() == names.index("Settings")
    finally:
        window.close()


def finished_page(tmp_path):
    backend, session, service, journal, prefs, page = ready_page(tmp_path)
    page.prompt_edit.setPlainText("a cat")
    page.count_spin.setValue(2)
    page.generate_button.click()
    backend.jobs["img-1"] = [job_json("img-1", "completed", 2, 1.0)]
    service.poll_now()
    return backend, service, page


def test_stage_shows_first_result_and_thumbnails_select(tmp_path):
    backend, service, page = finished_page(tmp_path)
    keys = list(page._buttons)
    assert len(keys) == 2 and page._selected == keys[0]
    assert page._buttons[keys[0]].property("selected") is True
    assert page.stage_save_button.isEnabled() and page.stage_open_button.isEnabled()
    page._buttons[keys[1]].click()
    assert page._selected == keys[1] and page._buttons[keys[0]].property("selected") is False
    assert keys[1][1] in page.stage_info.text()


def test_seed_lock_follows_selected_result(tmp_path):
    backend, service, page = finished_page(tmp_path)
    key = page._selected
    page._seeds[key] = 777
    page._select_result(*key)
    page.seed_lock.setChecked(True)
    assert page.seed_edit.text() == "777" and page.seed_mode.currentData() == "fixed"
    page.seed_lock.setChecked(False)
    assert page.seed_edit.text() == "-1"


def test_lora_rows_edit_the_prompt(tmp_path):
    *_, page = ready_page(tmp_path)
    page.prompt_edit.setPlainText("a cat <lora:Ink Style:0.5> here")
    assert page.lora_weights.names == ["Ink Style"]
    page.lora_weights._sliders[0].setValue(20)  # 1.0
    assert page.prompt_edit.toPlainText() == "a cat <lora:Ink Style:1> here"
    page.lora_weights.removed.emit(0)
    assert page.prompt_edit.toPlainText() == "a cat here" and page.lora_weights.names == []


def test_aspect_tiles_come_from_backend_presets(tmp_path):
    *_, page = ready_page(tmp_path)
    assert [t.text().split("\n")[0] for t in page.aspect_tiles] == ["Square", "Portrait"]
    page.aspect_tiles[1].click()
    assert (page.width_spin.value(), page.height_spin.value()) == (832, 1216)
    assert page.aspect_tiles[1].isChecked() and not page.aspect_tiles[0].isChecked()


def test_cleared_resets_stage(tmp_path):
    backend, service, page = finished_page(tmp_path)
    page._cleared()
    assert page._selected is None and not page.stage_save_button.isEnabled()
