"""Editor page (S4.1): read-only animation timeline with backend-resolved values."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.timeline import (
    EditError,
    Resolved,
    Series,
    Timeline,
    keyframe_at,
    plan_delete,
    plan_interpolation,
    plan_move,
    plan_set,
)
from morphorum_studio.ui.projects_service import ProjectsService
from morphorum_studio.ui.timeline_service import TimelineService
from morphorum_studio.ui.timeline_view import CurveView, TimelineView

SCRUB_DEBOUNCE_MS = 120


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class EditorPage(QWidget):
    open_connections = Signal()

    def __init__(self, session: BackendSession, projects: ProjectsService,
                 service: TimelineService) -> None:
        super().__init__()
        self.setObjectName("pageSurface")
        self._session = session
        self._projects = projects
        self._service = service
        self._active = False
        self._timeline: Timeline | None = None
        self._track_id: str | None = None
        self._error = ""
        self._build()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SCRUB_DEBOUNCE_MS)
        self._debounce.timeout.connect(lambda: self._service.request_frame(self.view.frame))
        projects.listed.connect(self._listed)
        service.loaded.connect(self._loaded)
        service.series_ready.connect(self._series_ready)
        service.resolved.connect(self._resolved)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(self._cleared)
        service.edited.connect(self._edited)
        service.history_changed.connect(self._update_edit_controls)
        session.changed.connect(self._update)
        self._update()

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(38, 34, 38, 24)
        box.setSpacing(10)
        box.addWidget(_label("EDITOR / STUDIO", "sectionCaption"))
        box.addWidget(_label("Animation timeline", "pageHeading"))
        self.status = _label("", "pageDescription", wrap=True)
        box.addWidget(self.status)

        top = QHBoxLayout()
        self.project = QComboBox()
        self.project.setMinimumWidth(240)
        self.project.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.reload = QPushButton("Reload")
        self.reload.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(0, 0)
        self.time_label = QLabel("")
        self.time_label.setObjectName("hint")
        top.addWidget(QLabel("Project"))
        top.addWidget(self.project, 1)
        top.addWidget(self.reload)
        top.addSpacing(16)
        top.addWidget(QLabel("Frame"))
        top.addWidget(self.frame_spin)
        top.addWidget(self.time_label)
        top.addStretch(1)
        box.addLayout(top)

        self.view = TimelineView()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.view)
        scroll.setMinimumHeight(200)
        box.addWidget(scroll, 3)

        lower = QHBoxLayout()
        lower.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(_label("At this frame", "fieldLabel"))
        self.values = QTableWidget(0, 2)
        self.values.setHorizontalHeaderLabels(["Track", "Value"])
        self.values.verticalHeader().setVisible(False)
        self.values.horizontalHeader().setStretchLastSection(True)
        self.values.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.values.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        left.addWidget(self.values, 1)
        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setMaximumHeight(90)
        left.addWidget(self.prompt_view)
        lower.addLayout(left, 1)

        right = QVBoxLayout()
        self.track_title = _label("Select a track", "fieldLabel")
        right.addWidget(self.track_title)
        self.curve = CurveView()
        right.addWidget(self.curve)
        self.keys = QTableWidget(0, 2)
        self.keys.setHorizontalHeaderLabels(["Frame", "Value"])
        self.keys.verticalHeader().setVisible(False)
        self.keys.horizontalHeader().setStretchLastSection(True)
        self.keys.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.keys.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.keys.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        right.addWidget(self.keys, 1)
        self.value_edit = QPlainTextEdit()
        self.value_edit.setPlaceholderText("Keyframe value (number, expression such as 1+0.5*sin(t), or prompt text)")
        self.value_edit.setMaximumHeight(64)
        right.addWidget(self.value_edit)
        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        self.set_button = QPushButton("Set at playhead")
        self.update_button = QPushButton("Update selected")
        self.delete_button = QPushButton("Delete")
        self.move_button = QPushButton("Move to playhead")
        self.interp = QComboBox()
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        for widget in (self.set_button, self.update_button, self.delete_button, self.move_button,
                       self.interp, self.undo_button, self.redo_button):
            if isinstance(widget, QPushButton):
                widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            edit_row.addWidget(widget)
        edit_row.addStretch(1)
        right.addLayout(edit_row)
        self.edit_status = _label("", "hint", wrap=True)
        right.addWidget(self.edit_status)
        lower.addLayout(right, 1)
        box.addLayout(lower, 2)
        box.addWidget(_label("Values and curves are evaluated by the backend. Each edit is saved to the "
                             "backend immediately and can be undone here.", "hint", wrap=True))

        self.project.activated.connect(self._project_chosen)
        self.reload.clicked.connect(self._reload)
        self.frame_spin.valueChanged.connect(self._spin_changed)
        self.view.frame_changed.connect(self._view_frame)
        self.view.track_selected.connect(self._track_selected)
        self.keys.currentCellChanged.connect(lambda *_: self._key_selected())
        self.set_button.clicked.connect(self._set_at_playhead)
        self.update_button.clicked.connect(self._update_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.move_button.clicked.connect(self._move_selected)
        self.interp.activated.connect(self._interp_chosen)
        self.undo_button.clicked.connect(self._undo)
        self.redo_button.clicked.connect(self._redo)

    # -- state --------------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and self._service.available:
            self._projects.refresh()

    def _update(self) -> None:
        if self._session.state == "offline":
            text = "Connect to a backend to open a project timeline."
        elif not self._session.feature("timeline"):
            text = "This backend does not provide the timeline API."
        elif self._service.busy:
            text = "Loading timeline…"
        elif self._error:
            text = self._error
        elif self._timeline:
            t = self._timeline
            text = f"{t.max_frames} frames at {t.fps:g} fps, {t.duration:.1f} s. Click or drag to scrub; ← → step (Shift ×10)."
        else:
            text = "Choose a project."
        self.status.setText(text)
        ready = self._service.available
        self.project.setEnabled(ready)
        self.reload.setEnabled(ready and self.project.currentData() is not None)
        self._update_edit_controls()

    def _listed(self, summaries) -> None:
        current = self.project.currentData()
        self.project.blockSignals(True)
        self.project.clear()
        self.project.addItem("Select a project…", None)
        for item in summaries:
            self.project.addItem(item.name or item.id, item.id)
        index = self.project.findData(current)
        self.project.setCurrentIndex(index if index >= 0 else 0)
        self.project.blockSignals(False)
        self._update()

    def _project_chosen(self, _index: int) -> None:
        project_id = self.project.currentData()
        self._error = ""
        if project_id:
            self._service.load(project_id)
        else:
            self._service.forget()
            self._cleared()
        self._update()

    def _reload(self) -> None:
        project_id = self.project.currentData()
        if project_id:
            self._error = ""
            self._service.load(project_id)
            self._update()

    def _cleared(self) -> None:
        self._timeline = None
        self._track_id = None
        self.view.set_timeline(None)
        self.values.setRowCount(0)
        self.keys.setRowCount(0)
        self.prompt_view.clear()
        self.curve.show_message("Select a numeric track")
        self.track_title.setText("Select a track")
        self.frame_spin.blockSignals(True)
        self.frame_spin.setRange(0, 0)
        self.frame_spin.setValue(0)
        self.frame_spin.blockSignals(False)
        self.time_label.setText("")
        self._update()

    # -- timeline -----------------------------------------------------------------------

    def _loaded(self, timeline: Timeline) -> None:
        self._error = ""
        self._timeline = timeline
        self._track_id = None
        self.view.set_timeline(timeline)
        self.frame_spin.blockSignals(True)
        self.frame_spin.setRange(0, timeline.max_frames - 1)
        self.frame_spin.setValue(0)
        self.frame_spin.blockSignals(False)
        self.keys.setRowCount(0)
        self.curve.show_message("Select a numeric track")
        self.track_title.setText("Select a track")
        self._show_frame_label(0)
        self._service.request_frame(0)
        self._update()

    def _show_frame_label(self, frame: int) -> None:
        if self._timeline:
            self.time_label.setText(f"{frame / self._timeline.fps:.2f} s")

    def _view_frame(self, frame: int) -> None:
        self._frame_moved(frame)
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(frame)
        self.frame_spin.blockSignals(False)

    def _spin_changed(self, frame: int) -> None:
        self.view.set_frame(frame)
        self._frame_moved(frame)

    def _frame_moved(self, frame: int) -> None:
        self.curve.set_frame(frame)
        self._show_frame_label(frame)
        self._update_edit_controls()
        self._debounce.start()

    def _resolved(self, resolved: Resolved) -> None:
        if resolved.frame != self.view.frame or self._timeline is None:
            return
        self._error = ""
        self._update()
        tracks = [t for t in self._timeline.tracks if t.id in resolved.values]
        self.values.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            unit = f" {track.unit}" if track.unit else ""
            self.values.setItem(row, 0, QTableWidgetItem(track.label))
            self.values.setItem(row, 1, QTableWidgetItem(f"{resolved.values[track.id]:.4g}{unit}"))
        lines = [f"Positive: {resolved.positive or '—'}", f"Negative: {resolved.negative or '—'}"]
        if resolved.seed is not None:
            lines.append(f"Seed: {resolved.seed}")
        self.prompt_view.setPlainText("\n".join(lines))

    # -- track selection ----------------------------------------------------------------

    def _track_selected(self, track_id: str) -> None:
        timeline = self._timeline
        track = timeline.track(track_id) if timeline else None
        if track is None:
            return
        self._track_id = track_id
        self._error = ""
        self.track_title.setText(f"{track.label} — {track.interpolation or 'n/a'} interpolation")
        self.keys.setRowCount(len(track.keyframes))
        for row, key in enumerate(track.keyframes):
            self.keys.setItem(row, 0, QTableWidgetItem(key.expression or str(key.frame)))
            self.keys.setItem(row, 1, QTableWidgetItem(key.value))
        self._show_interpolation()
        self._update_edit_controls()
        if track.kind == "numeric" and track.field:
            self.curve.show_message("Loading curve…")
            self._service.request_series(track_id)
        else:
            self.curve.show_message("Prompt tracks have no curve")

    def _series_ready(self, track_id: str, series: Series | None) -> None:
        if track_id != self._track_id or self._timeline is None:
            return
        track = self._timeline.track(track_id)
        if series is None or track is None:
            self.curve.show_message("The backend could not evaluate this curve")
            return
        self.curve.show_series(series, track.keyframes, self._timeline.max_frames)
        self.curve.set_frame(self.view.frame)

    def _failed(self, operation: str, code: str, message: str) -> None:
        if operation == "edit":
            self.edit_status.setText(f"Edit failed: {message}")
            self._update_edit_controls()
            return
        self._error = f"{operation.capitalize()} failed: {message}"
        self._update()

    # -- editing (S4.2) -----------------------------------------------------------------

    def _track(self):
        return self._timeline.track(self._track_id) if self._timeline and self._track_id else None

    def _selected_frame(self) -> int | None:
        track, row = self._track(), self.keys.currentRow()
        return track.keyframes[row].frame if track and 0 <= row < len(track.keyframes) else None

    def _update_edit_controls(self) -> None:
        track, can = self._track(), self._service.can_edit
        selected = self._selected_frame()
        self.value_edit.setEnabled(bool(track) and can)
        self.set_button.setEnabled(bool(track) and can)
        self.update_button.setEnabled(can and selected is not None)
        self.delete_button.setEnabled(can and selected is not None)
        self.move_button.setEnabled(can and selected is not None and selected != self.view.frame)
        self.interp.setEnabled(bool(track) and can and bool(track.modes if track else False))
        undo, redo = self._service.undo_label, self._service.redo_label
        self.undo_button.setEnabled(can and undo is not None)
        self.redo_button.setEnabled(can and redo is not None)
        self.undo_button.setToolTip(f"Undo: {undo}" if undo else "Nothing to undo")
        self.redo_button.setToolTip(f"Redo: {redo}" if redo else "Nothing to redo")

    def _key_selected(self) -> None:
        track, row = self._track(), self.keys.currentRow()
        if track and 0 <= row < len(track.keyframes):
            self.value_edit.setPlainText(track.keyframes[row].value)
        self._update_edit_controls()

    def _show_interpolation(self) -> None:
        track = self._track()
        self.interp.blockSignals(True)
        self.interp.clear()
        for mode in (track.modes if track else ()):
            self.interp.addItem(mode.capitalize(), mode)
        if track:
            self.interp.setCurrentIndex(max(0, self.interp.findData(track.interpolation)))
        self.interp.blockSignals(False)

    def _try(self, planner) -> None:
        self.edit_status.setText("")
        try:
            edit = planner()
        except EditError as exc:
            self.edit_status.setText(str(exc))
            return
        self._service.apply(edit)

    def _set_at_playhead(self) -> None:
        track, timeline = self._track(), self._timeline
        if track and timeline:
            self._try(lambda: plan_set(track, self.view.frame, self.value_edit.toPlainText(),
                                       timeline.max_frames))

    def _update_selected(self) -> None:
        track, timeline, frame = self._track(), self._timeline, self._selected_frame()
        if track and timeline and frame is not None:
            self._try(lambda: plan_set(track, frame, self.value_edit.toPlainText(), timeline.max_frames))

    def _delete_selected(self) -> None:
        track, timeline, frame = self._track(), self._timeline, self._selected_frame()
        if track and timeline and frame is not None:
            self._try(lambda: plan_delete(track, frame, timeline.max_frames))

    def _move_selected(self) -> None:
        track, timeline, frame = self._track(), self._timeline, self._selected_frame()
        if not (track and timeline and frame is not None):
            return
        target = self.view.frame
        overwrite = False
        if keyframe_at(track, target) is not None:
            answer = QMessageBox.question(
                self, "Replace keyframe?",
                f"There is already a keyframe at frame {target}. Replace it? (Undo restores it.)")
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self._try(lambda: plan_move(track, frame, target, timeline.max_frames, overwrite))

    def _interp_chosen(self, _index: int) -> None:
        track = self._track()
        if track:
            self._try(lambda: plan_interpolation(track, self.interp.currentData()))
            self._show_interpolation()  # snap back until the backend confirms

    def _undo(self) -> None:
        self.edit_status.setText(f"Undoing: {self._service.undo_label}")
        self._service.undo()

    def _redo(self) -> None:
        self.edit_status.setText(f"Redoing: {self._service.redo_label}")
        self._service.redo()

    def _edited(self, timeline: Timeline) -> None:
        """The backend confirmed and Studio reloaded: redraw from what it holds now."""
        self._timeline = timeline
        self.view.set_timeline_keep_frame(timeline)
        if self._track_id and timeline.track(self._track_id):
            self._track_selected(self._track_id)
        self.edit_status.setText("Saved.")
        self._service.request_frame(self.view.frame)
        self._update()
