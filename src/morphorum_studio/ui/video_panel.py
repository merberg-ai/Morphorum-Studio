"""Video export panel (S3.3), shown inside the render card for a completed render.

Sound is only ever described from the backend's own export record (``audio_included``); before
exporting, the panel says what the *render* froze, and warns when there is no soundtrack.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.images import JournalEntry
from morphorum_studio.backend.renders import RenderJob
from morphorum_studio.backend.videos import FORMATS, QUALITIES, VideoExport, audio_text, describe
from morphorum_studio.ui.video_service import VideoService

try:  # QtMultimedia is optional in a build; without it videos are saved, not played inline.
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget

    HAS_MULTIMEDIA = True
except ImportError:  # pragma: no cover - depends on the PySide6 build
    HAS_MULTIMEDIA = False


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class PlayerDialog(QDialog):
    """Plays a verified local copy with play/pause, a seek bar, volume and mute."""

    def __init__(self, title: str, path: str, audio_note: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 520)
        box = QVBoxLayout(self)
        self.video = QVideoWidget()
        self.video.setMinimumSize(480, 270)
        box.addWidget(self.video, 1)
        self.audio_label = _label(audio_note, "hint")
        box.addWidget(self.audio_label)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.player.setVideoOutput(self.video)
        row = QHBoxLayout()
        self.toggle = QPushButton("Pause")
        self.seek = _slider(0, 0)
        self.time = QLabel("0:00")
        self.mute = QCheckBox("Mute")
        self.volume = _slider(0, 100)
        self.volume.setValue(80)
        self.volume.setMaximumWidth(120)
        self.output.setVolume(0.8)
        for widget in (self.toggle, self.seek, self.time, self.mute, self.volume):
            row.addWidget(widget, 1 if widget is self.seek else 0)
        box.addLayout(row)
        self.status = _label("", "hint")
        box.addWidget(self.status)
        self.toggle.clicked.connect(self._toggle)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.volume.valueChanged.connect(lambda v: self.output.setVolume(v / 100))
        self.mute.toggled.connect(self.output.setMuted)
        self.player.positionChanged.connect(self._position)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
        self.player.errorOccurred.connect(lambda _e, text: self.status.setText(f"Playback error: {text}"))
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def _toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.toggle.setText("Play")
        else:
            self.player.play()
            self.toggle.setText("Pause")

    def _position(self, ms: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        seconds = ms // 1000
        self.time.setText(f"{seconds // 60}:{seconds % 60:02d}")

    def done(self, result: int) -> None:
        self.player.stop()
        super().done(result)


def _slider(low: int, high: int):
    from PySide6.QtWidgets import QSlider
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(low, high)
    return slider


class VideoPanel(QWidget):
    def __init__(self, service: VideoService) -> None:
        super().__init__()
        self._service = service
        self._project: str | None = None
        self._job: RenderJob | None = None
        self._exports: tuple[VideoExport, ...] = ()
        self._pending: list[JournalEntry] = []
        self._players: list[PlayerDialog] = []
        self._build()
        service.availability_ready.connect(lambda _a: self._update())
        service.list_ready.connect(self._list_ready)
        service.export_updated.connect(self._export_updated)
        service.pending_ready.connect(self._pending_ready)
        service.copy_saved.connect(lambda p: self.status.setText(f"Saved a verified copy to {p}"))
        service.playback_ready.connect(self._playback_ready)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(lambda: self.set_render(None, None))
        self._update()

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 8, 0, 0)
        box.setSpacing(8)
        box.addWidget(_label("Export video", "fieldLabel"))
        self.availability = _label("", "hint")
        box.addWidget(self.availability)
        self.audio_note = _label("", "notice")
        box.addWidget(self.audio_note)

        options = QHBoxLayout()
        self.format = QComboBox()
        for fmt in FORMATS:
            self.format.addItem(fmt.upper(), fmt)
        self.quality = QComboBox()
        for q in QUALITIES:
            self.quality.addItem(q.capitalize(), q)
        self.quality.setCurrentIndex(QUALITIES.index("balanced"))
        self.same_fps = QCheckBox("Original frame rate")
        self.same_fps.setChecked(True)
        self.fps = QSpinBox()
        self.fps.setRange(1, 120)
        self.fps.setValue(24)
        self.fps.setEnabled(False)
        for widget in (QLabel("Format"), self.format, QLabel("Quality"), self.quality,
                       self.same_fps, self.fps):
            options.addWidget(widget)
        options.addStretch(1)
        box.addLayout(options)
        self.same_fps.toggled.connect(lambda _on: self._update())

        row = QHBoxLayout()
        self.export_button = QPushButton("Export video")
        self.export_button.setObjectName("primaryAction")
        self.play_button = QPushButton("Play")
        self.save_button = QPushButton("Save video…")
        for button in (self.export_button, self.play_button, self.save_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            row.addWidget(button)
        row.addStretch(1)
        box.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        box.addWidget(self.progress)
        self.status = _label("", "hint")
        box.addWidget(self.status)
        self.listing = QListWidget()
        self.listing.setMaximumHeight(130)
        box.addWidget(self.listing)

        self.pending_label = _label("", "notice")
        self.pending_label.setVisible(False)
        box.addWidget(self.pending_label)
        pending = QHBoxLayout()
        self.pending_retry = QPushButton("Retry the same export")
        self.pending_discard = QPushButton("Discard")
        for button in (self.pending_retry, self.pending_discard):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setVisible(False)
            pending.addWidget(button)
        pending.addStretch(1)
        box.addLayout(pending)

        self.export_button.clicked.connect(self._export)
        self.play_button.clicked.connect(self._play)
        self.save_button.clicked.connect(self._save)
        self.listing.currentRowChanged.connect(lambda _r: self._update())
        self.pending_retry.clicked.connect(self._retry)
        self.pending_discard.clicked.connect(self._discard)

    # -- state ------------------------------------------------------------------------------

    def set_render(self, project_id: str | None, job: RenderJob | None) -> None:
        """Called by the render card whenever the selected render (or its status) changes."""
        was_done = bool(self._job and self._job.status == "completed")
        same = (project_id == self._project and job is not None and self._job is not None
                and job.id == self._job.id and (was_done or job.status != "completed"))
        self._project, self._job = project_id, job
        if not same:
            self._exports = ()
            self.listing.clear()
            self.progress.setValue(0)
            self.status.setText("")
            if project_id and job and job.status == "completed":
                self._service.load_availability()
                self._service.load_list(project_id, job.id)
                self._service.check_pending()
        self._update()

    def _selected(self) -> VideoExport | None:
        row = self.listing.currentRow()
        return self._exports[row] if 0 <= row < len(self._exports) else None

    def _update(self) -> None:
        job = self._job
        completed = bool(job and job.status == "completed" and self._project)
        self.setVisible(bool(self._project and job and job.final))
        avail = self._service.availability
        if not completed:
            self.availability.setText("Only a completed render can be exported. Resume it to finish the frames.")
        elif avail is None:
            self.availability.setText("Checking whether the backend host has FFmpeg…")
        elif avail.available:
            self.availability.setText("FFmpeg is available on the backend host.")
        else:
            self.availability.setText(
                "Video export is unavailable: FFmpeg was not found on the backend host. "
                + (avail.message or "Install FFmpeg there, or set MORPHORUM_FFMPEG."))
        if job and job.soundtrack:
            self.audio_note.setText(
                f"This render froze the soundtrack “{job.soundtrack}”. The backend will mux it in; if "
                "that file is missing or changed the export is refused (re-render after reattaching "
                "audio), and the audio is never silently dropped. The finished export states whether "
                "sound is included.")
        elif completed:
            self.audio_note.setText(
                "Warning: this render has no frozen soundtrack, so the video will most likely have no "
                "audio. The finished export tells you what the backend actually included.")
        else:
            self.audio_note.setText("")
        self.audio_note.setVisible(bool(self.audio_note.text()))
        frozen = bool(job and job.soundtrack)
        self.same_fps.setEnabled(not frozen)
        if frozen:
            self.same_fps.setChecked(True)  # The backend refuses an fps override with audio.
        self.fps.setEnabled(not self.same_fps.isChecked() and not frozen)
        ready = completed and bool(avail and avail.available) and self._service.available
        busy = self._service.busy or self._service.watched is not None
        self.export_button.setEnabled(ready and not busy)
        selected = self._selected()
        usable = bool(selected and selected.downloadable and self._service.available)
        self.save_button.setEnabled(usable)
        self.play_button.setEnabled(usable and HAS_MULTIMEDIA)
        self.play_button.setToolTip("" if HAS_MULTIMEDIA else "This build has no video playback; save the file instead.")
        self.pending_retry.setEnabled(self._service.available and not self._service.busy)

    # -- exporting --------------------------------------------------------------------------

    def _export(self) -> None:
        if not (self._project and self._job):
            return
        fps = None if self.same_fps.isChecked() else self.fps.value()
        self._service.start(self._project, self._job.id, self.format.currentData(),
                            self.quality.currentData(), fps)

    def _list_ready(self, project_id: str, render_id: str, exports) -> None:
        if project_id != self._project or not self._job or render_id != self._job.id:
            return
        self._exports = tuple(exports)
        self._fill()

    def _fill(self) -> None:
        current = self._selected()
        self.listing.blockSignals(True)
        self.listing.clear()
        for export in self._exports:
            self.listing.addItem(QListWidgetItem(describe(export)))
        self.listing.blockSignals(False)
        if self._exports:
            row = next((i for i, e in enumerate(self._exports)
                        if current and e.variant == current.variant), 0)
            self.listing.setCurrentRow(row)
        self._update()

    def _export_updated(self, export: VideoExport) -> None:
        if export.project_id != self._project or not self._job or export.render_id != self._job.id:
            return
        index = next((i for i, e in enumerate(self._exports) if e.variant == export.variant), None)
        if index is None:
            self._exports = (export,) + self._exports
        else:
            self._exports = self._exports[:index] + (export,) + self._exports[index + 1:]
        self._fill()
        self.progress.setValue(int(export.progress * 1000))
        if export.status == "completed":
            self.status.setText("Export finished. " + audio_text(export) + ".")
        elif export.status == "failed":
            self.status.setText("Export failed: " + (export.error or export.message or "unknown error"))
        elif export.active:
            self.status.setText(export.message or f"{export.status.capitalize()}…")

    # -- playing and saving -----------------------------------------------------------------

    def _play(self) -> None:
        export = self._selected()
        if export and export.downloadable:
            self.status.setText("Downloading a verified copy for playback…")
            self._service.prepare_playback(export)

    def _playback_ready(self, export: VideoExport, path: str) -> None:
        if not HAS_MULTIMEDIA:
            return
        self.status.setText("")
        dialog = PlayerDialog(f"Video — {describe(export)}", path, audio_text(export) + ".", self)
        self._players.append(dialog)
        dialog.finished.connect(lambda _r, d=dialog: self._players.remove(d) if d in self._players else None)
        dialog.show()

    def _save(self) -> None:
        export = self._selected()
        if not export or not export.downloadable:
            return
        name = f"{export.render_id}-{export.quality}-{export.fps}fps.{export.format}"
        path, _ = QFileDialog.getSaveFileName(self, "Save video", name,
                                              f"{export.format.upper()} video (*.{export.format})")
        if path:
            self.status.setText("Downloading and verifying…")
            self._service.save(export, path)

    # -- pending ----------------------------------------------------------------------------

    def _pending_ready(self, entries) -> None:
        self._pending = [e for e in entries if e.kind == "video"]
        self._show_pending()

    def _show_pending(self) -> None:
        has = bool(self._pending)
        self.pending_label.setVisible(has)
        self.pending_retry.setVisible(has)
        self.pending_discard.setVisible(has)
        if has:
            self.pending_label.setText(
                "A video export request may or may not have reached the backend. Retrying sends the "
                "same request with the same key, so it cannot start a second export.")

    def _retry(self) -> None:
        if self._pending:
            self._service.retry(self._pending[0])

    def _discard(self) -> None:
        for entry in self._pending:
            self._service.discard(entry.key)
        self._pending = []
        self._show_pending()

    def _failed(self, operation: str, code: str, message: str) -> None:
        if operation == "availability" and self._service.availability is None:
            self._update()
        self.status.setText(f"{operation.capitalize()} failed: {message}")
