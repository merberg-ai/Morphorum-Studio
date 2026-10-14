"""Queue: every image job and animation render the backend reports, in one list.

Shows only what the backend reports. Cancel and Resume appear only where the backend allows
them for that job; there is no reordering or priority because the backend has neither.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.queue_service import QueueEntry, QueueService, chip_for

FILTERS = (("all", "All"), ("active", "Running and waiting"), ("finished", "Finished"))
KIND_LABEL = {"render": "RENDER", "image": "IMAGE"}


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def summary_text(entries) -> str:
    running = sum(1 for e in entries if e.active and e.status != "queued")
    waiting = sum(1 for e in entries if e.status == "queued")
    finished = sum(1 for e in entries if not e.active)
    parts = []
    if running:
        parts.append(f"{running} running")
    if waiting:
        parts.append(f"{waiting} waiting")
    if finished:
        parts.append(f"{finished} finished")
    return " · ".join(parts) if parts else "Nothing in the queue"


def keep(entry: QueueEntry, mode: str) -> bool:
    return mode == "all" or (mode == "active") == entry.active


class QueueRow(QFrame):
    cancel_clicked = Signal(object)
    resume_clicked = Signal(object)
    open_clicked = Signal(object)

    def __init__(self, entry: QueueEntry) -> None:
        super().__init__()
        self.entry = entry
        self.setObjectName("queueRow")
        box = QHBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(14)
        kind = _label(KIND_LABEL.get(entry.kind, entry.kind.upper()), "sectionCaption")
        kind.setMinimumWidth(56)
        box.addWidget(kind)
        middle = QVBoxLayout()
        middle.setSpacing(3)
        self.title = _label(entry.title, "metricValue")
        self.title.setToolTip(entry.title)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.detail = _label(f"{entry.detail}  ·  {entry.text}", "hint")
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.detail.setToolTip(f"{entry.detail}\n{entry.text}")
        middle.addWidget(self.title)
        middle.addWidget(self.detail)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(max(0.0, min(1.0, entry.progress)) * 1000))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setVisible(entry.active and entry.status != "queued")
        middle.addWidget(self.bar)
        box.addLayout(middle, 1)
        label, state = chip_for(entry.status)
        self.chip = _label(label, "chip")
        self.chip.setProperty("state", state)
        box.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(entry.can_cancel)
        self.cancel_button.clicked.connect(lambda: self.cancel_clicked.emit(entry))
        self.resume_button = QPushButton("Resume")
        self.resume_button.setVisible(entry.can_resume)
        self.resume_button.clicked.connect(lambda: self.resume_clicked.emit(entry))
        self.open_button = QPushButton("Open in Timeline" if entry.kind == "render" else "Open in Lab")
        self.open_button.clicked.connect(lambda: self.open_clicked.emit(entry))
        for button in (self.cancel_button, self.resume_button, self.open_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            box.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.open_button.setEnabled(entry.kind == "image" or bool(entry.project_id))


class QueuePage(QFrame):
    open_connections = Signal()
    open_timeline = Signal(str)  # project id
    open_lab = Signal()

    def __init__(self, session: BackendSession, service: QueueService) -> None:
        super().__init__()
        self.setObjectName("pageSurface")
        self._session = session
        self._service = service
        self._mode = "all"
        self._entries: tuple[QueueEntry, ...] | None = None
        self._error = ""  # a refused cancel/resume; survives the refresh that follows it
        self.rows: list[QueueRow] = []
        self._build()
        service.updated.connect(self._updated)
        service.failed.connect(self._failed)
        service.action_failed.connect(self._action_failed)
        service.cleared.connect(self._cleared)
        session.changed.connect(self._session_changed)
        self._session_changed()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(38, 34, 38, 24)
        outer.setSpacing(12)
        outer.addWidget(_label("QUEUE / STUDIO", "sectionCaption"))
        outer.addWidget(_label("Queue", "pageHeading"))
        self.status_line = _label("", "pageDescription", wrap=True)
        outer.addWidget(self.status_line)
        self.connect_button = QPushButton("Open connection settings")
        self.connect_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.connect_button.clicked.connect(self.open_connections)
        outer.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignLeft)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, text in FILTERS:
            button = QPushButton(text)
            button.setObjectName("segButton")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _c=False, k=key: self.set_filter(k))
            bar.addWidget(button)
            self.filter_buttons[key] = button
        self.filter_buttons["all"].setChecked(True)
        bar.addStretch(1)
        self.summary = _label("", "hint")
        bar.addWidget(self.summary)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._service.refresh)
        bar.addWidget(self.refresh_button)
        self.filter_bar = QWidget()
        self.filter_bar.setLayout(bar)
        outer.addWidget(self.filter_bar)

        self.note = _label("", "hint", wrap=True)
        outer.addWidget(self.note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        self.list_box = QVBoxLayout(holder)
        self.list_box.setContentsMargins(0, 0, 0, 0)
        self.list_box.setSpacing(8)
        self.list_box.addStretch(1)
        self.scroll.setWidget(holder)
        outer.addWidget(self.scroll, 1)

    # -- public ---------------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        self._service.set_active(active)

    def set_filter(self, mode: str) -> None:
        self._mode = mode
        self._error = ""
        for key, button in self.filter_buttons.items():
            button.setChecked(key == mode)
        self._fill()

    # -- data -----------------------------------------------------------------------------

    def _updated(self, entries) -> None:
        self._entries = entries
        self._fill()

    def _fill(self) -> None:
        for row in self.rows:
            self.list_box.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.rows = []
        entries = self._entries or ()
        shown = [e for e in entries if keep(e, self._mode)]
        for position, entry in enumerate(shown):
            row = QueueRow(entry)
            row.cancel_clicked.connect(lambda e: self._act(self._service.cancel, e))
            row.resume_clicked.connect(lambda e: self._act(self._service.resume, e))
            row.open_clicked.connect(self._open)
            self.list_box.insertWidget(position, row)
            row.show()  # rows may be added while this page is hidden
            self.rows.append(row)
        self.summary.setText(summary_text(entries) if self._entries is not None else "")
        if self._error:
            self.note.setText(self._error)
        elif self._entries is None:
            self.note.setText("Loading…" if self._service.available else "")
        elif not shown:
            self.note.setText("Nothing here yet. Jobs from the Lab and renders from the Timeline appear here."
                              if not entries else "No jobs match this filter.")
        else:
            self.note.setText("")
        self.note.setVisible(bool(self.note.text()))

    def _act(self, action, entry: QueueEntry) -> None:
        self._error = ""
        action(entry)

    def _open(self, entry: QueueEntry) -> None:
        if entry.kind == "render" and entry.project_id:
            self.open_timeline.emit(entry.project_id)
        elif entry.kind == "image":
            self.open_lab.emit()

    def _failed(self, code: str) -> None:
        self.note.setText(f"Could not read the queue ({code}). Studio is retrying.")
        self.note.setVisible(True)

    def _action_failed(self, message: str) -> None:
        self._error = message
        self._fill()

    def _cleared(self) -> None:
        self._entries = None
        self._error = ""
        self._fill()

    def _session_changed(self) -> None:
        info = self._session.info
        connected = self._session.state == "connected"
        usable = self._service.available
        self.filter_bar.setVisible(usable)
        self.scroll.setVisible(usable)
        if info is None:
            self.status_line.setText("Connect to a Morphorum backend to see its queue.")
        elif connected and not usable:
            self.status_line.setText("The connected backend does not report image jobs or renders.")
        elif not connected:
            self.status_line.setText("The backend is not responding. Studio is retrying.")
        else:
            self.status_line.setText("Image jobs and animation renders on the connected backend.")
        self.connect_button.setVisible(info is None or (connected and not usable))
