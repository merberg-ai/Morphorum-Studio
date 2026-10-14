"""Audio Director controls for the Motion Lab (S5.2a): file loading and audition, the audio layer
form, and the envelope view with the threshold and the pulses the backend will make.

Channel ideas (frequency bands steering camera axes, level or transient detection, threshold,
attack/return, minimum gap, timing offset) follow Deforum Motion Studio by chicodog530.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.audio import (
    BAND_LABELS,
    BANDS,
    DETECTION_LABELS,
    DETECTIONS,
    AudioAnalysis,
    frames_to_seconds,
    seconds_to_frames,
)
from morphorum_studio.backend.motion import AXES, AXIS_LABELS
from morphorum_studio.ui.audio_decode import AUDIO_EXTENSIONS, AudioDecoder
from morphorum_studio.ui.audio_service import AudioService
from morphorum_studio.ui.lab_widgets import LinkedSlider
from morphorum_studio.ui.tokens import DARK

try:  # optional in a build; without it the audition button explains itself
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:  # pragma: no cover - depends on the PySide6 build
    QAudioOutput = QMediaPlayer = None

AUDITION_TICK_MS = 33


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _color(hex_value: str, alpha: int = 255) -> QColor:
    color = QColor(hex_value)
    color.setAlpha(alpha)
    return color


def duration_text(seconds: float) -> str:
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}:{rest:02d}"


# ----------------------------------------------------------------------------- audition

class Audition(QObject):
    """Plays the sound from the playhead and reports the frame it has reached, in real time."""

    frame = Signal(int)
    stopped = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None, player_factory=None) -> None:
        super().__init__(parent)
        self._factory = player_factory or (QMediaPlayer if QMediaPlayer is not None else None)
        self._player = None
        self._output = None
        self._fps = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(AUDITION_TICK_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def supported(self) -> bool:
        return self._factory is not None

    @property
    def playing(self) -> bool:
        return self._timer.isActive()

    def play(self, path: str, start_frame: int, fps: float) -> None:
        if self._factory is None:
            self.failed.emit("This Studio build cannot play audio.")
            return
        self.stop()
        self._fps = fps
        if self._player is None:
            self._player = self._factory(self)
            if QAudioOutput is not None and self._factory is QMediaPlayer:
                self._output = QAudioOutput(self)
                self._player.setAudioOutput(self._output)
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.setPosition(int(start_frame / fps * 1000))
        self._player.play()
        self._timer.start()

    def stop(self) -> None:
        was = self._timer.isActive()
        self._timer.stop()
        if self._player is not None:
            self._player.pause()
        if was:
            self.stopped.emit()

    def _tick(self) -> None:
        if self._player is None or self._fps <= 0:
            return
        self.frame.emit(int(self._player.position() / 1000.0 * self._fps))
        ended = getattr(QMediaPlayer, "MediaStatus", None)
        if ended is not None and self._player.mediaStatus() == ended.EndOfMedia:
            self.stop()


# ----------------------------------------------------------------------------- controls

class AudioControls(QWidget):
    """Load a sound file, show what was analysed, and audition it against the timeline."""

    analysis_ready = Signal(object)  # AudioAnalysis
    playhead_requested = Signal(int)

    def __init__(self, service: AudioService, decoder: AudioDecoder | None = None,
                 audition: Audition | None = None) -> None:
        super().__init__()
        self._service = service
        self._decoder = decoder or AudioDecoder(self)
        self._audition = audition or Audition(self)
        self._project_id: str | None = None
        self._frames = 0
        self._fps = 0.0
        self._usable = False
        self._pending_file = ""
        self._analysis: AudioAnalysis | None = None
        self._frame = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.load_button = QPushButton("Load audio…")
        self.load_button.setToolTip("WAV, MP3, FLAC, OGG or M4A. The file is not changed.")
        self.audition_button = QPushButton("Audition")
        self.audition_button.setToolTip("Play the sound from the playhead; the playhead follows it")
        row.addWidget(self.load_button)
        row.addWidget(self.audition_button)
        row.addStretch(1)
        box.addLayout(row)
        self.status = _label("", "hint", wrap=True)
        box.addWidget(self.status)
        self.load_button.clicked.connect(self._choose)
        self.audition_button.clicked.connect(self._toggle_audition)
        self._decoder.finished.connect(self._decoded)
        self._decoder.failed.connect(self._decode_failed)
        service.analyzed.connect(self._analyzed)
        service.failed.connect(self._service_failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(self.clear)
        self._audition.frame.connect(self.playhead_requested)
        self._audition.stopped.connect(self._update)
        self._audition.failed.connect(self._set_status)
        self._update()

    # -- state ----------------------------------------------------------------------------

    @property
    def analysis(self) -> AudioAnalysis | None:
        return self._analysis

    @property
    def audition(self) -> Audition:
        return self._audition

    def configure(self, project_id: str | None, frames: int, fps: float, usable: bool) -> None:
        """Called when a project loads (or Motion Lab becomes unusable for it)."""
        self._audition.stop()
        self._project_id, self._frames, self._fps, self._usable = project_id, frames, fps, usable
        self._analysis = None
        self._pending_file = ""
        self._set_status("")
        self._update()

    def clear(self) -> None:
        self.configure(None, 0, 0.0, False)

    def set_playhead(self, frame: int) -> None:
        self._frame = frame

    def stop_audition(self) -> None:
        self._audition.stop()

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _update(self) -> None:
        busy = self._decoder.busy or self._service.busy
        self.load_button.setEnabled(bool(self._usable and not busy))
        playable = self._analysis is not None and bool(self._service.playable(self._analysis.sha256)
                                                       or self._pending_file)
        self.audition_button.setEnabled(bool(playable and self._audition.supported))
        self.audition_button.setText("Stop" if self._audition.playing else "Audition")

    # -- loading ---------------------------------------------------------------------------

    def _choose(self) -> None:
        patterns = " ".join("*" + ext for ext in AUDIO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(self, "Choose audio", "", f"Audio ({patterns});;All files (*)")
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        if not self._usable or self._fps <= 0:
            return
        self._audition.stop()
        self._pending_file = path
        self._set_status("Preparing the audio…")
        self._decoder.load(path, self._frames / self._fps)
        self._update()

    def _decoded(self, wav: bytes, _seconds: float) -> None:
        self._set_status("Analysing on the backend…")
        self._service.analyze(wav, self._pending_file)
        self._update()

    def _decode_failed(self, message: str) -> None:
        self._pending_file = ""
        self._set_status(message)
        self._update()

    def _service_failed(self, operation: str, code: str, message: str) -> None:
        self._set_status(message or code)
        self._update()

    def _analyzed(self, analysis: AudioAnalysis, _path: str) -> None:
        self._analysis = analysis
        match = abs(analysis.fps - self._fps) < 1e-6 and analysis.frames == self._frames
        note = "" if match else ("  The project's frame rate or length differs from this analysis; load the "
                                 "audio again.")
        self._set_status(f"Analysed: {duration_text(analysis.duration)} of audio at "
                         f"{analysis.fps:g} fps, {analysis.frames} frames.{note}")
        self._update()
        self.analysis_ready.emit(analysis)

    # -- audition --------------------------------------------------------------------------

    def _toggle_audition(self) -> None:
        if self._audition.playing:
            self._audition.stop()
            return
        if self._analysis is None:
            return
        path = self._service.playable(self._analysis.sha256) or self._pending_file
        if path:
            self._audition.play(path, self._frame, self._fps)
            self._update()


# ----------------------------------------------------------------------------- envelope view

class EnvelopeView(QWidget):
    """One audio layer's envelope across the video, its threshold, and the pulses it will make."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._layer: dict | None = None
        self._pulses: list[float] = []
        self._total = 0
        self._frame = 0
        self._stale = False

    def set_layer(self, layer: dict | None, total_frames: int, pulses=None, stale: bool = False) -> None:
        self._layer, self._total = layer, total_frames
        self._pulses = list(pulses or [])
        self._stale = stale
        self.update()

    def set_frame(self, frame: int) -> None:
        self._frame = frame
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _color(DARK.void))
        layer = self._layer
        font = QFont(DARK.font_ui)
        font.setPixelSize(11)
        painter.setFont(font)
        if not layer or not layer.get("envelope") or self._total < 2:
            painter.setPen(_color(DARK.faint))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Select an audio layer")
            return
        pad = 8
        w, h = self.width() - 2 * pad, self.height() - 2 * pad
        start = int(layer.get("start_frame", 0))
        envelope = layer["envelope"]

        def px(frame: float) -> float:
            return pad + w * frame / max(1, self._total - 1)

        def py(value: float) -> float:
            return pad + h * (1 - value)

        painter.setPen(_color(DARK.line))
        painter.drawLine(QPointF(pad, py(0)), QPointF(pad + w, py(0)))
        # the layer's own range is brighter than the rest of the video
        painter.fillRect(QRectF(px(start), pad, max(1.0, px(start + len(envelope)) - px(start)), h),
                         _color(DARK.cyan, 14))
        painter.setPen(QPen(_color(DARK.cyan, 120 if self._stale else 255), 1.2))
        previous = None
        for i, value in enumerate(envelope):
            point = QPointF(px(start + i), py(value))
            if previous is not None:
                painter.drawLine(previous, point)
            previous = point
        threshold = layer.get("threshold")
        if isinstance(threshold, (int, float)):
            painter.setPen(QPen(_color(DARK.warn, 200), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(pad, py(threshold)), QPointF(pad + w, py(threshold)))
        if self._pulses and not self._stale:
            top = max((abs(p) for p in self._pulses), default=0.0)
            if top > 0:
                mid = py(0.5)
                painter.setPen(QPen(_color(DARK.ok), 2))
                for i, value in enumerate(self._pulses):
                    if value:
                        x = px(start + i)
                        painter.drawLine(QPointF(x, mid), QPointF(x, mid - (h * 0.4) * value / top))
        painter.setPen(QPen(_color(DARK.warn), 1.2))
        x = px(min(self._frame, self._total - 1))
        painter.drawLine(QPointF(x, pad), QPointF(x, pad + h))


# ----------------------------------------------------------------------------- layer form

class AudioLayerForm(QWidget):
    """Edits one audio layer. Times are shown in seconds and stored as whole frames."""

    edited = Signal(str, object)  # field name, new value

    def __init__(self) -> None:
        super().__init__()
        self._fps = 0.0
        self._loading = False
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(96)
        self.name_edit.setPlaceholderText("Layer name")
        self.axis_combo = QComboBox()
        for axis in AXES:
            self.axis_combo.addItem("Drives: " + AXIS_LABELS[axis], axis)
        self.band_combo = QComboBox()
        for band in BANDS:
            self.band_combo.addItem(BAND_LABELS[band], band)
        self.detection_combo = QComboBox()
        for mode in DETECTIONS:
            self.detection_combo.addItem(DETECTION_LABELS[mode], mode)
        for widget in (self.name_edit, self.axis_combo, self.band_combo, self.detection_combo):
            box.addWidget(widget)

        self.threshold_spin = self._spin(0.0, 1.0, 0.05, 2)
        self.threshold_slider = LinkedSlider(self.threshold_spin, scale=100)
        self.sensitivity_spin = self._spin(0.0, 1.0, 0.05, 2)
        self.distance_spin = self._spin(0.0, 1.0, 0.005, 3)
        self.attack_spin = self._spin(0.0, 5.0, 0.01, 3, " s")
        self.release_spin = self._spin(0.0, 5.0, 0.01, 3, " s")
        self.gap_spin = self._spin(0.0, 5.0, 0.01, 3, " s")
        self.offset_spin = self._spin(-30.0, 30.0, 0.01, 3, " s")
        box.addLayout(self._pair(("Threshold", self.threshold_spin), ("Strength", self.distance_spin)))
        box.addWidget(self.threshold_slider)
        self.sensitivity_row = self._pair(("Transient sensitivity", self.sensitivity_spin))
        box.addLayout(self.sensitivity_row)
        box.addLayout(self._pair(("Attack", self.attack_spin), ("Return", self.release_spin)))
        box.addLayout(self._pair(("Minimum gap", self.gap_spin), ("Timing offset", self.offset_spin)))
        self.lock_note = _label("", "hint", wrap=True)
        box.addWidget(self.lock_note)

        self.name_edit.textEdited.connect(lambda t: self._emit("name", t))
        self.axis_combo.activated.connect(lambda _i: self._emit("axis", self.axis_combo.currentData()))
        self.band_combo.activated.connect(lambda _i: self._emit("band", self.band_combo.currentData()))
        self.detection_combo.activated.connect(self._detection_chosen)
        self.threshold_spin.valueChanged.connect(lambda v: self._emit("threshold", round(v, 4)))
        self.sensitivity_spin.valueChanged.connect(lambda v: self._emit("sensitivity", round(v, 4)))
        self.distance_spin.valueChanged.connect(lambda v: self._emit("distance", round(v, 4)))
        self.attack_spin.valueChanged.connect(lambda v: self._emit_frames("attack_frames", v, 1))
        self.release_spin.valueChanged.connect(lambda v: self._emit_frames("release_frames", v, 1))
        self.gap_spin.valueChanged.connect(lambda v: self._emit_frames("cooldown_frames", v, 0))
        self.offset_spin.valueChanged.connect(lambda v: self._emit_frames("offset_frames", v, -3000))

    @staticmethod
    def _spin(low: float, high: float, step: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    @staticmethod
    def _pair(*cells) -> QHBoxLayout:
        row = QHBoxLayout()
        for text, spin in cells:
            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell.addWidget(_label(text, "fieldLabel"))
            cell.addWidget(spin)
            row.addLayout(cell)
        return row

    # -- editing --------------------------------------------------------------------------

    def _emit(self, field: str, value) -> None:
        if not self._loading:
            self.edited.emit(field, value)

    def _emit_frames(self, field: str, seconds: float, minimum: int) -> None:
        if not self._loading and self._fps > 0:
            self.edited.emit(field, seconds_to_frames(seconds, self._fps, minimum))

    def _detection_chosen(self, _index: int) -> None:
        self._set_sensitivity_visible(self.detection_combo.currentData() == "transient")
        self._emit("detection", self.detection_combo.currentData())

    def _set_sensitivity_visible(self, visible: bool) -> None:
        for i in range(self.sensitivity_row.count()):
            item = self.sensitivity_row.itemAt(i).layout()
            if item is None:
                continue
            for j in range(item.count()):
                widget = item.itemAt(j).widget()
                if widget is not None:
                    widget.setVisible(visible)

    def load(self, layer: dict, fps: float, analysis_ready: bool) -> None:
        self._loading = True
        self._fps = fps
        try:
            self.name_edit.setText(str(layer.get("name", "")))
            self.axis_combo.setCurrentIndex(max(0, self.axis_combo.findData(layer.get("axis"))))
            self.band_combo.setCurrentIndex(max(0, self.band_combo.findData(layer.get("band", "fullband"))))
            detection = layer.get("detection", "level")
            self.detection_combo.setCurrentIndex(max(0, self.detection_combo.findData(detection)))
            self._set_sensitivity_visible(detection == "transient")
            self.threshold_spin.setValue(float(layer.get("threshold", 0.25)))
            self.sensitivity_spin.setValue(float(layer.get("sensitivity", 0.35)))
            self.distance_spin.setValue(float(layer.get("distance", 0.04)))
            self.attack_spin.setValue(frames_to_seconds(int(layer.get("attack_frames", 1)), fps))
            self.release_spin.setValue(frames_to_seconds(int(layer.get("release_frames", 3)), fps))
            self.gap_spin.setValue(frames_to_seconds(int(layer.get("cooldown_frames", 3)), fps))
            self.offset_spin.setValue(frames_to_seconds(int(layer.get("offset_frames", 0)), fps))
            self.band_combo.setEnabled(analysis_ready)
            self.lock_note.setVisible(not analysis_ready)
            self.lock_note.setText(
                "" if analysis_ready else
                "The frequency band and frame range can change once this layer's audio is analysed. "
                "Studio is loading it from the backend, or load the audio again.")
        finally:
            self._loading = False
