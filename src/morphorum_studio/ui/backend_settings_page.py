"""Settings > Backend settings: the connected backend's model folders, managed model storage and
memory behaviour, the same set the Morphorum web UI edits (its browser look-and-feel is not shown).

Folders live on the backend's computer. Browse appears only when the backend runs on this PC.
Only changed values are sent. Folder changes take effect after the backend rescans its models.
"""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
from morphorum_studio.ui.connections_panel import COLUMN_WIDTH, _FitScroll

KIND_TITLE = {"checkpoints": "checkpoint folders", "loras": "LoRA folders"}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


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
        page.setContentsMargins(28, 8, 28, 24)
        column = QWidget()
        column.setMaximumWidth(COLUMN_WIDTH)
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
        self.form = QWidget()
        self.form_box = QVBoxLayout(self.form)
        self.form_box.setContentsMargins(0, 0, 0, 0)
        self.form_box.setSpacing(16)
        self.layout_.addWidget(self.form)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
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
                    check=False, remove=None, name=f"{family.label} storage folder"))
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
        _card, box = self._card(title[:1].upper() + title[1:])
        holder = QWidget()
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(8)
        box.addWidget(holder)

        def fill() -> None:
            while rows.count():
                widget = rows.takeAt(0).widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
            if not folders:
                rows.addWidget(_label("No folders yet.", "hint"))
            for index in range(len(folders)):
                rows.addWidget(self._folder_row(folders, index, fill))

        add = _small(QPushButton("Add folder"), 110)
        add.clicked.connect(lambda: (folders.append(""), fill(), self._update()))
        box.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        self._rows.append({"family": family, "kind": kind, "add": add})
        fill()

    def _folder_row(self, folders: list[str], index: int, refill: Callable[[], None]) -> QWidget:
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        message = _label("", "hint")

        def show_message() -> None:
            found = self._checks.get(folders[index].strip())
            message.setText(("OK: " if found.ok else "Problem: ") + found.message if found else "")
            message.setVisible(bool(found))

        def changed(text: str) -> None:
            folders[index] = text
            show_message()
            self._update()

        def remove() -> None:
            del folders[index]
            refill()
            self._update()

        column.addLayout(self._path_row(folders[index], changed, check=False, remove=None,
                                        name=f"Folder {index + 1}"))
        return container

    def _path_row(self, value: str, on_change: Callable[[str], None], *, check: bool,
                  remove: Callable[[], None] | None, name: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        edit = QLineEdit(value)
        edit.setToolTip(name)  # an accessible name on an editable field crashes Qt on Windows at exit
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
        if check:
            button = _small(QPushButton("Check"), 70)
            button.clicked.connect(lambda: self._service.check(edit.text().strip()) if edit.text().strip() else None)
            row.addWidget(button)
        if remove is not None:
            drop = _small(QPushButton("Remove"), 80)
            drop.clicked.connect(remove)
            row.addWidget(drop)
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
        self._service.save(body)

    def rescan(self) -> None:
        if self._service.available and not self._service.busy:
            self.status_line.setText("Rescanning models… this can take a while for large folders.")
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
        self._update()

    def _saved(self, data: BackendSettings) -> None:
        self.original, self.draft = data, data.copy()
        self._remember_checks(data)
        self._build_form()
        bad = sum(1 for found in data.checks.values() for c in found if not c.ok)
        self.status_line.setText(
            "Saved." + (f" {bad} folder(s) could not be used; see the messages below." if bad else "")
            + " Rescan models so the backend picks up folder changes.")
        self._update()

    def _checked(self, path: str, found: PathCheck) -> None:
        self._checks[path] = found
        self._build_form_keep_draft()

    def _build_form_keep_draft(self) -> None:
        if self.draft is not None:
            self._build_form()

    def _scanned(self, total, warnings) -> None:
        text = f"Rescan finished: {total} model(s) found." if total is not None else "Rescan finished."
        if warnings:
            text += " " + " ".join(warnings[:3])
        self.status_line.setText(text)

    def _failed(self, operation: str, code: str, message: str) -> None:
        self.status_line.setText(f"Could not {'check the folder' if operation == 'check' else operation}: {message}")
        self._update()

    def _cleared(self) -> None:
        self.original = self.draft = None
        self._requested = False
        self._checks = {}
        self._clear_form()
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
