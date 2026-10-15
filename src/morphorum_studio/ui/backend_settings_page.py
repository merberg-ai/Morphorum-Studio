"""Settings > Backend settings: the connected backend's model folders, managed model storage and
memory behaviour, the same set the Morphorum web UI edits (its browser look-and-feel is not shown).

Folders live on the backend's computer. Browse appears only when the backend runs on this PC.
Only changed values are sent. Folder changes take effect after the backend rescans its models.
"""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.backend_settings import (
    PERFORMANCE_FLAGS,
    BackendSettings,
    PathCheck,
    build_update,
)
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.backend_settings_service import BackendSettingsService
from morphorum_studio.ui.feedback import FeedbackBanner
from morphorum_studio.ui.connections_panel import COLUMN_WIDTH, _FitScroll

KIND_TITLE = {"checkpoints": "checkpoint folders", "loras": "LoRA folders"}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MAX_CHECKS = 20


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _small(button: QPushButton, width: int = 0) -> QPushButton:
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    if width:
        button.setMinimumWidth(width)
    return button


class BackendSettingsPage(QWidget):
    models_changed = Signal()  # the backend rescanned its model folders

    def __init__(self, session: BackendSession, service: BackendSettingsService,
                 choose_folder: Callable[[QWidget, str], str] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session, self._service = session, service
        self._choose = choose_folder or (lambda parent, start: QFileDialog.getExistingDirectory(
            parent, "Choose a folder", start))
        self.original: BackendSettings | None = None
        self.draft: BackendSettings | None = None
        self._checks: dict[str, PathCheck] = {}  # what the backend said about each folder
        self._rows: list[dict] = []
        self._requested = False
        self._active = False
        self._rescan_after_save = False
        self._build()
        service.loaded.connect(self._loaded)
        service.saved.connect(self._saved)
        service.checked.connect(self._checked)
        service.scanned.connect(self._scanned)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(self._cleared)
        session.changed.connect(self._session_changed)
        self._update()

    # ---- layout -----------------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = _FitScroll()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        page = QVBoxLayout(content)
        page.setContentsMargins(12, 8, 12, 24)
        column = QWidget()
        column.setMaximumWidth(1400)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        page.addWidget(column, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        page.addStretch(1)
        self.layout_ = QVBoxLayout(column)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(16)
        self.layout_.addWidget(_label("BACKEND / STUDIO", "sectionCaption", wrap=False))
        self.layout_.addWidget(_label("Backend settings", "pageHeading", wrap=False))
        self.layout_.addWidget(_label(
            "These settings belong to the connected backend, so they apply to everything that uses it. "
            "Folders are on the backend's computer.", "pageDescription"))
        self.status_line = _label("", "connectionDetails")
        self.layout_.addWidget(self.status_line)
        self.feedback = FeedbackBanner()
        self.layout_.addWidget(self.feedback)
        self.form = QWidget()
        self.form_box = QVBoxLayout(self.form)
        self.form_box.setContentsMargins(0, 0, 0, 0)
        self.form_box.setSpacing(16)
        self.layout_.addWidget(self.form)

        buttons = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        buttons.setSpacing(10)
        self.footer_buttons = buttons
        self.reload_button = _small(QPushButton("Reload"), 90)
        self.reload_button.clicked.connect(self.reload)
        self.revert_button = _small(QPushButton("Revert"), 90)
        self.revert_button.clicked.connect(self.revert)
        self.rescan_button = _small(QPushButton("Rescan models"), 130)
        self.rescan_button.setToolTip("Ask the backend to look through its model folders again")
        self.rescan_button.clicked.connect(self.rescan)
        self.save_button = _small(QPushButton("Save"), 100)
        self.save_button.setObjectName("primaryAction")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.reload_button)
        buttons.addStretch(1)
        for button in (self.revert_button, self.rescan_button, self.save_button):
            buttons.addWidget(button)
        self.footer = QWidget()
        self.footer.setLayout(buttons)
        self.layout_.addWidget(self.footer)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        direction = (QBoxLayout.Direction.TopToBottom if self.width() < 640
                     else QBoxLayout.Direction.LeftToRight)
        if self.footer_buttons.direction() != direction:
            self.footer_buttons.setDirection(direction)

    def _card(self, title: str, note: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 18, 20, 20)
        box.setSpacing(10)
        box.addWidget(_label(title, "cardTitle", wrap=False))
        if note:
            box.addWidget(_label(note, "hint"))
        self.form_box.addWidget(card)
        return card, box

    def _clear_form(self) -> None:
        self._rows = []
        while self.form_box.count():
            item = self.form_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # ---- building the form from the draft ------------------------------------------------

    def _local(self) -> bool:
        info = self._session.info
        host = urlsplit(info.base_url).hostname if info is not None else None
        return host in LOOPBACK

    def _build_form(self) -> None:
        self._clear_form()
        draft = self.draft
        if draft is None:
            return
        for family in draft.families:
            for kind, folders in draft.paths.get(family.id, {}).items():
                self._folder_card(family.id, f"{family.label} {KIND_TITLE.get(kind, kind)}", kind, folders)
        managed = [f for f in draft.families if f.managed]
        if managed:
            _card, box = self._card(
                "Managed model storage",
                "Where Morphorum keeps models it downloads for you. A relative folder is inside the "
                "backend's install folder.")
            for family in managed:
                box.addWidget(_label(f"{family.label} storage", "fieldLabel", wrap=False))
                box.addLayout(self._path_row(
                    draft.managed.get(family.id, ""), self._storage_setter(family.id),
                    name=f"{family.label} storage folder"))
        _card, box = self._card("Memory and performance")
        self._flag_boxes = {}
        for key, title, help_text in PERFORMANCE_FLAGS:
            check = QCheckBox(title)
            check.setChecked(draft.flags.get(key, False))
            check.toggled.connect(lambda on, k=key: self._flag(k, on))
            box.addWidget(check)
            box.addWidget(_label(help_text, "hint"))
            self._flag_boxes[key] = check

    def _storage_setter(self, family: str) -> Callable[[str], None]:
        def set_folder(text: str) -> None:
            if self.draft is not None:
                self.draft.managed[family] = text
                self._update()

        return set_folder

    def _flag(self, key: str, on: bool) -> None:
        if self.draft is not None:
            self.draft.flags[key] = bool(on)
            self._update()

    def _folder_card(self, family: str, title: str, kind: str, folders: list[str]) -> None:
        _card, box = self._card(title[:1].upper() + title[1:],
                                "Folders are on the backend's computer. Add one path per field.")
        paths_box = QVBoxLayout()
        paths_box.setSpacing(6)
        box.addLayout(paths_box)
        message = _label("", "hint")
        entry = {"folders": folders, "message": message, "paths_box": paths_box,
                 "edits": [], "remove_buttons": [], "edit": None}
        self._rows.append(entry)

        def changed() -> None:
            folders[:] = [edit.text().strip() for edit in entry["edits"] if edit.text().strip()]
            self._show_messages(entry)
            self._update()

        def remove(edit: QLineEdit) -> None:
            index = entry["edits"].index(edit)
            entry["edits"].pop(index)
            entry["remove_buttons"].pop(index)
            row = paths_box.takeAt(index)
            if row is not None and row.widget() is not None:
                row.widget().deleteLater()
            if not entry["edits"]:
                add_path("")
            changed()

        def add_path(value: str = "") -> None:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            edit = QLineEdit(value)
            edit.setPlaceholderText("Folder path on the backend computer")
            edit.setToolTip(title)
            edit.setAccessibleName(f"{title} folder path")
            edit.textEdited.connect(lambda _text: changed())
            layout.addWidget(edit, 1)
            remove_button = _small(QPushButton("Remove"))
            remove_button.clicked.connect(lambda _checked=False, field=edit: remove(field))
            layout.addWidget(remove_button)
            entry["edits"].append(edit)
            entry["remove_buttons"].append(remove_button)
            entry["edit"] = entry["edits"][0]
            paths_box.addWidget(row)

        entry["add_path"] = add_path
        for value in folders or [""]:
            add_path(value)
        box.addWidget(message)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add = _small(QPushButton("Add folder"), 105)
        add.clicked.connect(lambda: add_path(""))
        buttons.addWidget(add)
        if self._local():
            browse = _small(QPushButton("Browse…"), 90)
            browse.clicked.connect(lambda: self._browse_into(entry))
            buttons.addWidget(browse)
        check = _small(QPushButton("Check folders"), 120)
        check.clicked.connect(lambda: self._check_folders(entry))
        buttons.addWidget(check)
        buttons.addStretch(1)
        box.addLayout(buttons)
        self._show_messages(entry)

    def _browse_into(self, entry: dict) -> None:
        chosen = self._choose(self, entry["folders"][-1] if entry["folders"] else "")
        if chosen and chosen not in entry["folders"]:
            blank = next((edit for edit in entry["edits"] if not edit.text().strip()), None)
            if blank is None:
                entry["add_path"](chosen)
            else:
                blank.setText(chosen)
            entry["folders"][:] = [edit.text().strip() for edit in entry["edits"] if edit.text().strip()]
            self._show_messages(entry)
            self._update()

    def _check_folders(self, entry: dict) -> None:
        for path in entry["folders"][:MAX_CHECKS]:
            self._service.check(path)

    def _show_messages(self, entry: dict) -> None:
        lines = []
        for path in entry["folders"]:
            found = self._checks.get(path)
            if found is not None:
                lines.append(("OK: " if found.ok else "Problem: ") + f"{path} - {found.message}")
        entry["message"].setText("\n".join(lines))
        entry["message"].setVisible(bool(lines))

    def _path_row(self, value: str, on_change: Callable[[str], None], *, name: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        edit = QLineEdit(value)
        edit.setToolTip(name)
        edit.setPlaceholderText("Folder on the backend's computer")
        edit.textEdited.connect(on_change)
        row.addWidget(edit, 1)
        if self._local():
            browse = _small(QPushButton("Browse…"), 90)

            def pick() -> None:
                chosen = self._choose(self, edit.text())
                if chosen:
                    edit.setText(chosen)
                    on_change(chosen)

            browse.clicked.connect(pick)
            row.addWidget(browse)
        return row

    # ---- actions ------------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and self._service.available and self.original is None and not self._service.busy:
            self.reload()

    def reload(self) -> None:
        if not self._service.available:
            return
        self._requested = True
        self.status_line.setText("Loading the backend's settings…")
        self._service.load()

    def revert(self) -> None:
        if self.original is not None:
            self.draft = self.original.copy()
            self._build_form()
            self.status_line.setText("Changes discarded.")
            self._update()

    def save(self) -> None:
        if self.original is None or self.draft is None or self._service.busy:
            return
        body = build_update(self.original, self.draft)
        if not body:
            self.status_line.setText("Nothing has changed.")
            return
        self.status_line.setText("Saving…")
        self.feedback.notify("Saving backend settings…", busy=True)
        self._rescan_after_save = "models" in body or "managed_models" in body
        self._service.save(body)

    def rescan(self) -> None:
        if self._service.available and not self._service.busy:
            self.status_line.setText("Rescanning models… this can take a while for large folders.")
            self.feedback.notify("Scanning backend model directories…", busy=True)
            self._service.rescan()

    @property
    def dirty(self) -> bool:
        return self.original is not None and self.draft is not None and bool(build_update(self.original, self.draft))

    # ---- results ------------------------------------------------------------------------

    def _remember_checks(self, data: BackendSettings) -> None:
        self._checks = {c.path: c for found in data.checks.values() for c in found}

    def _loaded(self, data: BackendSettings) -> None:
        self.original, self.draft = data, data.copy()
        self._remember_checks(data)
        self._build_form()
        self.status_line.setText("")
        self.feedback.notify("Backend settings loaded.", kind="success")
        self._update()

    def _saved(self, data: BackendSettings) -> None:
        self.original, self.draft = data, data.copy()
        self._remember_checks(data)
        self._build_form()
        bad = sum(1 for found in data.checks.values() for c in found if not c.ok)
        text = "Saved." + (f" {bad} folder(s) could not be used; see the messages below." if bad else "")
        if self._rescan_after_save:
            self._rescan_after_save = False
            self.status_line.setText(text + " Rescanning models…")
            self.feedback.notify(text + " Rescanning models…", kind="warning" if bad else "info", busy=True)
            self._service.rescan()  # the backend only lists models after a scan
        else:
            self.status_line.setText(text)
            self.feedback.notify(text, kind="warning" if bad else "success")
        self._update()

    def _checked(self, path: str, found: PathCheck) -> None:
        self._checks[path] = found
        for entry in self._rows:
            self._show_messages(entry)

    def _scanned(self, result) -> None:
        labels = {f.id: f.label for f in self.draft.families} if self.draft is not None else {}
        self.status_line.setText(result.describe(labels))
        self.feedback.notify("Model scan finished. " + result.describe(labels), kind="success")
        self.models_changed.emit()

    def _failed(self, operation: str, code: str, message: str) -> None:
        self.status_line.setText(f"Could not {'check the folder' if operation == 'check' else operation}: {message}")
        self.feedback.notify(self.status_line.text(), kind="error")
        self._update()

    def _cleared(self) -> None:
        self.original = self.draft = None
        self._requested = False
        self._checks = {}
        self._clear_form()
        self.feedback.hide()
        self._update()

    def _session_changed(self) -> None:
        if self._service.available and self.original is None and self._active and not self._service.busy:
            self.reload()
        self._update()

    # ---- state --------------------------------------------------------------------------

    def _update(self) -> None:
        connected = self._service.available
        loaded = self.original is not None
        busy = self._service.busy
        self.form.setVisible(connected and loaded)
        self.footer.setVisible(connected)
        if not connected:
            self.status_line.setText("Connect to a backend to see and change its settings.")
        elif not loaded and not busy and not self._requested:
            self.status_line.setText("Press Reload to read the backend's settings.")
        dirty = self.dirty
        self.save_button.setEnabled(connected and loaded and dirty and not busy)
        self.revert_button.setEnabled(connected and loaded and dirty and not busy)
        self.reload_button.setEnabled(connected and not busy and not dirty)
        self.rescan_button.setEnabled(connected and loaded and not dirty and not busy)
