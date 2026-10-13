"""Editor page (S4.1): read-only animation timeline with backend-resolved values."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
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
from morphorum_studio.backend.timeline import Resolved, Series, Timeline
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
        right.addWidget(self.keys, 1)
        lower.addLayout(right, 1)
        box.addLayout(lower, 2)
        box.addWidget(_label("Read-only view: values and curves are evaluated by the backend. "
                             "Editing arrives in the next step.", "hint", wrap=True))

        self.project.activated.connect(self._project_chosen)
        self.reload.clicked.connect(self._reload)
        self.frame_spin.valueChanged.connect(self._spin_changed)
        self.view.frame_changed.connect(self._view_frame)
        self.view.track_selected.connect(self._track_selected)

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
        self._error = f"{operation.capitalize()} failed: {message}"
        self._update()
