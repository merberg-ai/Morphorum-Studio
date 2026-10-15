"""Console page: the backend's live log with filters, search, follow, copy and save."""

from __future__ import annotations

from html import escape
import re

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.console import LEVELS, ConsoleEntry
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.console_service import ConsoleService
from morphorum_studio.ui.tokens import DARK

FLUSH_MS = 100
LEVEL_COLOR = {"debug": DARK.faint, "info": DARK.text, "warning": DARK.warn,
               "error": DARK.bad, "critical": DARK.bad}
STATE_TEXT = {"live": "Live", "connecting": "Connecting…", "reconnecting": "Reconnecting…",
              "stopped": "Not streaming"}
ALL = "All"
_ACCESS_LOG = re.compile(r'\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/api/', re.I)
_STATUS = re.compile(r'\b([1-5]\d{2})\b')


def is_api_request_noise(entry: ConsoleEntry) -> bool:
    """Filter routine API access logging, never warnings or failed requests."""
    if entry.level not in ("debug", "info") or not _ACCESS_LOG.search(entry.message):
        return False
    return not any(int(code) >= 400 for code in _STATUS.findall(entry.message))



def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def format_entry(entry: ConsoleEntry) -> str:
    stamp = entry.timestamp[11:23] if len(entry.timestamp) >= 23 else entry.timestamp
    return f"{stamp}  {entry.level.upper():<8} {entry.category:<10} {entry.message}"


