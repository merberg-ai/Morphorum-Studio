"""Motion Lab panel (S5.1): compose six-axis camera motion from preset and curve layers.

The panel edits a draft list of layers. Preview asks the backend to compile the draft and shows the
six resolved per-frame curves; Apply saves the result into the project's camera tracks (after a
confirmation if hand-edited camera tracks would be replaced). Layers it cannot edit yet (recorded
takes, audio pulses) are kept as stored and can be switched off, moved or removed.
"""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.motion import (
    AXES,
    AXIS_LABELS,
    INTERPOLATIONS,
    MAX_KEYS,
    MAX_LAYERS,
    PRESETS,
    MotionPreview,
    MotionState,
    describe_layer,
    editable,
    new_curve_layer,
    new_preset_layer,
    preset_label,
    unique_id,
)
from morphorum_studio.backend.audio import (
    STARTERS,
    AudioAnalysis,
    new_audio_layer,
    refit_envelope,
)
from morphorum_studio.ui.audio_service import AudioService
from morphorum_studio.ui.audio_widgets import AudioControls, AudioLayerForm, EnvelopeView
from morphorum_studio.ui.motion_service import MotionService
from morphorum_studio.ui.tokens import DARK

AXIS_COLORS = {
    "translation_x": DARK.cyan, "translation_y": DARK.ok, "translation_z": DARK.warn,
    "rotation_x": DARK.violet, "rotation_y": DARK.blue, "rotation_z": DARK.bad,
}


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _color(hex_value: str, alpha: int = 255) -> QColor:
    color = QColor(hex_value)
    color.setAlpha(alpha)
    return color


