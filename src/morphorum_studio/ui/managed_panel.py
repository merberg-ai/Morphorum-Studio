"""Simple connection mode: Studio runs a Morphorum backend on this PC and connects to it.

This step manages a Morphorum folder that is already installed. The panel never offers a
control it cannot honour: there is no install button yet. Studio stops only a backend it
started itself, and the credential it uses is a revocable client token kept in the OS keyring.
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend import managed
from morphorum_studio.backend.credentials import CredentialStore
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui import managed_backend as mb
from morphorum_studio.ui.connections_panel import COLUMN_WIDTH, ConnectionsPanel, _FitScroll

STATE_CHIP = {
    mb.UNCONFIGURED: ("No folder", "idle"),
    mb.STOPPED: ("Stopped", "idle"),
    mb.STARTING: ("Starting", "busy"),
    mb.RUNNING: ("Running", "ok"),
    mb.STOPPING: ("Stopping", "busy"),
    mb.ADOPTED: ("Already running", "warn"),
    mb.CRASHED: ("Stopped unexpectedly", "bad"),
    mb.PORT_BUSY: ("Port in use", "warn"),
    mb.ERROR: ("Needs attention", "bad"),
}
CONNECTION_TEXT = {
    "BACKEND CONNECTED": "Connected to the managed backend.",
    "BACKEND CONNECTING": "Connecting…",
    "BACKEND UNAUTHORIZED": "The backend rejected Studio's credential. Use Reset credential.",
    "BACKEND INCOMPATIBLE": "This backend's API does not match Studio. Update the backend or Studio.",
    "BACKEND RECONNECTING": "Reconnecting…",
    "BACKEND IDENTITY MISMATCH": "The backend identity changed and was not accepted.",
    "BACKEND OFFLINE": "Not connected.",
}


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def open_in_file_manager(path: str) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - opens a folder the person chose
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", path])  # noqa: S603, S607


class ManagedPanel(QWidget):
    startup_progress = Signal(str)  # plain-language step while Studio opens
    startup_done = Signal(bool, str)  # connected?, reason when not

    def __init__(self, connections: ConnectionsPanel, backend: mb.ManagedBackend,
                 store: managed.ManagedStore | None = None, vault: CredentialStore | None = None,
                 session: BackendSession | None = None,
                 issuer_factory: Callable[[str], mb.CredentialIssuer] = mb.CredentialIssuer,
                 active_jobs: Callable[[], int] = lambda: 0,
                 ask_exit: Callable[[int], str] | None = None,
                 choose_folder: Callable[[QWidget, str], str] | None = None,
                 open_folder: Callable[[str], None] = open_in_file_manager,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.connections, self.backend = connections, backend
        self.store = store or managed.ManagedStore()
        self.vault = vault or connections.vault
        self.session = session or connections.session
        self._issuer_factory, self._active_jobs = issuer_factory, active_jobs
        self._ask_exit = ask_exit or self._ask_exit_dialog
        self._choose_folder = choose_folder or self._choose_folder_dialog
        self._open_folder = open_folder
        self._issuer: mb.CredentialIssuer | None = None
        self._connect_when_ready = False
        self._restart = False
        self._starting_up = False  # Studio is opening and bringing the backend up
        self._startup_connecting = False
        self._notice = ""  # a message about the last action; replaces the backend's own detail
        self.settings = self.store.load()
        if not self.settings.folder:
            self.settings.folder = ""  # the person chooses; nothing is created on their disk yet
        self._build()
        backend.state_changed.connect(self._state_changed)
        backend.log_line.connect(self._append_log)
        backend.ready.connect(self._backend_ready)
        connections.status_changed.connect(self._connection_changed)
        self.session.changed.connect(self._update)
        self.folder_edit.setText(self.settings.folder)
        for widget, apply in ((self.port, lambda: self.port.setValue(self.settings.port)),
                              (self.autostart, lambda: self.autostart.setChecked(self.settings.autostart)),
                              (self.stop_on_exit, lambda: self.stop_on_exit.setChecked(self.settings.stop_on_exit))):
            widget.blockSignals(True)  # showing saved values is not a change to save
            apply()
            widget.blockSignals(False)
        backend.configure(self.settings.folder, self.settings.port)
        self._show_folder_check()
        self._update()

    # ---- layout -------------------------------------------------------------------

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(_label(title, "cardTitle", wrap=False))
        return card, layout

    @staticmethod
    def _fixed(button: QPushButton, min_width: int = 0) -> QPushButton:
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if min_width:
            button.setMinimumWidth(min_width)
        return button

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
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(_label("BACKEND CONNECTIONS / STUDIO", "sectionCaption", wrap=False))
        layout.addWidget(_label("Backend connection", "pageHeading", wrap=False))
        layout.addWidget(_label(
            "Studio runs Morphorum on this PC and connects to it. Choose a folder where Morphorum is "
            "installed. Installing a new copy from Studio is not available yet.", "pageDescription"))

        folder_card, box = self._card("Morphorum folder")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText(str(managed.default_folder()))
        self.folder_edit.setAccessibleName("Morphorum folder")
        self.choose_button = self._fixed(QPushButton("Choose folder…"), 130)
        self.choose_button.clicked.connect(self.choose)
        self.open_button = self._fixed(QPushButton("Open folder"), 110)
        self.open_button.clicked.connect(self._open)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(self.choose_button)
        row.addWidget(self.open_button)
        box.addLayout(row)
        self.folder_note = _label("", "hint")
        box.addWidget(self.folder_note)
        port_row = QHBoxLayout()
        port_row.setSpacing(10)
        port_row.addWidget(_label("Port", "fieldLabel", wrap=False))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setAccessibleName("Backend port")
        self.port.valueChanged.connect(self._port_changed)
        port_row.addWidget(self.port)
        port_row.addStretch(1)
        box.addLayout(port_row)
        self.autostart = QCheckBox("Start the backend and connect when Studio opens")
        self.autostart.setToolTip("Applies when this was the backend you used last.")
        self.autostart.toggled.connect(self._autostart_changed)
        box.addWidget(self.autostart)
        self.stop_on_exit = QCheckBox("Stop the backend when Studio closes")
        self.stop_on_exit.toggled.connect(self._exit_setting_changed)
        box.addWidget(self.stop_on_exit)
        box.addWidget(_label(
            "The backend listens on this PC only. Studio stops only a backend that Studio started.", "hint"))
        layout.addWidget(folder_card)

        run_card, rbox = self._card("Backend")
        head = QHBoxLayout()
        head.setSpacing(12)
        self.chip = _label("", "chip", wrap=False)
        head.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignTop)
        self.detail = _label("", "connectionDetails")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(self.detail, 1)
        rbox.addLayout(head)
        self.connection_line = _label("", "hint")
        rbox.addWidget(self.connection_line)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.reset_button = self._fixed(QPushButton("Reset credential"), 130)
        self.reset_button.setToolTip("Create a new Studio credential for this backend")
        self.reset_button.clicked.connect(self.reset_credential)
        self.restart_button = self._fixed(QPushButton("Restart"), 90)
        self.restart_button.clicked.connect(self.restart)
        self.stop_button = self._fixed(QPushButton("Stop"), 90)
        self.stop_button.setObjectName("dangerAction")
        self.stop_button.clicked.connect(self.stop)
        self.start_button = self._fixed(QPushButton("Start and connect"), 150)
        self.start_button.setObjectName("primaryAction")
        self.start_button.clicked.connect(self.start)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        for button in (self.restart_button, self.stop_button, self.start_button):
            buttons.addWidget(button)
        rbox.addLayout(buttons)
        self.log_toggle = QToolButton()
        self.log_toggle.setObjectName("linkButton")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setText("▸  Backend output")
        self.log_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_toggle.toggled.connect(self._toggle_log)
        rbox.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(mb.KEEP_LINES)
        self.log.setMinimumHeight(160)
        self.log.setAccessibleName("Backend output")
        self.log.setVisible(False)
        rbox.addWidget(self.log)
        layout.addWidget(run_card)

    def _toggle_log(self, shown: bool) -> None:
        self.log.setVisible(shown)
        self.log_toggle.setText(("▾" if shown else "▸") + "  Backend output")

    def _append_log(self, line: str) -> None:
        self.log.appendPlainText(line)

    # ---- folder and settings --------------------------------------------------------

    def _persist(self) -> None:
        try:
            self.store.save(self.settings)
        except OSError as exc:
            self.folder_note.setText(f"Could not save these settings: {exc}")

    def _choose_folder_dialog(self, parent: QWidget, start: str) -> str:
        return QFileDialog.getExistingDirectory(parent, "Choose the Morphorum folder", start)

    def choose(self) -> None:
        if self.backend.owned:
            return
        start = self.settings.folder or str(managed.default_folder().parent)
        chosen = self._choose_folder(self, start)
        if not chosen:
            return
        self.settings.folder = str(Path(chosen))
        self.folder_edit.setText(self.settings.folder)
        self._persist()
        self.backend.configure(self.settings.folder, self.settings.port)
        self._show_folder_check()
        self._update()

    def _show_folder_check(self) -> None:
        if not self.settings.folder:
            self.folder_note.setText("No folder chosen yet.")
            return
        check = managed.check_folder(self.settings.folder)
        if check.ok:
            self.folder_note.setText("Morphorum" + (f" {check.version}" if check.version else "") + " found.")
        else:
            self.folder_note.setText(" ".join(check.problems))

    def _open(self) -> None:
        if self.settings.folder and Path(self.settings.folder).is_dir():
            self._open_folder(self.settings.folder)

    def _port_changed(self, value: int) -> None:
        if self.backend.owned:
            return
        self.settings.port = int(value)
        self._persist()
        self.backend.configure(self.settings.folder, self.settings.port)
        self._update()

    def _autostart_changed(self, checked: bool) -> None:
        self.settings.autostart = bool(checked)
        self._persist()

    def _exit_setting_changed(self, checked: bool) -> None:
        self.settings.stop_on_exit = bool(checked)
        self._persist()

    # ---- start / stop -----------------------------------------------------------------

    def start(self) -> None:
        self._notice = ""
        if self.backend.owned or (self._issuer is not None and self._issuer.busy):
            return
        if self.backend.state == mb.ADOPTED:
            self._connect_when_ready = True
            self._prepare_credential(then=self._backend_ready)
            return
        check = managed.check_folder(self.settings.folder)
        if not check.ok:
            self._show_folder_check()
            return
        self._connect_when_ready = True
        self._prepare_credential(then=self.backend.start)

    def _prepare_credential(self, then: Callable[[], object]) -> None:
        """Make sure Studio holds a credential for the managed backend, then continue."""
        try:
            profile = self.connections.ensure_managed_profile(managed.loopback_url(self.settings.port))
            if profile.id != self.settings.profile_id:
                self.settings.profile_id = profile.id
                self._persist()
            have = bool(self.vault.get(profile.id))
        except Exception as exc:  # keyring, disk or URL validation problems; shown, never raised
            self._say(f"Could not prepare the connection: {exc}")
            self._startup_finish(False, f"Could not prepare the connection: {exc}")
            return
        if have:
            then()
            return
        self._say("Creating a Studio credential for this backend…")
        self.start_button.setEnabled(False)
        issuer = self._issuer_factory(self.settings.folder)
        self._issuer = issuer
        issuer.done.connect(lambda token, message, profile_id=profile.id: self._credential_done(
            profile_id, token, message, then))
        issuer.issue()

    def _credential_done(self, profile_id: str, token, message: str, then: Callable[[], object]) -> None:
        issuer, self._issuer = self._issuer, None
        if issuer is not None:
            issuer.deleteLater()
        if token is None:
            self._say(message or "A credential could not be created.")
            self._startup_finish(False, message or "A credential could not be created.")
            return
        try:
            self.vault.set(profile_id, token)
        except (ValueError, RuntimeError) as exc:
            self._say(str(exc))
            self._startup_finish(False, str(exc))
            return
        self._notice = ""
        self._update()
        then()

    def _backend_ready(self) -> None:
        if self._connect_when_ready:
            self._connect_when_ready = False
            if self._starting_up:
                self._startup_connecting = True
                self.startup_progress.emit("Connecting to the local backend…")
            if not self.connections.connect_managed() and self._starting_up:
                self._startup_finish(False, "Studio could not start the connection.")

    def stop(self) -> None:
        self._restart = False
        self._stop()

    def _stop(self) -> bool:
        if not self.backend.owned:
            return False
        jobs = self._active_jobs()
        if jobs:
            answer = QMessageBox.question(
                self, "Stop the backend?",
                f"{jobs} job(s) are still running on this backend. Stopping it will interrupt them. Stop anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self._connect_when_ready = False
        self._disconnect_if_managed()
        return self.backend.stop()

    def restart(self) -> None:
        self._restart = False
        if self._stop():
            self._restart = True  # starts again once the old process has finished

    def reset_credential(self) -> None:
        """Replace Studio's credential for the managed backend with a freshly issued one."""
        profile = self.connections.managed_profile()
        if profile is None or not self.settings.folder or (self._issuer is not None and self._issuer.busy):
            return
        try:
            self.vault.delete(profile.id)
        except RuntimeError as exc:
            self._say(str(exc))
            return
        self._disconnect_if_managed()
        again = self.backend.running
        self._connect_when_ready = again
        self._prepare_credential(then=self._backend_ready if again else self._update)

    # ---- opening Studio ---------------------------------------------------------------

    def startup_wanted(self, last_profile_id: str) -> bool:
        """True when the backend Studio used last was the managed one and starting it is allowed."""
        profile = self.connections.managed_profile()
        return bool(self.settings.autostart and profile is not None and profile.id == last_profile_id
                    and managed.check_folder(self.settings.folder).ok)

    def begin_startup(self) -> None:
        """Bring the managed backend up (if it is not already) and connect, reporting through ``startup_done``."""
        if self._starting_up:
            return
        self._starting_up, self._startup_connecting = True, False
        self.backend.refresh()
        state = self.backend.state
        if state in (mb.STOPPED, mb.CRASHED, mb.ADOPTED):
            self.startup_progress.emit("Checking the local backend…" if state == mb.ADOPTED
                                       else "Starting the local backend…")
            self.start()
            if not self._starting_up:
                return
            if self._issuer is not None and self._issuer.busy:
                self.startup_progress.emit("Preparing the backend credential…")
        elif state == mb.RUNNING:
            self._connect_when_ready = True
            self._backend_ready()
        else:
            self._startup_finish(False, self.backend.detail)

    def _startup_finish(self, ok: bool, reason: str = "") -> None:
        if not self._starting_up:
            return
        self._starting_up = self._startup_connecting = False
        if not ok and reason:
            self._notice = reason
            self._update()
        self.startup_done.emit(ok, reason)

    # ---- state ------------------------------------------------------------------------

    def _disconnect_if_managed(self) -> None:
        info = self.session.info
        profile = self.connections.managed_profile()
        if profile is not None and info is not None and info.profile_id == profile.id:
            self.connections.disconnect()

    def _say(self, text: str) -> None:
        self._notice = text
        self._update()

    def _state_changed(self, state: str, detail: str) -> None:
        self._notice = ""
        if self._starting_up and state in (mb.CRASHED, mb.ERROR, mb.PORT_BUSY):
            self._startup_finish(False, detail)
        if state in (mb.STOPPING, mb.STOPPED, mb.CRASHED, mb.ERROR):
            self._disconnect_if_managed()
        if state in (mb.STOPPING, mb.CRASHED, mb.ERROR):
            self._connect_when_ready = False
        if state == mb.STOPPED and self._restart:
            self._restart = False
            self.start()
        self._update()

    def _connection_changed(self, text: str) -> None:
        profile = self.connections.managed_profile()
        info = self.session.info
        mine = profile is not None and info is not None and info.profile_id == profile.id
        if self._starting_up:
            if text == "BACKEND CONNECTED" and mine:
                self._startup_finish(True)
            elif text in ("BACKEND UNAUTHORIZED", "BACKEND INCOMPATIBLE", "BACKEND IDENTITY MISMATCH") or \
                    (text == "BACKEND OFFLINE" and self._startup_connecting):
                self._startup_finish(False, CONNECTION_TEXT.get(text, "The connection failed."))
        if text == "BACKEND CONNECTED" and not mine:
            self.connection_line.setText("")
        else:
            self.connection_line.setText(CONNECTION_TEXT.get(text, ""))
        self._update()

    def _update(self) -> None:
        state = self.backend.state
        label, kind = STATE_CHIP.get(state, (state, "idle"))
        self.chip.setText(label)
        self.chip.setProperty("state", kind)
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        self.detail.setText(self._notice or self.backend.detail)
        owned, ready = self.backend.owned, managed.check_folder(self.settings.folder).ok
        busy_credential = self._issuer is not None and self._issuer.busy
        can_start = ready and state in (mb.STOPPED, mb.CRASHED, mb.ERROR, mb.ADOPTED) and not busy_credential
        self.start_button.setText("Connect" if state == mb.ADOPTED else "Start and connect")
        self.start_button.setEnabled(can_start and (state != mb.ERROR or ready))
        self.stop_button.setEnabled(owned and state in (mb.STARTING, mb.RUNNING))
        self.restart_button.setEnabled(owned and state == mb.RUNNING)
        self.choose_button.setEnabled(not owned)
        self.port.setEnabled(not owned)
        self.open_button.setEnabled(bool(self.settings.folder) and Path(self.settings.folder).is_dir())
        self.reset_button.setEnabled(ready and not busy_credential)

    # ---- closing Studio -----------------------------------------------------------------

    def _ask_exit_dialog(self, jobs: int) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Local backend is busy")
        box.setText(f"{jobs} job(s) are still running on the backend Studio started.")
        stop = box.addButton("Stop it and close", QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton("Keep it running and close", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        return "stop" if clicked is stop else "keep" if clicked is keep else "cancel"

    def close_requested(self) -> bool:
        """Called when Studio is closing. False means the person cancelled the close."""
        if not self.backend.owned:
            return True
        if not self.settings.stop_on_exit:
            return True  # left running on purpose; the next session recognises it
        jobs = self._active_jobs()
        choice = self._ask_exit(jobs) if jobs else "stop"
        if choice == "cancel":
            return False
        if choice == "stop":
            self._disconnect_if_managed()
            self.backend.shutdown()
        return True
