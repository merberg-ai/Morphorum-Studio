"""Simple connection mode: Studio runs a Morphorum backend on this PC and connects to it.

The panel manages a Morphorum folder: it can install one (by running the backend's own
installer after the person agrees), start and stop it, and connect to it. The panel never
offers a control it cannot honour. Studio stops only a backend it started itself, and the
credential it uses is a revocable client token kept in the OS keyring.
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
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend import maintenance as mt
from morphorum_studio.backend import managed
from morphorum_studio.backend.credentials import CredentialStore
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui import managed_backend as mb
from morphorum_studio.ui import managed_install as mi
from morphorum_studio.ui import managed_maintenance as mm
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
                 installer: mi.InstallDriver | None = None,
                 confirm_close_install: Callable[[], bool] | None = None,
                 confirm_lan: Callable[[], bool] | None = None,
                 maintenance: mm.MaintenanceDriver | None = None,
                 confirm_remove: Callable[[str, list[str]], bool] | None = None,
                 lan_address: Callable[[int], str] = managed.lan_address,
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
        self.installer = installer or mi.InstallDriver()
        self._confirm_close_install = confirm_close_install or self._confirm_close_install_dialog
        self._confirm_lan = confirm_lan or self._confirm_lan_dialog
        self._lan_address = lan_address
        self.maintenance = maintenance or mm.MaintenanceDriver()
        self._confirm_remove = confirm_remove or self._confirm_remove_dialog
        self.git_status: mt.GitStatus | None = None
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
        backend.restart_scheduled.connect(lambda _attempt, _delay: setattr(self, "_connect_when_ready", True))
        connections.status_changed.connect(self._connection_changed)
        self.installer.log_line.connect(self._append_log)
        self.installer.stage.connect(self._install_stage)
        self.installer.state_changed.connect(self._install_state)
        self.installer.finished.connect(self._install_finished)
        self.maintenance.log_line.connect(self._append_log)
        self.maintenance.busy_changed.connect(lambda _busy: self._update())
        self.maintenance.checked.connect(self._checked)
        self.maintenance.finished.connect(self._maintenance_finished)
        self.session.changed.connect(self._update)
        self.folder_edit.setText(self.settings.folder)
        for widget, apply in ((self.port, lambda: self.port.setValue(self.settings.port)),
                              (self.autostart, lambda: self.autostart.setChecked(self.settings.autostart)),
                              (self.stop_on_exit, lambda: self.stop_on_exit.setChecked(self.settings.stop_on_exit)),
                              (self.auto_restart, lambda: self.auto_restart.setChecked(self.settings.auto_restart)),
                              (self.lan, lambda: self.lan.setChecked(self.settings.lan))):
            widget.blockSignals(True)  # showing saved values is not a change to save
            apply()
            widget.blockSignals(False)
        backend.auto_restart = self.settings.auto_restart
        backend.configure(self.settings.folder, self.settings.port, self.settings.lan)
        self._lan_hint()
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
            "Studio runs Morphorum on this PC and connects to it. Choose the folder where Morphorum is "
            "installed, or let Studio install it for you.", "pageDescription"))

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
        self.auto_restart = QCheckBox("Start the backend again if it stops unexpectedly")
        self.auto_restart.setToolTip("Up to three tries, then Studio stops and tells you.")
        self.auto_restart.toggled.connect(self._auto_restart_changed)
        box.addWidget(self.auto_restart)
        self.lan = QCheckBox("Let other computers on my network connect")
        self.lan.toggled.connect(self._lan_changed)
        box.addWidget(self.lan)
        self.lan_note = _label("", "hint")
        box.addWidget(self.lan_note)
        box.addWidget(_label("Studio stops only a backend that Studio started.", "hint"))
        layout.addWidget(folder_card)

        self.install_card, ibox = self._card("Install Morphorum")
        ibox.addWidget(_label(
            "Studio will run Morphorum's own installer and put everything in the folder above. "
            "Nothing is changed outside it, except that Git and FFmpeg are installed for Windows "
            "with winget if they are missing.", "hint"))
        for text in (
            f"Downloads the installer from github.com/{managed.REPO} (branch {managed.DEFAULT_BRANCH}).",
            "Downloads the Morphorum source and a Python environment with PyTorch (several GB).",
            f"Needs at least {managed.MIN_FREE_BYTES // 1024**3} GiB free and usually takes 10 to 30 minutes.",
            "You can cancel at any time and continue later."):
            ibox.addWidget(_label("•  " + text, "hint"))
        self.consent = QCheckBox("I agree to install Morphorum into this folder")
        self.consent.toggled.connect(lambda _checked: self._update())
        ibox.addWidget(self.consent)
        self.install_note = _label("", "hint")
        ibox.addWidget(self.install_note)
        self.install_stage = _label("", "connectionDetails")
        ibox.addWidget(self.install_stage)
        self.install_bar = QProgressBar()
        self.install_bar.setRange(0, 0)
        self.install_bar.setTextVisible(False)
        self.install_bar.setMaximumHeight(8)
        self.install_bar.setVisible(False)
        ibox.addWidget(self.install_bar)
        irow = QHBoxLayout()
        irow.setSpacing(10)
        irow.addStretch(1)
        self.cancel_install_button = self._fixed(QPushButton("Cancel install"), 120)
        self.cancel_install_button.setObjectName("dangerAction")
        self.cancel_install_button.clicked.connect(self.cancel_install)
        self.install_button = self._fixed(QPushButton("Install Morphorum"), 160)
        self.install_button.setObjectName("primaryAction")
        self.install_button.clicked.connect(self.install)
        irow.addWidget(self.cancel_install_button)
        irow.addWidget(self.install_button)
        ibox.addLayout(irow)
        layout.addWidget(self.install_card)

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
        self.port_button = self._fixed(QPushButton("Use a free port"), 130)
        self.port_button.setToolTip("Switch Studio's backend to the next port nothing is using")
        self.port_button.clicked.connect(self.use_free_port)
        self.start_button = self._fixed(QPushButton("Start and connect"), 150)
        self.start_button.setObjectName("primaryAction")
        self.start_button.clicked.connect(self.start)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        for button in (self.port_button, self.restart_button, self.stop_button, self.start_button):
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

        self.maint_card, mbox = self._card("Maintenance")
        self.install_info = _label("", "connectionDetails")
        mbox.addWidget(self.install_info)
        self.maint_note = _label("", "hint")
        mbox.addWidget(self.maint_note)
        mbox.addWidget(_label(
            "Updating, switching branch and repairing run Morphorum's own scripts. They refuse to run "
            "over your local changes, keep a backup, and need the backend to be stopped.", "hint"))
        mrow = QHBoxLayout()
        mrow.setSpacing(10)
        self.check_button = self._fixed(QPushButton("Check for updates"), 150)
        self.check_button.clicked.connect(self.check_for_updates)
        self.update_button = self._fixed(QPushButton("Update"), 90)
        self.update_button.setObjectName("primaryAction")
        self.update_button.clicked.connect(self.update_backend)
        self.doctor_button = self._fixed(QPushButton("Health check"), 120)
        self.doctor_button.clicked.connect(self.health_check)
        self.repair_button = self._fixed(QPushButton("Repair"), 90)
        self.repair_button.clicked.connect(self.repair)
        self.cancel_maint_button = self._fixed(QPushButton("Cancel"), 90)
        self.cancel_maint_button.setObjectName("dangerAction")
        self.cancel_maint_button.clicked.connect(self.maintenance.cancel)
        for button in (self.check_button, self.update_button, self.doctor_button, self.repair_button,
                       self.cancel_maint_button):
            mrow.addWidget(button)
        mrow.addStretch(1)
        mbox.addLayout(mrow)
        brow = QHBoxLayout()
        brow.setSpacing(10)
        brow.addWidget(_label("Branch", "fieldLabel", wrap=False))
        self.branch_box = QComboBox()
        self.branch_box.setAccessibleName("Backend branch")
        self.branch_box.setMinimumWidth(200)
        brow.addWidget(self.branch_box)
        self.switch_button = self._fixed(QPushButton("Switch branch"), 130)
        self.switch_button.clicked.connect(self.switch_branch)
        brow.addWidget(self.switch_button)
        brow.addStretch(1)
        mbox.addLayout(brow)
        self.branch_note = _label("Run “Check for updates” to list the branches on GitHub.", "hint")
        mbox.addWidget(self.branch_note)
        rrow = QHBoxLayout()
        rrow.addStretch(1)
        self.remove_button = self._fixed(QPushButton("Remove Morphorum…"), 170)
        self.remove_button.setObjectName("dangerAction")
        self.remove_button.clicked.connect(self.remove_folder)
        rrow.addWidget(self.remove_button)
        mbox.addLayout(rrow)
        layout.addWidget(self.maint_card)

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
        self._lan_hint()
        self._update()

    def use_free_port(self) -> None:
        """The port is taken by another program: move Studio's backend to the next free one."""
        if self.backend.owned or self.backend.state != mb.PORT_BUSY:
            return
        free = managed.free_port(self.settings.port + 1)
        if free is None:
            self._say("No free port was found near this one. Choose a port by hand.")
            return
        old = self.settings.port
        self.port.setValue(free)  # saves, re-checks and re-points the connection on the next start
        self._say(f"Port {old} is in use, so Studio will use port {free}.")

    def _auto_restart_changed(self, checked: bool) -> None:
        self.settings.auto_restart = bool(checked)
        self.backend.auto_restart = bool(checked)
        self._persist()

    def _confirm_lan_dialog(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Allow other computers?")
        box.setText(managed.LAN_WARNING)
        allow = box.addButton("Allow my network", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Keep it on this PC", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is allow

    def _lan_changed(self, checked: bool) -> None:
        if checked and not self._confirm_lan():
            self.lan.blockSignals(True)
            self.lan.setChecked(False)
            self.lan.blockSignals(False)
            return
        self.settings.lan = bool(checked)
        self._persist()
        self.backend.configure(self.settings.folder, self.settings.port, self.settings.lan)
        self._lan_hint()
        self._update()

    def _lan_hint(self) -> None:
        if not self.settings.lan:
            self.lan_note.setText("The backend listens on this PC only.")
            return
        address = self._lan_address(self.settings.port)
        where = f"Other computers can use {address}" if address else "Other computers can connect to this PC's address"
        self.lan_note.setText(
            f"{where} with a credential of their own (create one with the backend's `clients issue` command). "
            "Not encrypted: trusted networks only. Applies the next time Studio starts the backend.")

    def _autostart_changed(self, checked: bool) -> None:
        self.settings.autostart = bool(checked)
        self._persist()

    def _exit_setting_changed(self, checked: bool) -> None:
        self.settings.stop_on_exit = bool(checked)
        self._persist()

    # ---- start / stop -----------------------------------------------------------------

    def start(self) -> None:
        self._notice = ""
        self.backend.reset_restarts()
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

    # ---- install ----------------------------------------------------------------------

    def _install_target(self) -> str:
        return self.settings.folder or str(managed.default_folder())

    def _resuming(self) -> bool:
        folder = self._install_target()
        return Path(folder).is_dir() and managed.is_checkout(folder) and not managed.check_folder(folder).ok

    def install(self) -> None:
        """Run the backend's installer. Only reachable once the person has ticked the consent box."""
        if self.installer.busy or self.backend.owned or not self.consent.isChecked():
            return
        folder = self._install_target()
        check = self.installer._check(folder, self.settings.port)
        if not check.ok:
            self.install_note.setText(" ".join(check.problems))
            return
        if folder != self.settings.folder:  # nothing was chosen: the default folder
            self.settings.folder = folder
            self.folder_edit.setText(folder)
            self._persist()
            self.backend.configure(folder, self.settings.port)
        self.install_note.setText(" ".join(check.warnings))
        self.install_stage.setText("")
        self.log_toggle.setChecked(True)
        self.log.clear()
        self.installer.start(folder, managed.DEFAULT_BRANCH, self.settings.port)
        self._update()

    def cancel_install(self) -> None:
        self.installer.cancel()

    def _install_stage(self, section: str) -> None:
        self.install_stage.setText(section)

    def _install_state(self, state: str, detail: str) -> None:
        if state in (mi.DOWNLOADING, mi.RUNNING):
            self.install_stage.setText(detail if not self.installer.section else self.installer.section)
        self._update()

    def _install_finished(self, ok: bool, message: str) -> None:
        self.consent.setChecked(False)
        self.backend.configure(self.settings.folder, self.settings.port)
        self._show_folder_check()
        if ok:
            self._notice = ""
            self.install_stage.setText("")
            self.start()  # install, then run it and connect
        else:
            self.install_stage.setText(message)
            self._update()

    def _confirm_close_install_dialog(self) -> bool:
        answer = QMessageBox.question(
            self, "Installation is running",
            "Morphorum is still installing. Cancel the installation and close Studio? "
            "Installing again later continues where it stopped.",
        )
        return answer == QMessageBox.StandardButton.Yes

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

    # ---- maintenance ----------------------------------------------------------------

    def _maintenance_ok(self) -> bool:
        """Scripts that change the folder run only with the backend stopped and nothing else running."""
        return managed.check_folder(self.settings.folder).ok and not self.maintenance.busy \
            and not self.installer.busy and self.backend.state in (mb.STOPPED, mb.CRASHED, mb.ERROR, mb.PORT_BUSY)

    def check_for_updates(self) -> None:
        if self.settings.folder and not self.maintenance.busy:
            self.maint_note.setText("Checking GitHub…")
            self.maintenance.check_for_updates(self.settings.folder)

    def _checked(self, status: mt.GitStatus) -> None:
        self.git_status = status
        if status.error:
            self.maint_note.setText(status.error)
        elif status.behind:
            self.maint_note.setText(f"{status.behind} update(s) available on branch {status.branch}.")
        elif status.ahead:
            self.maint_note.setText(f"Up to date with GitHub (this copy has {status.ahead} extra local commit(s)).")
        else:
            self.maint_note.setText(f"Up to date on branch {status.branch}.")
        if status.dirty:
            self.maint_note.setText(self.maint_note.text() + " Local changes in the folder will stop an update.")
        self.branch_box.clear()
        self.branch_box.addItems(list(status.branches))
        if status.branch in status.branches:
            self.branch_box.setCurrentText(status.branch)
        self.branch_note.setText("Switching branch changes the backend's code; it is not for everyday use."
                                 if status.branches else "No branches were listed.")
        self._update()

    def update_backend(self) -> None:
        if self._maintenance_ok() and self.git_status is not None and self.git_status.update_available \
                and not self.git_status.dirty:
            self._run_maintenance(lambda: self.maintenance.update(self.settings.folder))

    def switch_branch(self) -> None:
        branch = self.branch_box.currentText()
        status = self.git_status
        if self._maintenance_ok() and branch and status is not None and branch != status.branch \
                and not status.dirty:
            self._run_maintenance(lambda: self.maintenance.update(self.settings.folder, branch))

    def repair(self) -> None:
        if self._maintenance_ok():
            self._run_maintenance(lambda: self.maintenance.repair(self.settings.folder))

    def health_check(self) -> None:
        if self._maintenance_ok():
            self._run_maintenance(lambda: self.maintenance.health_check(self.settings.folder))

    def _run_maintenance(self, start: Callable[[], bool]) -> None:
        self.log_toggle.setChecked(True)
        self.maint_note.setText("Working… the output is shown under Backend output.")
        if not start():
            self.maint_note.setText("That could not be started.")

    def _maintenance_finished(self, job: str, ok: bool, message: str) -> None:
        if job == mm.REMOVE:
            self._removed(ok, message)
            return
        if job == mm.CHECK:
            return
        self.maint_note.setText(message)
        if job in (mm.UPDATE, mm.SWITCH, mm.REPAIR):
            self.git_status = None  # what was true before no longer is
            if ok:
                self.check_for_updates()
        self._update()

    def _confirm_remove_dialog(self, name: str, personal: list[str]) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Remove Morphorum")
        layout = QVBoxLayout(dialog)
        text = f"This permanently deletes the folder “{self.settings.folder}” and everything in it."
        if personal:
            text += "\n\nIt contains " + ", ".join(personal) + ". Those cannot be recovered."
        text += "\n\nStudio will also forget its connection and credential for it. Type the folder name to confirm."
        layout.addWidget(_label(text, "hint"))
        edit = QLineEdit()
        edit.setPlaceholderText(name)
        layout.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        remove = buttons.addButton("Remove permanently", QDialogButtonBox.ButtonRole.DestructiveRole)
        remove.setEnabled(False)
        edit.textChanged.connect(lambda value: remove.setEnabled(value.strip() == name))
        buttons.rejected.connect(dialog.reject)
        remove.clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def remove_folder(self) -> None:
        folder = self.settings.folder
        if not folder or self.maintenance.busy or self.installer.busy or self.backend.state not in (
                mb.STOPPED, mb.CRASHED, mb.ERROR, mb.PORT_BUSY, mb.UNCONFIGURED):
            return
        problems = mt.removal_problems(folder)
        if problems:
            self.maint_note.setText(" ".join(problems))
            return
        if not self._confirm_remove(Path(folder).name, mt.personal_contents(folder)):
            return
        self.log_toggle.setChecked(True)
        self.maint_note.setText("Removing…")
        if not self.maintenance.remove(folder):
            self.maint_note.setText("The folder could not be removed.")

    def _removed(self, ok: bool, message: str) -> None:
        self.maint_note.setText(message)
        if ok:
            self._disconnect_if_managed()
            kept = self.connections.remove_managed_profile()
            self.settings.folder, self.settings.profile_id = "", ""
            self.folder_edit.setText("")
            self.git_status = None
            self.branch_box.clear()
            self.backend.configure("", self.settings.port, self.settings.lan)
            self._persist()
            self._show_folder_check()
            if not kept:
                self.maint_note.setText(message + " Studio could not forget the saved credential; "
                                                  "remove it from Connections.")
        self._update()

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
        can_start = ready and state in (mb.STOPPED, mb.CRASHED, mb.ERROR, mb.ADOPTED) and not busy_credential \
            and not self.installer.busy
        self.start_button.setText("Connect" if state == mb.ADOPTED else "Start and connect")
        self.start_button.setEnabled(can_start and (state != mb.ERROR or ready))
        self.stop_button.setEnabled(owned and state in (mb.STARTING, mb.RUNNING))
        self.restart_button.setEnabled(owned and state == mb.RUNNING)
        installing = self.installer.busy
        self.choose_button.setEnabled(not owned and not installing)
        self.port.setEnabled(not owned and not installing)
        self.install_card.setVisible(installing or not ready)
        resuming = self._resuming()
        self.install_button.setText("Resume install" if resuming else "Install Morphorum")
        self.install_button.setEnabled(self.consent.isChecked() and not installing and not owned)
        self.consent.setEnabled(not installing)
        self.cancel_install_button.setVisible(installing)
        self.install_button.setVisible(not installing)
        self.install_bar.setVisible(installing)

        self.open_button.setEnabled(bool(self.settings.folder) and Path(self.settings.folder).is_dir())
        self.reset_button.setEnabled(ready and not busy_credential)
        self.port_button.setVisible(state == mb.PORT_BUSY)
        self.port_button.setEnabled(state == mb.PORT_BUSY and not installing)
        self.lan.setEnabled(not owned and not installing)
        self.auto_restart.setEnabled(not installing)

        self.maint_card.setVisible(ready or bool(self.settings.folder) and Path(self.settings.folder).is_dir())
        self.install_info.setText(mt.describe_install(self.settings.folder) if ready else "")
        idle = self._maintenance_ok()
        status = self.git_status
        self.check_button.setEnabled(ready and not self.maintenance.busy and not installing)
        self.update_button.setEnabled(idle and status is not None and status.update_available and not status.dirty)
        self.switch_button.setEnabled(idle and status is not None and not status.dirty and bool(
            self.branch_box.currentText()) and self.branch_box.currentText() != status.branch)
        self.doctor_button.setEnabled(idle)
        self.repair_button.setEnabled(idle)
        self.branch_box.setEnabled(idle and status is not None)
        self.cancel_maint_button.setVisible(self.maintenance.busy and self.maintenance.job in (
            mm.UPDATE, mm.SWITCH, mm.REPAIR))
        self.remove_button.setEnabled(bool(self.settings.folder) and not self.maintenance.busy and not installing
                                      and state in (mb.STOPPED, mb.CRASHED, mb.ERROR, mb.PORT_BUSY, mb.UNCONFIGURED))

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
        if self.installer.busy:
            if not self._confirm_close_install():
                return False
            self.installer.cancel()
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