class ConsolePage(QWidget):
    open_connections = Signal()

    def __init__(self, session: BackendSession, service: ConsoleService, preferences=None) -> None:
        super().__init__()
        self._prefs = preferences
        self.setObjectName("pageSurface")
        self._session = session
        self._service = service
        self._queue: list[ConsoleEntry] = []
        self._markers: list[tuple[int, str]] = []  # (entries held when it happened, text)
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(FLUSH_MS)
        self._timer.timeout.connect(self._flush)
        self._timer.start()
        service.entries_added.connect(self._queue.extend)
        service.marker.connect(self._marker)
        service.state_changed.connect(self._state)
        service.cleared.connect(self._cleared)
        session.changed.connect(self._state_from_session)
        self._state(service.state)
        self._rebuild()

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(38, 34, 38, 24)
        box.setSpacing(10)
        box.addWidget(_label("CONSOLE / STUDIO", "sectionCaption"))
        box.addWidget(_label("Backend console", "pageHeading"))
        self.status = _label("", "pageDescription", wrap=True)
        box.addWidget(self.status)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.level = QComboBox()
        self.level.addItem("All levels", "debug")
        self.level.addItem("Info and up", "info")
        self.level.addItem("Warnings and up", "warning")
        self.level.addItem("Errors only", "error")
        self.level.setCurrentIndex(0)
        self.category = QComboBox()
        self.category.addItem("All categories", ALL)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search text…")
        self.search.setClearButtonEnabled(True)
        self.follow = QCheckBox("Follow")
        self.follow.setChecked(True)
        self.wrap = QCheckBox("Wrap")
        self.show_api = QCheckBox("Show API requests")
        self.show_api.setToolTip("Show routine HTTP access lines; warnings and errors are retained.")
        self.clear_button = QPushButton("Clear view")
        self.copy_button = QPushButton("Copy")
        self.save_button = QPushButton("Save…")
        bar.addWidget(self.level)
        bar.addWidget(self.category)
        bar.addWidget(self.search, 1)
        for widget in (self.follow, self.wrap, self.show_api, self.clear_button, self.copy_button, self.save_button):
            if isinstance(widget, QPushButton):
                widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            bar.addWidget(widget)
        box.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setMaximumBlockCount(6000)
        self.view.setObjectName("consoleView")
        box.addWidget(self.view, 1)
        self.count = _label("", "hint")
        box.addWidget(self.count)

        if self._prefs is not None:  # restore the remembered view
            self.level.setCurrentIndex(max(0, self.level.findData(self._prefs.ui("console/level", "debug"))))
            self.follow.setChecked(self._prefs.ui("console/follow", "1") == "1")
            self.wrap.setChecked(self._prefs.ui("console/wrap", "0") == "1")
            self.show_api.setChecked(self._prefs.ui("console/show_api", "0") == "1")
        self.level.currentIndexChanged.connect(lambda _i: self._remember())
        self.follow.toggled.connect(lambda _c: self._remember())
        self.wrap.toggled.connect(lambda _c: self._remember())
        self.show_api.toggled.connect(lambda _c: self._remember())
        self.show_api.toggled.connect(lambda _c: self._rebuild())
        self.level.currentIndexChanged.connect(lambda _i: self._rebuild())
        self.category.currentIndexChanged.connect(lambda _i: self._rebuild())
        self.search.textChanged.connect(lambda _t: self._rebuild())
        self.wrap.toggled.connect(lambda on: self.view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if on else QPlainTextEdit.LineWrapMode.NoWrap))
        self.clear_button.clicked.connect(self._service.clear_view)
        self.copy_button.clicked.connect(self._copy)
        self.save_button.clicked.connect(self._save)

    # -- filtering ------------------------------------------------------------------------

    def _matches(self, entry: ConsoleEntry) -> bool:
        if not self.show_api.isChecked() and is_api_request_noise(entry):
            return False
        floor = LEVELS.index(self.level.currentData())
        if LEVELS.index(entry.level) < floor:
            return False
        wanted = self.category.currentData()
        if wanted != ALL and entry.category != wanted:
            return False
        needle = self.search.text().strip().lower()
        return not needle or needle in entry.message.lower() or needle in entry.category

    def _line_html(self, entry: ConsoleEntry) -> str:
        return (f'<span style="color:{LEVEL_COLOR.get(entry.level, DARK.text)};white-space:pre">'
                f"{escape(format_entry(entry))}</span>")

    def _note_html(self, text: str) -> str:
        return f'<span style="color:{DARK.cyan}">— {escape(text)} —</span>'

    def _note_categories(self, entries) -> None:
        known = {self.category.itemData(i) for i in range(self.category.count())}
        for name in sorted({e.category for e in entries} - known):
            self.category.blockSignals(True)
            self.category.addItem(name, name)
            self.category.blockSignals(False)

    def _remember(self) -> None:
        if self._prefs is not None:
            self._prefs.set_ui("console/level", str(self.level.currentData()))
            self._prefs.set_ui("console/follow", "1" if self.follow.isChecked() else "0")
            self._prefs.set_ui("console/wrap", "1" if self.wrap.isChecked() else "0")
            self._prefs.set_ui("console/show_api", "1" if self.show_api.isChecked() else "0")

    def _rebuild(self) -> None:
        held = list(self._service.entries)
        self._note_categories(held)
        self._queue.clear()
        self.view.clear()
        shown = 0
        marks = iter(sorted(self._markers))
        mark = next(marks, None)
        for index, entry in enumerate(held):
            while mark is not None and mark[0] <= index:
                self.view.appendHtml(self._note_html(mark[1]))
                mark = next(marks, None)
            if self._matches(entry):
                self.view.appendHtml(self._line_html(entry))
                shown += 1
        while mark is not None:
            self.view.appendHtml(self._note_html(mark[1]))
            mark = next(marks, None)
        self._shown = shown
        self._update_count()
        self._scroll()

    def _flush(self) -> None:
        if not self._queue:
            return
        batch, self._queue[:] = list(self._queue), []
        self._note_categories(batch)
        lines = [self._line_html(e) for e in batch if self._matches(e)]
        if lines:
            for line in lines:
                self.view.appendHtml(line)
            self._shown += len(lines)
            self._update_count()
            self._scroll()

    def _scroll(self) -> None:
        if self.follow.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _update_count(self) -> None:
        total = len(self._service.entries)
        self.count.setText(f"{self._shown} shown of {total} held in Studio "
                           "(the backend keeps its own recent 1500).")

    # -- service events -------------------------------------------------------------------

    def _marker(self, text: str) -> None:
        self._markers.append((len(self._service.entries), text))
        self._markers = self._markers[-50:]
        self.view.appendHtml(self._note_html(text))
        self._scroll()

    def _cleared(self) -> None:
        self._markers.clear()
        self._queue.clear()
        self._rebuild()

    def _state(self, state: str) -> None:
        self._state_from_session()

    def _state_from_session(self) -> None:
        state = self._service.state
        if self._session.state == "offline":
            text = "Connect to a backend to see its console."
        elif not self._session.feature("console_sse"):
            text = "This backend does not advertise a console stream."
        else:
            text = STATE_TEXT.get(state, state)
        self.status.setText(text)

    # -- output ---------------------------------------------------------------------------

    def visible_text(self) -> str:
        return "\n".join(format_entry(e) for e in self._service.entries if self._matches(e))

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.visible_text())

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save console", "morphorum-console.txt",
                                              "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(self.visible_text() + "\n")
        except OSError as exc:
            self.status.setText(f"Could not save: {exc.strerror or 'error'}")