class MotionChart(QWidget):
    """The backend's resolved per-frame values for each camera axis, with the playhead."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._series: dict[str, tuple[float, ...]] = {}
        self._shown = set(AXES)
        self._frame = 0
        self._stale = False
        self._message = "Press Preview to see the camera motion"

    def set_series(self, series: dict[str, tuple[float, ...]]) -> None:
        self._series, self._stale = dict(series), False
        self.update()

    def clear(self, message: str = "") -> None:
        self._series = {}
        self._message = message or self._message
        self.update()

    def set_shown(self, axes) -> None:
        self._shown = set(axes)
        self.update()

    def set_stale(self, stale: bool) -> None:
        if stale != self._stale:
            self._stale = stale
            self.update()

    def set_frame(self, frame: int) -> None:
        self._frame = frame
        self.update()

    @property
    def has_data(self) -> bool:
        return bool(self._series)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _color(DARK.void))
        font = QFont(DARK.font_ui)
        font.setPixelSize(11)
        painter.setFont(font)
        shown = [a for a in AXES if a in self._shown and len(self._series.get(a, ())) > 1]
        if not shown:
            painter.setPen(_color(DARK.faint))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self._message if not self._series else "No axes selected")
            return
        count = max(len(self._series[a]) for a in shown)
        low = min(min(self._series[a]) for a in shown)
        high = max(max(self._series[a]) for a in shown)
        if high - low < 1e-9:
            low, high = low - 1e-3, high + 1e-3
        pad_l, pad_r, pad_t, pad_b = 46, 10, 8, 8
        w, h = self.width() - pad_l - pad_r, self.height() - pad_t - pad_b

        def px(frame: float) -> float:
            return pad_l + w * frame / max(1, count - 1)

        def py(value: float) -> float:
            return pad_t + h * (1 - (value - low) / (high - low))

        painter.setPen(_color(DARK.line))
        for value in (low, (low + high) / 2, high):
            painter.drawLine(QPointF(pad_l, py(value)), QPointF(pad_l + w, py(value)))
            painter.setPen(_color(DARK.faint))
            painter.drawText(QRectF(0, py(value) - 8, pad_l - 6, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{value:.3g}")
            painter.setPen(_color(DARK.line))
        if low < 0 < high:
            painter.setPen(_color(DARK.line2))
            painter.drawLine(QPointF(pad_l, py(0)), QPointF(pad_l + w, py(0)))
        for axis in shown:
            painter.setPen(QPen(_color(AXIS_COLORS[axis], 110 if self._stale else 255), 1.5))
            painter.drawPolyline(QPolygonF([QPointF(px(i), py(v)) for i, v in enumerate(self._series[axis])]))
        painter.setPen(QPen(_color(DARK.warn), 1.2))
        x = px(min(self._frame, count - 1))
        painter.drawLine(QPointF(x, pad_t), QPointF(x, pad_t + h))
        if self._stale:
            painter.setPen(_color(DARK.warn))
            painter.drawText(QRectF(pad_l, pad_t, w, 16), Qt.AlignmentFlag.AlignRight, "out of date")


class MotionPanel(QFrame):
    applied = Signal(str)  # project id: the camera tracks changed, reload the timeline
    playhead_requested = Signal(int)  # audition moved the playhead

    def __init__(self, service: MotionService, audio_service: AudioService | None = None,
                 audio_decoder=None, audition=None) -> None:
        super().__init__()
        self.setObjectName("card")
        self._service = service
        self._audio_service = audio_service
        self._audio_decoder, self._audition = audio_decoder, audition
        self._analysis: AudioAnalysis | None = None
        self._recovering: set[str] = set()
        self._pulses: dict[str, list] = {}
        self._pulses_stale = True
        self._soundtrack_text = ""
        self._playhead = 0
        self._project_id: str | None = None
        self._state: MotionState | None = None
        self._saved: list[dict] = []
        self._layers: list[dict] = []
        self._presets: tuple[str, ...] = PRESETS
        self._loading = False
        self._error = ""
        self._build()
        service.loaded.connect(self._loaded)
        service.previewed.connect(self._previewed)
        service.applied.connect(self._applied)
        service.conflict.connect(self._conflict)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(self.clear)
        service.soundtrack_known.connect(self._soundtrack_known)
        if self.audio is not None:
            self.audio.analysis_ready.connect(self._analysis_ready)
            self.audio.playhead_requested.connect(self.playhead_requested)
            audio_service.failed.connect(self._audio_failed)
        self._update()

    # -- construction -------------------------------------------------------------------

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 14, 16, 16)
        box.setSpacing(8)
        box.addWidget(_label("Motion Lab", "cardTitle"))
        self.status = _label("", "hint", wrap=True)
        box.addWidget(self.status)

        self.layer_list = QListWidget()
        self.layer_list.setMinimumHeight(110)
        self.layer_list.setMaximumHeight(150)
        self.layer_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.layer_list.setAccessibleName("Motion layers")
        box.addWidget(self.layer_list)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.add_preset_button = QPushButton("+ Preset")
        self.add_curve_button = QPushButton("+ Curve")
        self.duplicate_button = QPushButton("Copy")
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("↑")
        self.down_button = QPushButton("↓")
        self.up_button.setToolTip("Move the layer up (applied earlier)")
        self.down_button.setToolTip("Move the layer down (applied later)")
        for button in (self.add_preset_button, self.add_curve_button, self.duplicate_button,
                       self.remove_button, self.up_button, self.down_button):
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            row.addWidget(button)
        self.add_audio_button = QPushButton("+ Audio")
        self.add_audio_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.audio_menu = QMenu(self.add_audio_button)
        for label, name, band, axis, distance, detection in STARTERS:
            action = self.audio_menu.addAction(label)
            action.triggered.connect(
                lambda _c=False, n=name, b=band, a=axis, d=distance, m=detection:
                self._add_audio(n, b, a, d, m))
        self.add_audio_button.setMenu(self.audio_menu)
        row.insertWidget(2, self.add_audio_button)
        box.addLayout(row)

        self.audio = None
        if self._audio_service is not None:
            self.audio = AudioControls(self._audio_service, self._audio_decoder, self._audition)
            box.addWidget(_label("Audio", "fieldLabel"))
            box.addWidget(self.audio)
            self.soundtrack_note = _label("", "hint", wrap=True)
            box.addWidget(self.soundtrack_note)
        else:
            self.add_audio_button.setVisible(False)

        # -- editor for the selected layer
        self.editor = QWidget()
        ebox = QVBoxLayout(self.editor)
        ebox.setContentsMargins(0, 4, 0, 0)
        ebox.setSpacing(6)
        common = QHBoxLayout()
        self.blend_combo = QComboBox()
        self.blend_combo.addItem("Add to camera", "add")
        self.blend_combo.addItem("Replace camera", "replace")
        self.start_spin = QSpinBox()
        self.end_spin = QSpinBox()
        self.start_spin.setPrefix("from ")
        self.end_spin.setPrefix("to ")
        self.start_spin.setToolTip("First frame of the layer")
        self.end_spin.setToolTip("Frame after the last one (exclusive)")
        common.addWidget(self.blend_combo, 1)
        common.addWidget(self.start_spin)
        common.addWidget(self.end_spin)
        ebox.addLayout(common)

        self.forms = QStackedWidget()
        self.forms.addWidget(QWidget())  # 0: nothing editable
        preset_form = QWidget()
        pform = QVBoxLayout(preset_form)
        pform.setContentsMargins(0, 0, 0, 0)
        pform.setSpacing(6)
        self.preset_combo = QComboBox()
        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(0.0, 1.0)
        self.strength_spin.setSingleStep(0.05)
        self.strength_spin.setDecimals(2)
        self.cycle_spin = QDoubleSpinBox()
        self.cycle_spin.setRange(0.2, 600.0)
        self.cycle_spin.setSingleStep(0.5)
        self.cycle_spin.setSuffix(" s")
        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setRange(0.0, 120.0)
        self.fade_spin.setSingleStep(0.1)
        self.fade_spin.setSuffix(" s")
        pform.addWidget(self.preset_combo)
        grid = QHBoxLayout()
        for text, spin in (("Strength", self.strength_spin), ("Cycle", self.cycle_spin),
                           ("Fade", self.fade_spin)):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell.addWidget(_label(text, "fieldLabel"))
            cell.addWidget(spin)
            grid.addLayout(cell)
        pform.addLayout(grid)
        self.forms.addWidget(preset_form)  # 1
        curve_form = QWidget()
        cform = QVBoxLayout(curve_form)
        cform.setContentsMargins(0, 0, 0, 0)
        cform.setSpacing(6)
        crow = QHBoxLayout()
        self.axis_combo = QComboBox()
        for axis in AXES:
            self.axis_combo.addItem(AXIS_LABELS[axis], axis)
        self.interp_combo = QComboBox()
        for name in INTERPOLATIONS:
            self.interp_combo.addItem(name.capitalize(), name)
        crow.addWidget(self.axis_combo, 1)
        crow.addWidget(self.interp_combo, 1)
        cform.addLayout(crow)
        self.key_table = QTableWidget(0, 2)
        self.key_table.setHorizontalHeaderLabels(["Frame", "Per-frame move"])
        self.key_table.horizontalHeader().setStretchLastSection(True)
        self.key_table.verticalHeader().setVisible(False)
        self.key_table.setMinimumHeight(96)
        self.key_table.setMaximumHeight(140)
        self.key_table.setAccessibleName("Curve keyframes")
        cform.addWidget(self.key_table)
        krow = QHBoxLayout()
        self.add_key_button = QPushButton("Add key")
        self.remove_key_button = QPushButton("Remove key")
        krow.addWidget(self.add_key_button)
        krow.addWidget(self.remove_key_button)
        cform.addLayout(krow)
        self.forms.addWidget(curve_form)  # 2
        self.audio_form = AudioLayerForm()
        self.forms.addWidget(self.audio_form)  # 3
        ebox.addWidget(self.forms)
        self.kept_note = _label("", "hint", wrap=True)
        ebox.addWidget(self.kept_note)
        box.addWidget(self.editor)

        # -- preview chart
        self.envelope = EnvelopeView()
        self.envelope.setVisible(False)
        box.addWidget(self.envelope)
        self.chart = MotionChart()
        box.addWidget(self.chart)
        legend = QHBoxLayout()
        legend.setSpacing(4)
        self.axis_boxes: dict[str, QCheckBox] = {}
        for axis in AXES:
            check = QCheckBox(AXIS_LABELS[axis].split(" ")[0] + " " + axis[-1].upper())
            check.setChecked(True)
            check.setToolTip(AXIS_LABELS[axis])
            check.setStyleSheet(f"QCheckBox {{ color: {AXIS_COLORS[axis]}; font-size: 11px; }}")
            check.toggled.connect(self._axes_toggled)
            legend.addWidget(check)
            self.axis_boxes[axis] = check
        box.addLayout(legend)
        self.limit_note = _label("", "hint", wrap=True)
        box.addWidget(self.limit_note)

        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.apply_button = QPushButton("Apply to camera")
        self.apply_button.setObjectName("primary")
        self.revert_button = QPushButton("Revert")
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.revert_button)
        buttons.addStretch(1)
        buttons.addWidget(self.apply_button)
        box.addLayout(buttons)
        box.addWidget(_label("Preview and Apply are computed by the backend. Apply writes the six camera "
                             "tracks; it never changes prompts or other settings.", "hint", wrap=True))

        self.layer_list.currentRowChanged.connect(self._row_changed)
        self.layer_list.itemChanged.connect(self._item_toggled)
        self.add_preset_button.clicked.connect(self._add_preset)
        self.add_curve_button.clicked.connect(self._add_curve)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.remove_button.clicked.connect(self._remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.blend_combo.activated.connect(lambda _i: self._edit("blend", self.blend_combo.currentData()))
        self.start_spin.valueChanged.connect(self._range_changed)
        self.end_spin.valueChanged.connect(self._range_changed)
        self.preset_combo.activated.connect(lambda _i: self._edit("preset", self.preset_combo.currentData()))
        self.strength_spin.valueChanged.connect(lambda v: self._edit("strength", v))
        self.cycle_spin.valueChanged.connect(lambda v: self._edit("cycle_seconds", v))
        self.fade_spin.valueChanged.connect(lambda v: self._edit("fade_seconds", v))
        self.axis_combo.activated.connect(lambda _i: self._edit("axis", self.axis_combo.currentData()))
        self.interp_combo.activated.connect(
            lambda _i: self._edit("interpolation", self.interp_combo.currentData()))
        self.audio_form.edited.connect(self._audio_edited)
        self.key_table.itemChanged.connect(self._key_edited)
        self.add_key_button.clicked.connect(self._add_key)
        self.remove_key_button.clicked.connect(self._remove_key)
        self.preview_button.clicked.connect(self._preview)
        self.apply_button.clicked.connect(self._apply)
        self.revert_button.clicked.connect(self._revert)

    # -- public -------------------------------------------------------------------------

    @property
    def dirty(self) -> bool:
        return self._layers != self._saved

    @property
    def layers(self) -> list[dict]:
        return deepcopy(self._layers)

    def set_project(self, project_id: str | None) -> None:
        self.clear()
        self._project_id = project_id
        if self._audio_service is not None:
            self._audio_service.set_project(project_id)
        if project_id:
            self._service.load(project_id)
        self._update()

    def set_playhead(self, frame: int) -> None:
        self._playhead = frame
        self.chart.set_frame(frame)
        self.envelope.set_frame(frame)
        if self.audio is not None:
            self.audio.set_playhead(frame)

    def stop_audition(self) -> None:
        if self.audio is not None:
            self.audio.stop_audition()

    def clear(self) -> None:
        self._state = None
        self._saved, self._layers = [], []
        self._error = ""
        self._analysis = None
        self._recovering.clear()
        self._pulses, self._pulses_stale = {}, True
        self._soundtrack_text = ""
        if self.audio is not None:
            self.audio.clear()
            self.soundtrack_note.setText("")
        self.chart.clear("Press Preview to see the camera motion")
        self.limit_note.setText("")
        self._refill()
        self._update()

    # -- service callbacks --------------------------------------------------------------

    def _loaded(self, state: MotionState, presets) -> None:
        self._state = state
        self._presets = tuple(presets) or PRESETS
        self._saved = [deepcopy(x) for x in state.layers]
        self._layers = [deepcopy(x) for x in state.layers]
        self._error = ""
        self._loading = True
        self.preset_combo.clear()
        for name in self._presets:
            self.preset_combo.addItem(preset_label(name), name)
        self._loading = False
        self.chart.clear("Press Preview to see the camera motion")
        self.limit_note.setText("")
        if self.audio is not None:
            self.audio.configure(self._project_id, state.frames, state.fps, state.usable)
        self._refill()
        self._update()

    def _previewed(self, preview: MotionPreview) -> None:
        self._error = ""
        self._pulses = {str(x.get("id")): list(x.get("pulses") or []) for x in preview.layers
                        if x.get("type") == "audio"}
        self._pulses_stale = False
        self.chart.set_series(preview.series)
        notes = []
        if preview.limited:
            parts = ", ".join(f"{AXIS_LABELS[a]} ({n} frames)" for a, n in preview.limited.items())
            notes.append(f"Clipped to the safety limits on: {parts}.")
        if preview.camera_changed:
            notes.append("The camera tracks were edited by hand since the last Apply; this preview treats the "
                         "current tracks as the base.")
        self.limit_note.setText(" ".join(notes))
        self._update()

    def _applied(self, _project) -> None:
        self._error = ""
        if self._project_id:
            self.applied.emit(self._project_id)
            self._service.load(self._project_id)
        self._update()

    def _conflict(self, _message: str) -> None:
        answer = QMessageBox.question(
            self, "Camera tracks were edited",
            "The camera tracks have been changed by hand since Motion Lab last applied them.\n\n"
            "Apply anyway, using the current camera tracks as the base? Your hand edits become part of "
            "the base; the motion layers are added on top.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._service.apply(self.layers, rebase=True)
        else:
            self._error = "Apply cancelled; the camera tracks were not changed."
            self._update()

    def _failed(self, operation: str, code: str, message: str) -> None:
        self._error = message or code
        self._update()

    # -- list ---------------------------------------------------------------------------

    def _refill(self, select: int | None = None) -> None:
        self._loading = True
        self.layer_list.clear()
        for layer in self._layers:
            item = QListWidgetItem(self._text(layer))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.get("enabled", True) is True
                               else Qt.CheckState.Unchecked)
            if not editable(layer):
                item.setToolTip("Kept as stored. It can be switched off, moved or removed.")
            self.layer_list.addItem(item)
        if self._layers:
            row = select if select is not None and 0 <= select < len(self._layers) else 0
            self.layer_list.setCurrentRow(row)
        self._loading = False
        self._show_layer()
        self._update()

    @staticmethod
    def _text(layer: dict) -> str:
        return (f"{describe_layer(layer)}  ·  {layer.get('start_frame', 0)}–"
                f"{layer.get('end_frame', '?')}"
                + ("  ·  replace" if layer.get("blend") == "replace" else ""))

    def _row(self) -> int:
        return self.layer_list.currentRow()

    def _current(self) -> dict | None:
        row = self._row()
        return self._layers[row] if 0 <= row < len(self._layers) else None

    def _row_changed(self, _row: int) -> None:
        if not self._loading:
            self._show_layer()
            self._update()

    def _item_toggled(self, item: QListWidgetItem) -> None:
        if self._loading:
            return
        row = self.layer_list.row(item)
        if 0 <= row < len(self._layers):
            self._layers[row]["enabled"] = item.checkState() == Qt.CheckState.Checked
            self._changed()

    def _changed(self) -> None:
        self.chart.set_stale(self.chart.has_data)
        self._pulses_stale = True
        self._refresh_envelope()
        self._update()

    # -- add, copy, remove, move ----------------------------------------------------------

    def _frames(self) -> int:
        return self._state.frames if self._state else 0

    def _add(self, layer: dict) -> None:
        self._layers.append(layer)
        self._refill(select=len(self._layers) - 1)
        self._changed()

    def _add_preset(self) -> None:
        if len(self._layers) < MAX_LAYERS and self._frames():
            self._add(new_preset_layer(self._layers, self._frames(), self._presets[1]
                                       if len(self._presets) > 1 else self._presets[0]))

    def _add_curve(self) -> None:
        if len(self._layers) < MAX_LAYERS and self._frames():
            self._add(new_curve_layer(self._layers, self._frames()))

    def _duplicate(self) -> None:
        layer = self._current()
        if layer is not None and len(self._layers) < MAX_LAYERS:
            copy = deepcopy(layer)
            copy["id"] = unique_id(self._layers)
            self._layers.insert(self._row() + 1, copy)
            self._refill(select=self._row() + 1)
            self._changed()

    def _remove(self) -> None:
        row = self._row()
        if 0 <= row < len(self._layers):
            del self._layers[row]
            self._refill(select=min(row, len(self._layers) - 1))
            self._changed()

    def _move(self, step: int) -> None:
        row = self._row()
        target = row + step
        if 0 <= row < len(self._layers) and 0 <= target < len(self._layers):
            self._layers[row], self._layers[target] = self._layers[target], self._layers[row]
            self._refill(select=target)
            self._changed()

    # -- editing the selected layer -------------------------------------------------------

    def _show_layer(self) -> None:
        layer = self._current()
        self._loading = True
        try:
            self.editor.setVisible(layer is not None)
            if layer is None:
                self.envelope.setVisible(False)
                return
            kind = layer.get("type")
            is_editable = editable(layer)
            self.blend_combo.setVisible(is_editable)
            self.start_spin.setVisible(is_editable)
            self.end_spin.setVisible(is_editable)
            self.kept_note.setVisible(not is_editable)
            self.kept_note.setText(
                "" if is_editable else
                f"{describe_layer(layer)} is a {kind} layer. It is kept exactly as stored and applied with "
                "the others; editing it comes in a later step.")
            if not is_editable:
                self.forms.setCurrentIndex(0)
                self._refresh_envelope()
                return
            frames = self._frames()
            self.blend_combo.setCurrentIndex(max(0, self.blend_combo.findData(layer.get("blend", "add"))))
            self.start_spin.setRange(0, max(0, frames - 1))
            self.end_spin.setRange(1, max(1, frames))
            self.start_spin.setValue(int(layer.get("start_frame", 0)))
            self.end_spin.setValue(int(layer.get("end_frame", frames)))
            if kind == "audio":
                self.forms.setCurrentIndex(3)
                ready = self._analysis_for(layer) is not None
                self.audio_form.load(layer, self._state.fps if self._state else 0.0, ready)
                self.start_spin.setEnabled(ready)
                self.end_spin.setEnabled(ready)
                if not ready:
                    self._recover(layer)
            elif kind == "preset":
                self.start_spin.setEnabled(True)
                self.end_spin.setEnabled(True)
                self.forms.setCurrentIndex(1)
                index = self.preset_combo.findData(layer.get("preset"))
                self.preset_combo.setCurrentIndex(max(0, index))
                self.strength_spin.setValue(float(layer.get("strength", 0.5)))
                self.cycle_spin.setValue(float(layer.get("cycle_seconds", 8.0)))
                self.fade_spin.setValue(float(layer.get("fade_seconds", 0.5)))
            else:
                self.start_spin.setEnabled(True)
                self.end_spin.setEnabled(True)
                self.forms.setCurrentIndex(2)
                self.axis_combo.setCurrentIndex(max(0, self.axis_combo.findData(layer.get("axis"))))
                self.interp_combo.setCurrentIndex(
                    max(0, self.interp_combo.findData(layer.get("interpolation", "linear"))))
                self._fill_keys(layer)
            self._refresh_envelope()
        finally:
            self._loading = False

    def _fill_keys(self, layer: dict) -> None:
        keys = layer.get("keys") or []
        self.key_table.blockSignals(True)
        self.key_table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            self.key_table.setItem(row, 0, QTableWidgetItem(str(key.get("frame"))))
            self.key_table.setItem(row, 1, QTableWidgetItem(f"{key.get('value'):g}"))
        self.key_table.blockSignals(False)

    def _edit(self, field: str, value) -> None:
        layer = self._current()
        if self._loading or layer is None:
            return
        layer[field] = value
        self._refresh_row_text()
        self._changed()

    def _range_changed(self) -> None:
        layer = self._current()
        if self._loading or layer is None:
            return
        start, end = self.start_spin.value(), self.end_spin.value()
        if end <= start:
            end = start + 1
            self._loading = True
            self.end_spin.setValue(end)
            self._loading = False
        before = layer["start_frame"], layer["end_frame"]
        layer["start_frame"], layer["end_frame"] = start, end
        if layer.get("type") == "audio" and not self._refit(layer):
            layer["start_frame"], layer["end_frame"] = before
            self._show_layer()
            return
        self._refresh_row_text()
        self._changed()

    def _refresh_row_text(self) -> None:
        layer, item = self._current(), self.layer_list.currentItem()
        if layer is not None and item is not None:
            self._loading = True
            item.setText(self._text(layer))
            self._loading = False

    def _key_edited(self, _item) -> None:
        layer = self._current()
        if self._loading or layer is None or layer.get("type") != "keyframes":
            return
        keys = []
        try:
            for row in range(self.key_table.rowCount()):
                keys.append({"frame": int(self.key_table.item(row, 0).text()),
                             "value": float(self.key_table.item(row, 1).text())})
        except (ValueError, AttributeError):
            self._error = "Keyframes need a whole frame number and a number for the move."
            self._fill_keys(layer)
            self._update()
            return
        self._error = ""
        layer["keys"] = sorted(keys, key=lambda k: k["frame"])
        self._fill_keys(layer)
        self._changed()

    def _add_key(self) -> None:
        layer = self._current()
        if layer is None or layer.get("type") != "keyframes" or len(layer["keys"]) >= MAX_KEYS:
            return
        taken = {k["frame"] for k in layer["keys"]}
        frame = next((f for f in range(max(1, int(layer.get("start_frame", 0))),
                                       int(layer.get("end_frame", 1)))
                      if f not in taken), None)
        if frame is None:
            self._error = "Every frame in this layer already has a keyframe."
            self._update()
            return
        layer["keys"] = sorted(layer["keys"] + [{"frame": frame, "value": 0.0}],
                               key=lambda k: k["frame"])
        self._fill_keys(layer)
        self._changed()

    def _remove_key(self) -> None:
        layer, row = self._current(), self.key_table.currentRow()
        if layer is None or layer.get("type") != "keyframes" or not 0 <= row < len(layer["keys"]):
            return
        if len(layer["keys"]) <= 1:
            self._error = "A curve needs at least one keyframe."
            self._update()
            return
        del layer["keys"][row]
        self._fill_keys(layer)
        self._changed()

    # -- audio layers (S5.2a) ---------------------------------------------------------------

    def _analysis_for(self, layer: dict) -> AudioAnalysis | None:
        if self._audio_service is None:
            return None
        analysis = self._audio_service.analysis(str(layer.get("sha256", "")))
        if analysis is None and self._analysis is not None and self._analysis.sha256 == layer.get("sha256"):
            analysis = self._analysis
        return analysis

    def _recover(self, layer: dict) -> None:
        """Ask the backend for this layer's stored audio so its band and range can be edited."""
        sha = str(layer.get("sha256", ""))
        if sha and sha not in self._recovering and self._audio_service is not None:
            self._recovering.add(sha)
            self._audio_service.recover(sha)

    def _refit(self, layer: dict) -> bool:
        """Re-slice the envelope after a band or range change; False when it cannot be done."""
        analysis = self._analysis_for(layer)
        if analysis is None:
            self._error = "This layer's audio is not loaded yet."
            self._update()
            return False
        try:
            refit_envelope(layer, analysis)
        except ValueError as exc:
            self._error = str(exc)
            self._update()
            return False
        return True

    def _add_audio(self, name: str, band: str, axis: str, distance: float, detection: str) -> None:
        analysis = self._analysis
        if analysis is None or len(self._layers) >= MAX_LAYERS or not self._frames():
            self._error = "Load an audio file first."
            self._update()
            return
        try:
            layer = new_audio_layer(self._layers, analysis, self._frames(), name=name, band=band,
                                    axis=axis, distance=distance, detection=detection)
        except ValueError as exc:
            self._error = str(exc)
            self._update()
            return
        self._add(layer)

    def _audio_edited(self, field: str, value) -> None:
        layer = self._current()
        if layer is None or layer.get("type") != "audio":
            return
        layer[field] = value
        if field == "band" and not self._refit(layer):
            return
        self._refresh_row_text()
        self._changed()

    def _analysis_ready(self, analysis: AudioAnalysis) -> None:
        self._analysis = analysis
        self._recovering.discard(analysis.sha256)
        self._error = ""
        layer = self._current()
        if layer is not None and layer.get("type") == "audio" and layer.get("sha256") == analysis.sha256:
            self._show_layer()
        self._update()

    def _audio_failed(self, operation: str, code: str, message: str) -> None:
        self._recovering.clear()
        self._error = message or code
        self._update()

    def _soundtrack_known(self, soundtrack) -> None:
        if soundtrack is None:
            self._soundtrack_text = ("No soundtrack is attached to this project, so exported videos will have no "
                                     "sound. Attach one in Library → project → Media.")
        else:
            self._soundtrack_text = (f"Final video soundtrack: {soundtrack.filename}"
                                     + (f" (offset {soundtrack.offset_seconds:g} s)"
                                        if soundtrack.offset_seconds else "") + ".")
        self._update()

    def _refresh_envelope(self) -> None:
        layer = self._current()
        audio = layer is not None and layer.get("type") == "audio"
        self.envelope.setVisible(audio)
        if audio:
            self.envelope.set_layer(layer, self._frames(), self._pulses.get(str(layer.get("id"))),
                                    self._pulses_stale)
            self.envelope.set_frame(self._playhead)

    # -- preview, apply, revert -----------------------------------------------------------

    def _axes_toggled(self) -> None:
        self.chart.set_shown(a for a, box in self.axis_boxes.items() if box.isChecked())

    def _preview(self) -> None:
        self._error = ""
        self._service.preview(self.layers)
        self._update()

    def _apply(self) -> None:
        self._error = ""
        self._service.apply(self.layers)
        self._update()

    def _revert(self) -> None:
        self._layers = [deepcopy(x) for x in self._saved]
        self._error = ""
        self.chart.clear("Press Preview to see the camera motion")
        self.limit_note.setText("")
        self._pulses_stale = True
        self._refill()

    # -- state ----------------------------------------------------------------------------

    def _update(self) -> None:
        state, busy = self._state, self._service.busy
        usable = state is not None and state.usable and self._service.available
        if self._project_id is None:
            message = "Choose a project to compose camera motion."
        elif state is None:
            message = "Loading…" if self._service.available else "Connect to a backend to use Motion Lab."
        elif state.mode != "3d":
            message = ("Motion Lab drives the six 3D camera axes. This project is in 2D mode; switch it to 3D "
                       "to use Motion Lab.")
        else:
            message = (f"{state.frames} frames at {state.fps:g} fps. Layers are applied top to bottom."
                       + ("  Unsaved changes." if self.dirty else ""))
        self.status.setText(self._error or message)
        self.status.setProperty("state", "bad" if self._error else "")
        has_layer = usable and self._current() is not None
        room = usable and len(self._layers) < MAX_LAYERS
        for button in (self.add_preset_button, self.add_curve_button):
            button.setEnabled(bool(room and not busy))
        self.add_audio_button.setEnabled(bool(room and not busy and self._analysis is not None))
        self.add_audio_button.setToolTip("" if self._analysis is not None else "Load an audio file first")
        if self.audio is not None:
            has_audio = self._analysis is not None or any(x.get("type") == "audio" for x in self._layers)
            self.soundtrack_note.setText(self._soundtrack_text if has_audio else "")
            self.soundtrack_note.setVisible(bool(self.soundtrack_note.text()))
        self.duplicate_button.setEnabled(bool(has_layer and room and not busy))
        self.remove_button.setEnabled(bool(has_layer and not busy))
        row = self._row()
        self.up_button.setEnabled(bool(has_layer and row > 0 and not busy))
        self.down_button.setEnabled(bool(has_layer and 0 <= row < len(self._layers) - 1 and not busy))
        self.layer_list.setEnabled(bool(usable))
        self.editor.setEnabled(bool(usable and not busy))
        self.preview_button.setEnabled(bool(usable and self._layers and not busy))
        self.apply_button.setEnabled(bool(usable and self._layers and not busy))
        self.revert_button.setEnabled(bool(usable and self.dirty and not busy))
