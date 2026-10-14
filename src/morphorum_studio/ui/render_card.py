"""Render card (S3.2) for the open project: start, watch, cancel, resume, browse frames, preview.

Renders always use the *saved* project on the backend, so starting is paused while the form has
unsaved edits. Everything shown comes from the backend's job record.
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
)

from morphorum_studio.backend.images import JournalEntry
from morphorum_studio.backend.renders import RenderJob, render_text
from morphorum_studio.ui.render_service import RenderService

FRAME_BOX = QSize(420, 280)
CACHE_LIMIT = 24


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class PreviewDialog(QDialog):
    """Plays the backend's animated GIF preview."""

    save_requested = Signal()

    def __init__(self, title: str, data: bytes, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 520)
        self._bytes = QByteArray(data)
        self._buffer = QBuffer(self._bytes, self)
        self._buffer.open(QBuffer.OpenModeFlag.ReadOnly)
        self.movie = QMovie(self._buffer, QByteArray(b"gif"), self)
        box = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setMovie(self.movie)
        box.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.toggle = QPushButton("Pause")
        self.save = QPushButton("Save copy…")
        row.addWidget(self.toggle)
        row.addStretch(1)
        row.addWidget(self.save)
        box.addLayout(row)
        self.toggle.clicked.connect(self._toggle)
        self.save.clicked.connect(self.save_requested)
        self.movie.start()

    def _toggle(self) -> None:
        paused = self.movie.state() == QMovie.MovieState.Running
        self.movie.setPaused(paused)
        self.toggle.setText("Play" if paused else "Pause")


