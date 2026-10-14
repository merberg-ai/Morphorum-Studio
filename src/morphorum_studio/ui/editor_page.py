"""Editor page (S4.1): read-only animation timeline with backend-resolved values."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
from morphorum_studio.backend.validation import Validation
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
from morphorum_studio.ui.motion_panel import MotionPanel
from morphorum_studio.ui.player_panel import PlayerPanel
from morphorum_studio.ui.projects_service import ProjectsService
from morphorum_studio.ui.render_card import RenderCard
from morphorum_studio.ui.timeline_service import TimelineService
from morphorum_studio.ui.timeline_view import CurveView, TimelineView

SCRUB_DEBOUNCE_MS = 120
FRAME_CACHE = 32


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class EditorPage(QWidget):
    open_connections = Signal()

    def __init__(self, session: BackendSession, projects: ProjectsService,
                 service: TimelineService, render_service=None, video_service=None,
                 motion_service=None) -> None:
        super().__init__()
        self._render_service = render_service
        self._video_service = video_service
        self._motion_service = motion_service
        self._player_job = None  # newest render of this project that has rendered frames
        self._frames: dict[tuple[str, int], bytes] = {}
        self._frame_failed: set[tuple[str, int]] = set()
        self._frame_inflight: tuple[str, int] | None = None
        self._pending_open: str | None = None
        self.setObjectName("pageSurface")
        self._session = session
        self._projects = projects
        self._service = service
        self._active = False
        self._timeline: Timeline | None = None
        self._track_id: str | None = None
        self._error = ""
        self._build()
        self._reset_preview()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SCRUB_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._settled)
        projects.listed.connect(self._listed)
        service.loaded.connect(self._loaded)
        service.series_ready.connect(self._series_ready)
        service.resolved.connect(self._resolved)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(self._cleared)
        service.edited.connect(self._edited)
        service.validated.connect(self._validated)
        service.history_changed.connect(self._update_edit_controls)
        session.changed.connect(self._update)
        if render_service is not None:
            render_service.list_ready.connect(self._renders_listed)
            render_service.job_updated.connect(self._render_job_updated)
            render_service.frame_ready.connect(self._frame_arrived)
            render_service.cleared.connect(self._renders_cleared)
        self._update()

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(38, 34, 38, 24)
        box.setSpacing(10)
        box.addWidget(_label("TIMELINE / STUDIO", "sectionCaption"))
        box.addWidget(_label("Timeline", "pageHeading"))
        self.status = _label("", "pageDescription", wrap=True)
        box.addWidget(self.status)

        # Everything below the heading scrolls when the window is too small, instead of overlapping.
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setMinimumSize(900, 620)
        page_scroll.setWidget(body)
        box.addWidget(page_scroll, 1)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

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
        outer.addLayout(top)

        main = QHBoxLayout()
        main.setSpacing(14)
        outer.addLayout(main, 1)

        # -- centre: player over the tracks dock
        centre = QVBoxLayout()
        centre.setSpacing(10)
        self.player = PlayerPanel()
        self.player.setMinimumHeight(250)
        centre.addWidget(self.player, 3)

        self.view = TimelineView()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.view)
        scroll.setMinimumHeight(170)
        centre.addWidget(scroll, 2)

        glance = QHBoxLayout()
        glance.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(_label("At this frame", "fieldLabel"))
        self.values = QTableWidget(0, 2)
        self.values.setHorizontalHeaderLabels(["Track", "Value"])
        self.values.verticalHeader().setVisible(False)
        self.values.horizontalHeader().setStretchLastSection(True)
        self.values.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.values.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.values.setMinimumHeight(110)
        left.addWidget(self.values, 1)
        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setMaximumHeight(90)
        left.addWidget(self.prompt_view)
        glance.addLayout(left, 1)
        checks = QVBoxLayout()
        self.check_label = _label("", "fieldLabel", wrap=True)
        checks.addWidget(self.check_label)
        self.issues = QListWidget()
        self.issues.setMinimumHeight(110)
        checks.addWidget(self.issues, 1)
        glance.addLayout(checks, 1)
        centre.addLayout(glance, 2)
        centre_widget = QWidget()
        centre_widget.setLayout(centre)
        main.addWidget(centre_widget, 1)

        # -- right: keyframe inspector, then the render card
        side = QScrollArea()
        side.setObjectName("connectionsScroll")
        side.setWidgetResizable(True)
        side.setFrameShape(QFrame.Shape.NoFrame)
        side.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.setFixedWidth(392)
        side_content = QWidget()
        side_content.setObjectName("connectionsContent")
        side.setWidget(side_content)
        sbox = QVBoxLayout(side_content)
        sbox.setContentsMargins(0, 0, 8, 0)
        sbox.setSpacing(12)

        inspector = QFrame()
        inspector.setObjectName("card")
        right = QVBoxLayout(inspector)
        right.setContentsMargins(16, 14, 16, 16)
        right.setSpacing(8)
        right.addWidget(_label("Keyframe inspector", "cardTitle"))
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
        self.keys.setMinimumHeight(120)
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
        self.reload.setToolTip("Read the timeline from the backend again (F5)")
        self.frame_spin.setToolTip("Playhead frame. Left/Right arrows step by one, Shift by ten.")
        self.set_button.setToolTip("Add a keyframe at the playhead, or replace the one that is there")
        self.update_button.setToolTip("Change the value of the selected keyframe")
        self.delete_button.setToolTip("Remove the selected keyframe")
        self.move_button.setToolTip("Move the selected keyframe to the playhead frame")
        self.interp.setToolTip("How values blend from the selected keyframe to the next one")
        self.undo_button.setToolTip("Undo the last edit (Ctrl+Z)")
        self.redo_button.setToolTip("Redo the edit you undid (Ctrl+Shift+Z)")
        for widget in (self.set_button, self.update_button, self.delete_button, self.move_button,
                       self.undo_button, self.redo_button):
            widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        first_row = QHBoxLayout()
        first_row.setSpacing(6)
        first_row.addWidget(self.set_button)
        first_row.addWidget(self.update_button)
        first_row.addStretch(1)
        right.addLayout(first_row)
        for widget in (self.move_button, self.delete_button):
            edit_row.addWidget(widget)
        edit_row.addStretch(1)
        right.addLayout(edit_row)
        history_row = QHBoxLayout()
        history_row.setSpacing(6)
        history_row.addWidget(QLabel("Interpolation"))
        history_row.addWidget(self.interp, 1)
        right.addLayout(history_row)
        undo_row = QHBoxLayout()
        undo_row.setSpacing(6)
        undo_row.addWidget(self.undo_button)
        undo_row.addWidget(self.redo_button)
        undo_row.addStretch(1)
        right.addLayout(undo_row)
        self.edit_status = _label("", "hint", wrap=True)
        right.addWidget(self.edit_status)
        right.addWidget(_label("Values and curves are evaluated by the backend. Each edit is saved to the "
                               "backend immediately and can be undone here.", "hint", wrap=True))
        self.inspector = inspector
        self.motion_panel = None
        self.side_tabs: dict[str, QPushButton] = {}
        if self._motion_service is not None:
            tabs = QHBoxLayout()
            tabs.setSpacing(8)
            for key, text in (("keyframes", "Keyframes"), ("motion", "Motion")):
                button = QPushButton(text)
                button.setObjectName("segButton")
                button.setCheckable(True)
                button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                button.clicked.connect(lambda _c=False, k=key: self.show_side(k))
                tabs.addWidget(button)
                self.side_tabs[key] = button
            tabs.addStretch(1)
            sbox.addLayout(tabs)
            self.motion_panel = MotionPanel(self._motion_service)
            self.motion_panel.applied.connect(lambda _pid: self._reload())
            self.motion_panel.setVisible(False)
        sbox.addWidget(inspector)
        if self.motion_panel is not None:
            sbox.addWidget(self.motion_panel)
            self.side_tabs["keyframes"].setChecked(True)

        self.render_card = None
        if self._render_service is not None:
            self.render_card = RenderCard(self._render_service, self._video_service, compact=True)
            sbox.addWidget(self.render_card)
        sbox.addStretch(1)
        main.addWidget(side)

        self.project.activated.connect(self._project_chosen)
        self.reload.clicked.connect(self._reload)
        self.frame_spin.valueChanged.connect(self._spin_changed)
        self.view.frame_changed.connect(self._view_frame)
        self.view.track_selected.connect(self._track_selected)
        self.player.frame_requested.connect(self._player_frame)
        self.keys.currentCellChanged.connect(lambda *_: self._key_selected())
        self.issues.itemActivated.connect(self._issue_chosen)
        self.issues.itemClicked.connect(self._issue_chosen)
        self.set_button.clicked.connect(self._set_at_playhead)
        self.update_button.clicked.connect(self._update_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.move_button.clicked.connect(self._move_selected)
        self.interp.activated.connect(self._interp_chosen)
        self.undo_button.clicked.connect(self._undo)
        self.redo_button.clicked.connect(self._redo)

    def show_side(self, key: str) -> None:
        """Switch the right column between the keyframe inspector and the Motion Lab panel."""
        if self.motion_panel is None:
            return
        motion = key == "motion"
        self.inspector.setVisible(not motion)
        self.motion_panel.setVisible(motion)
        for name, button in self.side_tabs.items():
            button.setChecked((name == "motion") == motion)

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
        wanted, self._pending_open = self._pending_open, None
        if wanted and self.project.findData(wanted) >= 0:
            self.project.setCurrentIndex(self.project.findData(wanted))
            self._project_chosen(self.project.currentIndex())

    def open_project(self, project_id: str) -> None:
        """Show ``project_id`` (used by Library and Home); waits for the project list if needed."""
        index = self.project.findData(project_id)
        if index >= 0:
            self.project.setCurrentIndex(index)
            self._project_chosen(index)
        else:
            self._pending_open = project_id
            if self._service.available:
                self._projects.refresh()

    def _project_chosen(self, _index: int) -> None:
        project_id = self.project.currentData()
        self._error = ""
        self._reset_preview()
        if self.render_card is not None:
            self.render_card.set_project(project_id)
        if self.motion_panel is not None:
            self.motion_panel.set_project(project_id or None)
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
        self.issues.clear()
        self.check_label.setText("")
        self.curve.show_message("Select a numeric track")
        self.track_title.setText("Select a track")
        self.frame_spin.blockSignals(True)
        self.frame_spin.setRange(0, 0)
        self.frame_spin.setValue(0)
        self.frame_spin.blockSignals(False)
        self.time_label.setText("")
        self.player.set_range(0, 0.0)
        self._reset_preview()
        self._update()

    # -- timeline -----------------------------------------------------------------------

    def _loaded(self, timeline: Timeline) -> None:
        self._error = ""
        self._timeline = timeline
        self._track_id = None
        self.view.set_timeline(timeline)
        self.player.set_range(timeline.max_frames, timeline.fps)
        if self.render_card is not None:
            self.render_card.set_playhead(0)
        self._request_preview(0)
        self.frame_spin.blockSignals(True)
        self.frame_spin.setRange(0, timeline.max_frames - 1)
        self.frame_spin.setValue(0)
        self.frame_spin.blockSignals(False)
        self.keys.setRowCount(0)
        self.curve.show_message("Select a numeric track")
        self.track_title.setText("Select a track")
        self._show_frame_label(0)
        self._service.request_frame(0)
        self.check_label.setText("Checking schedules…")
        self.issues.clear()
        self._service.validate()
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

    def _player_frame(self, frame: int) -> None:
        """Transport button or playback moved the playhead."""
        self.view.set_frame(frame)
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(frame)
        self.frame_spin.blockSignals(False)
        self._frame_moved(frame)
        self._request_preview(frame)

    def _settled(self) -> None:
        self._service.request_frame(self.view.frame)
        self._request_preview(self.view.frame)

    def _frame_moved(self, frame: int) -> None:
        self.player.set_frame(frame)
        if self.render_card is not None:
            self.render_card.set_playhead(frame)
        if self.motion_panel is not None:
            self.motion_panel.set_playhead(frame)
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


    # -- rendered-frame preview (layout step 4) ---------------------------------------------

    def _reset_preview(self) -> None:
        self._player_job = None
        self._frames.clear()
        self._frame_failed = set()
        self._frame_inflight = None
        if self._render_service is None:
            self.player.show_message("Rendered frames appear here once the backend can render.")
        else:
            self.player.show_message("Open a project to preview its rendered frames")

    def _renders_listed(self, project_id: str, jobs) -> None:
        if project_id != self.project.currentData():
            return
        framed = [j for j in jobs if j.latest_frame is not None]
        self._player_job = max(framed, key=lambda j: j.created_at or "") if framed else None
        self._request_preview(self.view.frame)

    def _render_job_updated(self, job) -> None:
        if job.project_id != self.project.currentData() or job.latest_frame is None:
            return
        current = self._player_job
        if current is None or job.id == current.id or (job.created_at or "") >= (current.created_at or ""):
            self._player_job = job
            self._request_preview(self.view.frame)

    def _renders_cleared(self) -> None:
        self._reset_preview()

    def _request_preview(self, frame: int) -> None:
        if self._timeline is None or self._render_service is None:
            return
        job, project_id = self._player_job, self.project.currentData()
        if job is None or project_id is None:
            self.player.show_message("No rendered frames yet",
                                     "Render the project from the panel on the right to preview it here.")
            return
        latest = job.latest_frame or 0
        if frame > latest:
            self.player.show_message(f"Frame {frame + 1} has not been rendered yet",
                                     f"The latest render has frames 1 to {latest + 1}.")
            return
        key = (job.id, frame)
        data = self._frames.get(key)
        if data is not None:
            self.player.show_png(data, f"Render {job.id} · frame {frame + 1}")
        elif key in self._frame_failed:
            self.player.show_message("This frame is not available")
        elif self._frame_inflight is None:
            self._frame_inflight = key
            self.player.caption.setText("Loading frame…")
            self._render_service.fetch_frame(project_id, job.id, frame)

    def _frame_arrived(self, render_id: str, frame: int, data) -> None:
        job = self._player_job
        if job is None or render_id != job.id:
            return
        key = (render_id, frame)
        if data:
            while len(self._frames) >= FRAME_CACHE:
                del self._frames[next(iter(self._frames))]
            self._frames[key] = data
        elif key == self._frame_inflight:
            self._frame_failed.add(key)
        if key == self._frame_inflight:
            self._frame_inflight = None
        self._request_preview(self.view.frame)

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
        if operation == "validate":
            self.check_label.setText(f"Schedules could not be checked: {message}")
            return
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
        self._service.validate()
        self._update()

    # -- validation (S4.3) --------------------------------------------------------------

    def _validated(self, result: Validation | None) -> None:
        self.issues.clear()
        if result is None:
            self.check_label.setText("Schedules could not be checked.")
            return
        errors, warnings = len(result.errors), len(result.warnings)
        if result.valid and not warnings:
            self.check_label.setText("Schedules are valid.")
        elif result.valid:
            self.check_label.setText(f"Schedules are valid with {warnings} warning(s).")
        else:
            self.check_label.setText(f"{errors} schedule error(s), {warnings} warning(s): "
                                     "renders are blocked until errors are fixed.")
        for issue in result.issues:
            item = QListWidgetItem(f"{'⚠' if issue.severity == 'warning' else '✖'} "
                                   f"{issue.field or 'project'}: {issue.message}")
            item.setData(Qt.ItemDataRole.UserRole, issue.track_id)
            item.setToolTip(issue.message)
            self.issues.addItem(item)

    def _issue_chosen(self, item: QListWidgetItem) -> None:
        track_id = item.data(Qt.ItemDataRole.UserRole)
        if track_id and self._timeline and self._timeline.track(track_id):
            self.view.select(track_id)
            self._track_selected(track_id)