class RenderCard(QFrame):
    def __init__(self, service: RenderService, video_service=None, compact: bool = False) -> None:
        """``compact``: the host shows rendered frames itself (the Timeline player), so this card
        keeps its controls, status, history and saving but hides its own picture and slider and
        saves whichever frame the host reports with ``set_playhead``."""
        super().__init__()
        self._compact = compact
        self.setObjectName("card")
        self._video_service = video_service
        self._service = service
        self._project: str | None = None
        self._locked = False
        self._jobs: tuple[RenderJob, ...] = ()
        self._job: RenderJob | None = None
        self._follow = True
        self._wanted_frame: int | None = None
        self._pixmaps: dict[tuple[str, int], QPixmap] = {}
        self._requested: set[tuple[str, int]] = set()
        self._pending: list[JournalEntry] = []
        self._preview_for: str | None = None
        self._build()
        service.list_ready.connect(self._list_ready)
        service.submitted.connect(self._submitted)
        service.job_updated.connect(self._job_updated)
        service.pending_ready.connect(self._pending_ready)
        service.frame_ready.connect(self._frame_ready)
        service.preview_ready.connect(self._preview_ready)
        service.copy_saved.connect(self._copied)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(lambda: self.set_project(None))
        self._update()

    # -- construction -----------------------------------------------------------------------

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 20)
        box.setSpacing(10)
        box.addWidget(_label("Render", "cardTitle"))
        self.note = _label("", "hint", wrap=True)
        box.addWidget(self.note)

        self.pending_label = _label("", "notice", wrap=True)
        self.pending_label.setVisible(False)
        box.addWidget(self.pending_label)
        pending_row = QHBoxLayout()
        self.pending_retry = QPushButton("Retry the same request")
        self.pending_discard = QPushButton("Discard")
        for button in (self.pending_retry, self.pending_discard):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            pending_row.addWidget(button)
            button.setVisible(False)
        pending_row.addStretch(1)
        box.addLayout(pending_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_button = QPushButton("Render animation")
        self.start_button.setObjectName("primaryAction")
        self.cancel_button = QPushButton("Cancel")
        self.resume_button = QPushButton("Resume…")
        for button in (self.start_button, self.cancel_button, self.resume_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            actions.addWidget(button)
        actions.addStretch(1)
        box.addLayout(actions)

        history = QHBoxLayout()
        history.addWidget(_label("Renders", "fieldLabel"))
        self.render_combo = QComboBox()
        self.render_combo.setAccessibleName("Renders of this project")
        history.addWidget(self.render_combo, 1)
        box.addLayout(history)

        self.status = _label("No render yet.", "metricValue", wrap=True)
        box.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        box.addWidget(self.progress)
        self.detail = _label("", "hint", wrap=True)
        box.addWidget(self.detail)

        self.frame_view = QLabel("No frame yet")
        self.frame_view.setObjectName("assetThumb")
        self.frame_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_view.setFixedSize(FRAME_BOX)
        box.addWidget(self.frame_view, 0, Qt.AlignmentFlag.AlignLeft)
        slider_row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setAccessibleName("Frame")
        self.frame_label = _label("", "hint")
        self.follow = QCheckBox("Follow latest")
        self.follow.setChecked(True)
        slider_row.addWidget(self.slider, 1)
        slider_row.addWidget(self.frame_label)
        slider_row.addWidget(self.follow)
        box.addLayout(slider_row)
        media = QHBoxLayout()
        media.setSpacing(8)
        self.save_frame_button = QPushButton("Save frame…")
        self.play_button = QPushButton("Play preview")
        self.save_preview_button = QPushButton("Save preview…")
        for button in (self.save_frame_button, self.play_button, self.save_preview_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            media.addWidget(button)
        media.addStretch(1)
        box.addLayout(media)

        self.video_panel = None
        if self._video_service is not None:
            from morphorum_studio.ui.video_panel import VideoPanel
            self.video_panel = VideoPanel(self._video_service)
            box.addWidget(self.video_panel)

        if self._compact:
            for widget in (self.frame_view, self.slider, self.frame_label, self.follow):
                widget.setVisible(False)
        self.start_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self._cancel)
        self.resume_button.clicked.connect(self._resume)
        self.render_combo.activated.connect(self._combo_chosen)
        self.pending_retry.clicked.connect(self._retry)
        self.pending_discard.clicked.connect(self._discard)
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.sliderReleased.connect(self._slider_released)
        self.follow.toggled.connect(self._follow_toggled)
        self.save_frame_button.clicked.connect(self._save_frame)
        self.play_button.clicked.connect(self._play)
        self.save_preview_button.clicked.connect(self._save_preview)

    # -- project / state --------------------------------------------------------------------

    def set_project(self, project_id: str | None) -> None:
        if project_id == self._project:
            return
        self._project = project_id
        self._jobs = ()
        self._job = None
        self._follow = True
        self.follow.setChecked(True)
        self._pixmaps.clear()
        self._requested.clear()
        if not self._compact:
            self._wanted_frame = None
        self._pending = []
        self.render_combo.clear()
        self._show_idle()
        self._show_pending()
        if project_id:
            self._service.load_list(project_id)
            self._service.check_pending()
        self._update()

    def set_locked(self, locked: bool) -> None:
        """True while the project form has unsaved edits: a render would use the saved version."""
        if locked != self._locked:
            self._locked = locked
            self._update()

    def _show_idle(self) -> None:
        if self.video_panel is not None:
            self.video_panel.set_render(None, None)
        self.status.setText("No render yet.")
        self.detail.setText("")
        self.progress.setValue(0)
        self.frame_view.setPixmap(QPixmap())
        self.frame_view.setText("No frame yet")
        self.slider.blockSignals(True)
        self.slider.setRange(0, 0)
        self.slider.blockSignals(False)
        self.frame_label.setText("")

    def _update(self) -> None:
        job = self._job
        ready = self._project is not None and self._service.available
        busy = self._service.busy
        active = bool(job and job.active)
        self.start_button.setEnabled(ready and not busy and not active and not self._locked)
        self.note.setText(
            "Save or revert your edits first: a render uses the saved project." if self._locked
            else "Renders run on the backend using the saved project. Rendered frames are kept if it stops.")
        self.cancel_button.setEnabled(ready and active and not (job and job.cancel_requested))
        self.resume_button.setEnabled(ready and not busy and bool(job and job.final and job.resumable))
        has_frame = bool(job and job.latest_frame is not None)
        saveable = has_frame
        if self._compact:
            saveable = bool(has_frame and self._wanted_frame is not None
                            and self._wanted_frame <= (job.latest_frame or 0))
        self.save_frame_button.setEnabled(ready and saveable)
        self.play_button.setEnabled(ready and bool(job and job.has_preview))
        self.save_preview_button.setEnabled(ready and bool(job and job.has_preview))
        self.slider.setEnabled(has_frame)
        self.follow.setEnabled(has_frame)
        self.pending_retry.setEnabled(ready and not busy)

    # -- starting, cancelling, resuming -----------------------------------------------------

    def _start(self) -> None:
        if not self._project:
            return
        answer = QMessageBox.question(
            self, "Render animation",
            "Start rendering the saved version of this project on the backend?\n\n"
            "This uses the GPU and can take a long time. You can cancel, and rendered frames are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._service.start(self._project)

    def _cancel(self) -> None:
        if self._job and self._job.active:
            self._service.cancel(self._job.id)

    def _resume(self) -> None:
        job = self._job
        if not job or not self._project:
            return
        done = job.completed_frames
        answer = QMessageBox.question(
            self, "Resume render",
            f"Continue this render from the {done} frame{'s' if done != 1 else ''} already rendered?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._service.resume(self._project, job.id)

    # -- results from the service -----------------------------------------------------------

    def _submitted(self, entry: JournalEntry, job: RenderJob) -> None:
        self._pending = [e for e in self._pending if e.key != entry.key]
        self._show_pending()
        if job.project_id == self._project:
            self._service.load_list(job.project_id)

    def _list_ready(self, project_id: str, jobs) -> None:
        if project_id != self._project:
            return
        self._jobs = tuple(jobs)
        self._fill_combo()
        if not self._jobs:
            return
        live = next((j for j in self._jobs if j.active), None)
        chosen = live or (next((j for j in self._jobs if self._job and j.id == self._job.id), None)
                          or self._jobs[0])
        self.render_combo.setCurrentIndex(self._jobs.index(chosen))
        self._select(chosen)

    def _fill_combo(self) -> None:
        self.render_combo.blockSignals(True)
        current = self.render_combo.currentIndex()
        self.render_combo.clear()
        for job in self._jobs:
            when = job.created_at[:16].replace("T", " ") if job.created_at else "?"
            self.render_combo.addItem(f"{when}  ·  {job.status}  ·  {job.completed_frames} frame(s)")
        if 0 <= current < self.render_combo.count():
            self.render_combo.setCurrentIndex(current)
        self.render_combo.blockSignals(False)

    def _combo_chosen(self, index: int) -> None:
        if 0 <= index < len(self._jobs):
            self._select(self._jobs[index])

    def _select(self, job: RenderJob) -> None:
        self._job = job
        self._follow = True
        self.follow.setChecked(True)
        if not self._compact:
            self._wanted_frame = None
        self._show_job(job)
        if job.active and self._service.watched != job.id:
            self._service.watch(job.id)

    def _job_updated(self, job: RenderJob) -> None:
        if job.project_id != self._project:
            return
        if self._job is not None and self._job.id != job.id and not job.active:
            return  # a stale answer about another render
        index = next((i for i, j in enumerate(self._jobs) if j.id == job.id), None)
        if index is not None:
            self._jobs = self._jobs[:index] + (job,) + self._jobs[index + 1:]
        else:
            self._jobs = (job,) + self._jobs
        self._fill_combo()
        if self._job is None or self._job.id == job.id or job.active:
            self._job = job
            self.render_combo.blockSignals(True)
            self.render_combo.setCurrentIndex(next(i for i, j in enumerate(self._jobs) if j.id == job.id))
            self.render_combo.blockSignals(False)
            self._show_job(job)

    def _show_job(self, job: RenderJob) -> None:
        if self.video_panel is not None:
            self.video_panel.set_render(self._project, job)
        text = render_text(job)
        if job.cancel_requested and job.active:
            text += " (cancelling…)"
        self.status.setText(text)
        self.progress.setValue(int(max(0.0, min(1.0, job.progress)) * 1000))
        bits = []
        if job.average_frame_seconds:
            bits.append(f"about {job.average_frame_seconds:.1f} s per frame")
        if job.soundtrack:
            bits.append(f"soundtrack frozen into this render: {job.soundtrack}")
        if job.hybrid:
            bits.append("uses hybrid video")
        self.detail.setText(" · ".join(bits))
        latest = job.latest_frame
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, latest or 0))
        if latest is None:
            self.slider.setValue(0)
        elif self._follow:
            self.slider.setValue(latest)
        self.slider.blockSignals(False)
        if latest is None:
            self.frame_label.setText("")
            self.frame_view.setPixmap(QPixmap())
            self.frame_view.setText("No frame yet")
        else:
            self._want(self.slider.value())
        self._update()

    # -- frames -----------------------------------------------------------------------------

    def set_playhead(self, frame: int) -> None:
        """Compact mode: the frame "Save frame…" will save."""
        if self._compact and frame != self._wanted_frame:
            self._wanted_frame = frame
            self._update()

    def _want(self, frame: int) -> None:
        job = self._job
        if job is None or self._compact:
            return
        self._wanted_frame = frame
        total = f" of {job.total_frames}" if job.total_frames else ""
        self.frame_label.setText(f"frame {frame + 1}{total}")
        pixmap = self._pixmaps.get((job.id, frame))
        if pixmap is not None:
            self._set_frame(pixmap)
        elif (job.id, frame) not in self._requested and self._project:
            self._requested.add((job.id, frame))
            self._service.fetch_frame(self._project, job.id, frame)

    def _set_frame(self, pixmap: QPixmap) -> None:
        self.frame_view.setText("")
        self.frame_view.setPixmap(pixmap.scaled(
            FRAME_BOX, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _frame_ready(self, render_id: str, frame: int, data) -> None:
        key = (render_id, frame)
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            while len(self._pixmaps) >= CACHE_LIMIT:
                oldest = next(iter(self._pixmaps))
                del self._pixmaps[oldest]
                self._requested.discard(oldest)
            self._pixmaps[key] = pixmap
            if self._job and self._job.id == render_id and self._wanted_frame == frame:
                self._set_frame(pixmap)
        else:
            self._requested.discard(key)
            if self._job and self._job.id == render_id and self._wanted_frame == frame:
                self.frame_view.setPixmap(QPixmap())
                self.frame_view.setText("This frame is not available")

    def _slider_changed(self, value: int) -> None:
        # Moving off the newest frame stops following; returning to it resumes following.
        self._follow = value >= self.slider.maximum()
        self.follow.blockSignals(True)
        self.follow.setChecked(self._follow)
        self.follow.blockSignals(False)
        if not self.slider.isSliderDown():
            self._want(value)

    def _slider_released(self) -> None:
        self._want(self.slider.value())

    def _follow_toggled(self, on: bool) -> None:
        self._follow = on
        if on and self._job and self._job.latest_frame is not None:
            self.slider.setValue(self._job.latest_frame)

    # -- preview and saving -----------------------------------------------------------------

    def _play(self) -> None:
        if self._job and self._project:
            self._preview_for = self._job.id
            self.detail.setText("Loading the preview…")
            self._service.fetch_preview(self._project, self._job.id)

    def _preview_ready(self, render_id: str, data) -> None:
        if render_id != self._preview_for:
            return
        self._preview_for = None
        if not data:
            self.detail.setText("The preview could not be loaded.")
            return
        if self._job:
            self._show_job(self._job)
        dialog = PreviewDialog("Render preview", data, self)
        dialog.save_requested.connect(self._save_preview)
        dialog.exec()

    def _save_frame(self) -> None:
        job = self._job
        if not job or not self._project or self._wanted_frame is None:
            return
        frame = self._wanted_frame
        path, _ = QFileDialog.getSaveFileName(
            self, "Save frame", f"{self._project}-frame-{frame:05d}.png", "PNG image (*.png)")
        if path:
            self._service.save_frame(self._project, job.id, frame, path)

    def _save_preview(self) -> None:
        job = self._job
        if not job or not self._project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save preview", f"{self._project}-preview.gif", "GIF image (*.gif)")
        if path:
            self._service.save_preview(self._project, job.id, path)

    def _copied(self, path: str) -> None:
        self.detail.setText(f"Saved a copy to {path}")

    # -- unfinished submissions -------------------------------------------------------------

    def _pending_ready(self, entries) -> None:
        self._pending = list(entries)
        self._show_pending()

    def _show_pending(self) -> None:
        visible = bool(self._pending)
        for widget in (self.pending_label, self.pending_retry, self.pending_discard):
            widget.setVisible(visible)
        if visible:
            project = self._pending[0].payload.get("project", {})
            name = project.get("name") or project.get("id") or "a project"
            self.pending_label.setText(
                f"A render request for “{name}” may not have reached the backend. Retrying sends the "
                "same request with the same key, so it cannot start a second render.")

    def _retry(self) -> None:
        if self._pending:
            self._service.retry(self._pending[0])

    def _discard(self) -> None:
        if self._pending:
            self._service.discard(self._pending[0].key)
            self._pending.pop(0)
            self._show_pending()

    # -- errors -----------------------------------------------------------------------------

    def _failed(self, operation: str, code: str, message: str) -> None:
        titles = {"start": "Could not start the render", "resume": "Could not resume the render",
                  "cancel": "Could not cancel", "copy": "Could not save the copy"}
        if operation in titles:
            QMessageBox.warning(self, titles[operation], message)
        elif operation == "job":
            self.detail.setText(f"Lost track of the render ({code}). Pick it from the list to look again.")
        elif operation == "list":
            self.detail.setText(f"Could not load this project's renders ({code}).")
        self._update()
