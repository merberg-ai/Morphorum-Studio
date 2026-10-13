"""Native S1.2 connection panel with explicit trust and off-thread discovery."""
from __future__ import annotations

from urllib.parse import urlsplit
from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget, QFileDialog
)

from morphorum_studio.backend.client import BackendError, normalize_base_url
from morphorum_studio.backend.credentials import CredentialStore
from morphorum_studio.backend.profiles import ConnectionProfile, ProfileStore
from morphorum_studio.backend.session import BackendSession, SessionInfo
from morphorum_studio.backend.worker import DiscoveryWorker
from morphorum_studio.ui.preferences import StudioPreferences

# While connected, these failures usually mean the backend is restarting or briefly
# overloaded, so the monitor keeps retrying quietly. Anything else (rejected credentials,
# incompatible API, wrong server) stops monitoring and asks the user to act.
TRANSIENT_ERRORS = frozenset({
    "NETWORK_ERROR", "CONNECTION_ERROR", "HTTP_ERROR", "RATE_LIMITED", "INVALID_RESPONSE",
})


class ConnectionsPanel(QWidget):
    status_changed = Signal(str)
    profile_selected = Signal(str)
    connection_succeeded = Signal(str)

    def __init__(self, parent=None, profile_store=None, credential_store=None, preferences=None,
                 session=None):
        super().__init__(parent)
        # Shared, read-only view of this connection for the other pages (see backend/session.py).
        self.session = session if session is not None else BackendSession(self)
        self._probe_token = None
        self.store = profile_store or ProfileStore()
        self.vault = credential_store or CredentialStore()
        self.preferences = preferences or StudioPreferences()
        loaded = self.store.load_recovering()
        self.profiles = loaded.profiles
        self._load_warning = loaded.warning
        self._connecting = False  # A user-started or startup connect is in flight.
        self._monitor_inflight = False  # A background health probe is in flight.
        self._restart_notice = False
        self._worker = None
        self._epoch = 0
        self._connected_profile = None
        self._retry_count = 0
        self._monitor = QTimer(self)
        self._monitor.setInterval(15000)
        self._monitor.timeout.connect(self._monitor_tick)
        self._build_ui()
        self.import_button.clicked.connect(self.import_token_file)
        self.new_button.clicked.connect(self.new_profile)
        self.save_button.clicked.connect(self.save_profile)
        self.remove_button.clicked.connect(self.remove_profile)
        self.test_button.clicked.connect(self.connect_profile)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.url.textChanged.connect(self._url_edited)
        self.refresh()
        if self._load_warning:
            self.details.setText(self._load_warning)

    # ---- layout -------------------------------------------------------------------

    @staticmethod
    def _fixed(button: QPushButton, min_width: int = 0) -> QPushButton:
        """Buttons keep their natural size instead of stretching across the card."""
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if min_width:
            button.setMinimumWidth(min_width)
        return button

    @staticmethod
    def _label(text: str, name: str, wrap: bool = True) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(wrap)
        return label

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(self._label(title, "cardTitle", wrap=False))
        return card, layout

    def _field(self, caption: str, widget: QWidget, hint: str = "") -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(self._label(caption, "fieldLabel", wrap=False))
        box.addWidget(widget)
        if hint:
            box.addWidget(self._label(hint, "hint"))
        return box

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("connectionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("connectionsContent")
        scroll.setWidget(content)
        page = QVBoxLayout(content)
        page.setContentsMargins(38, 34, 38, 28)
        column = QWidget()
        column.setMaximumWidth(780)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        page.addWidget(column, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        page.addStretch(1)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(self._label("BACKEND CONNECTIONS / STUDIO", "sectionCaption", wrap=False))
        layout.addWidget(self._label("Backend connection", "pageHeading", wrap=False))
        layout.addWidget(self._label(
            "Connect to an existing Morphorum GPU backend. No local GPU needed.",
            "pageDescription",
        ))

        # -- Backend card: which server, and the actions that act on it.
        backend, box = self._card("Backend")
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.select_profile)
        self.new_button = self._fixed(QPushButton("New"), 72)
        picker = QHBoxLayout()
        picker.setSpacing(10)
        picker.addLayout(self._field("Saved profile", self.selector), 1)
        picker.addWidget(self.new_button, 0, Qt.AlignmentFlag.AlignBottom)
        box.addLayout(picker)

        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Workshop GPU")
        self.url = QLineEdit()
        self.url.setPlaceholderText("http://127.0.0.1:7866")
        box.addLayout(self._field("Profile name", self.name))
        box.addLayout(self._field("Backend URL", self.url))

        self.save_button = self._fixed(QPushButton("Save profile"), 110)
        self.remove_button = self._fixed(QPushButton("Remove"), 90)
        self.remove_button.setObjectName("dangerAction")
        self.disconnect_button = self._fixed(QPushButton("Disconnect"), 100)
        self.test_button = self._fixed(QPushButton("Connect / Test"), 130)
        self.test_button.setObjectName("primaryAction")
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        actions.addWidget(self.disconnect_button)
        actions.addWidget(self.test_button)
        box.addLayout(actions)
        layout.addWidget(backend)

        # -- Credential card. Provisioning is local: reading/saving a token does not transmit it.
        credential, cbox = self._card("Client credential")
        self.credential_status = self._label("No token imported for this session.", "hint")
        self.import_button = self._fixed(QPushButton("Import token file…"), 150)
        self.import_button.setToolTip("Select a token file from this PC or a trusted mapped share")
        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        status_row.addWidget(self.credential_status, 1)
        status_row.addWidget(self.import_button)
        cbox.addLayout(status_row)

        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Paste a token (optional)")
        cbox.addLayout(self._field(
            "Bearer token", self.token,
            "Saved to the OS credential manager with the profile. Leave blank to keep the existing one.",
        ))

        self.trust_http = QCheckBox("Allow sending this credential over HTTP on my trusted LAN")
        cbox.addWidget(self.trust_http)
        cbox.addWidget(self._label(
            "Only for a private network you control. HTTP does not encrypt the token.", "hint"))

        self.help_toggle = QToolButton()
        self.help_toggle.setObjectName("linkButton")
        self.help_toggle.setCheckable(True)
        self.help_toggle.setText("▸  How do I get a token?")
        self.help_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        cbox.addWidget(self.help_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.help_panel = QWidget()
        hbox = QVBoxLayout(self.help_panel)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(8)
        hbox.addWidget(self._label(
            "1. On the GPU host, issue a client token with the command below.\n"
            "2. Transfer the token file securely or browse a trusted network share.\n"
            "3. Import it, then choose Connect / Test.",
            "hint",
        ))
        self.issue_command = QLineEdit(
            '.\\.venv\\Scripts\\python.exe -m morphorum clients issue '
            '"Morphorum Studio" --days 90 --out ".\\data\\studio-client.token"'
        )
        self.issue_command.setReadOnly(True)
        self.issue_command.setCursorPosition(0)
        self.issue_command.setToolTip("Run this in PowerShell inside the Morphorum backend checkout")
        self.copy_button = self._fixed(QPushButton("Copy"), 72)
        command_row = QHBoxLayout()
        command_row.setSpacing(10)
        command_row.addWidget(self.issue_command, 1)
        command_row.addWidget(self.copy_button)
        hbox.addLayout(command_row)
        self.help_panel.setVisible(False)
        cbox.addWidget(self.help_panel)
        layout.addWidget(credential)

        # -- Status
        status, sbox = self._card("Status")
        self.details = self._label("No backend connected.", "connectionDetails")
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sbox.addWidget(self.details)
        layout.addWidget(status)

        self.help_toggle.toggled.connect(self._toggle_help)
        self.copy_button.clicked.connect(self._copy_command)

    def _toggle_help(self, shown: bool) -> None:
        self.help_panel.setVisible(shown)
        self.help_toggle.setText(("▾" if shown else "▸") + "  How do I get a token?")

    def _copy_command(self) -> None:
        QApplication.clipboard().setText(self.issue_command.text())
        self.copy_button.setText("Copied")
        QTimer.singleShot(1500, lambda: self.copy_button.setText("Copy"))

    def _url_edited(self, text):
        """HTTP trust belongs to one exact URL: editing the address withdraws it."""
        profile = self.selected()
        saved = profile.url if profile else ""
        try:
            current = normalize_base_url(text)
        except BackendError:
            current = text.strip()
        if current != saved and self.trust_http.isChecked():
            self.trust_http.setChecked(False)

    def _blocked(self) -> bool:
        """True (with feedback) while a connection attempt is in progress."""
        if self._connecting:
            self.details.setText(
                "A connection attempt is in progress. Wait for it, or press Disconnect to cancel."
            )
            return True
        return False

    def refresh(self, selected=None):
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItem("New connection", None)
        for p in self.profiles:
            self.selector.addItem(p.name, p.id)
        if selected:
            index = self.selector.findData(selected)
            self.selector.setCurrentIndex(index if index >= 0 else 0)
        self.selector.blockSignals(False)
        self.select_profile(self.selector.currentIndex())

    def selected(self):
        key = self.selector.currentData()
        return next((p for p in self.profiles if p.id == key), None)

    def select_profile(self, index):
        if self._connected_profile is not None:
            self.disconnect()
        p = self.selected()
        self.profile_selected.emit(p.id if p else "")
        self.name.setText(p.name if p else "")
        self.url.setText(p.url if p else "")
        self.token.clear()
        self.trust_http.setChecked(bool(p and self.preferences.trusted_http(p.id, p.url)))
        try:
            has_token = bool(p and self.vault.get(p.id))
        except RuntimeError:
            has_token = False
        self.credential_status.setText(
            "Token stored in OS credential manager" if has_token
            else "No saved token for this profile"
        )

    def select_by_id(self, profile_id: str):
        index = self.selector.findData(profile_id)
        if index >= 0:
            self.selector.setCurrentIndex(index)
            return True
        return False

    def new_profile(self):
        if self._blocked():
            return
        self.selector.setCurrentIndex(0)
        self.disconnect()

    def save_profile(self):
        if self._blocked():
            return
        if self._connected_profile is not None:
            self.disconnect()
        try:
            url = normalize_base_url(self.url.text())
            name = self.name.text().strip()
            if not name:
                raise ValueError("Enter a profile name")
            p = self.selected()
            if p is None:
                p = ConnectionProfile.create(name, url)
                self.profiles.append(p)
            else:
                if p.url != url:
                    p.instance_id = ""
                    p.boot_id = ""
                p.name, p.url = name, url
            if self.token.text():
                self.vault.set(p.id, self.token.text())
            self.store.save(self.profiles)
            self.preferences.set_trusted_http(p.id, p.url, self.trust_http.isChecked())
            self.preferences.sync()
            self.refresh(p.id)
            self.details.setText("Profile saved. Choose Connect / Test.")
            self.status_changed.emit("BACKEND OFFLINE")
        except (ValueError, RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Could not save connection", str(exc))

    def import_token_file(self):
        """Read a small host-issued secret locally, then store only in OS keyring."""
        if self._blocked():
            return
        p = self.selected()
        if p is None:
            QMessageBox.information(self, "Save profile first",
                "Create and save a named connection before importing its token.")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import backend-issued token file", "", "Token files (*.token *.txt);;All files (*)")
        if not filename:
            return
        try:
            path = Path(filename)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
                raise ValueError("Token file must be a regular file smaller than 8 KiB")
            token = path.read_text(encoding="utf-8-sig").strip()
            if not token or len(token) > 4096 or any(c.isspace() for c in token):
                raise ValueError("File does not contain a valid single-line token")
            self.vault.set(p.id, token)
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Token import failed", str(exc))
            return
        self.token.clear()
        self.credential_status.setText("Token imported and securely saved for this profile")
        self.details.setText(
            "Token imported into OS credential storage. The source file was not deleted. "
            "Remove the transfer copy securely when no longer needed, then Connect / Test."
        )

    def remove_profile(self):
        if self._blocked():
            return
        p = self.selected()
        if p is None:
            return
        if QMessageBox.question(self, "Remove connection", f"Remove profile '{p.name}'?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.vault.delete(p.id)
            self.preferences.set_trusted_http(p.id, p.url, False)
            self.profiles.remove(p)
            self.store.save(self.profiles)
            self.refresh()
            self.disconnect()
        except (RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Remove failed", str(exc))

    def connect_profile(self, *, automatic=False):
        if self._connecting:
            return
        p = self.selected()
        if p is None:
            QMessageBox.information(self, "Save first", "Save a connection profile first.")
            return
        try:
            token = self.vault.get(p.id)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Credential store", str(exc))
            return
        if token and urlsplit(p.url).scheme == "http" and not self.preferences.trusted_http(p.id, p.url) and automatic:
            self.details.setText("Auto-connect paused: approve trusted HTTP in Connections and save the profile.")
            self.status_changed.emit("BACKEND OFFLINE")
            return
        if token and urlsplit(p.url).scheme == "http" and not self.trust_http.isChecked():
            answer = QMessageBox.warning(
                self, "Unencrypted connection",
                "HTTP does not encrypt bearer tokens. Only continue if this is a trusted "
                "private network or a protected tunnel. Allow this connection?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.trust_http.setChecked(True)
        self._probe(p, token, monitoring=False)

    def auto_connect(self, profile_id: str) -> bool:
        if not profile_id or not self.select_by_id(profile_id):
            return False
        if self._connecting:
            return False
        self.connect_profile(automatic=True)
        return True

    def _probe(self, profile, token, *, monitoring):
        self._epoch += 1  # Supersedes any older request, including a background probe.
        self._monitor_inflight = monitoring
        if not monitoring:
            self._connecting = True
            self.test_button.setEnabled(False)
            self.selector.setEnabled(False)
            self.details.setText("Connecting in background…")
            self.status_changed.emit("BACKEND CONNECTING")
        epoch = self._epoch
        self._probe_token = token
        worker = DiscoveryWorker(profile.url, token)
        self._worker = worker
        worker.signals.completed.connect(
            lambda result, error: self._discovery_done(
                profile.id, epoch, monitoring, result, error
            )
        )
        QThreadPool.globalInstance().start(worker)

    def _monitor_tick(self):
        if self._connecting or self._monitor_inflight or not self._connected_profile:
            return
        p = next((x for x in self.profiles if x.id == self._connected_profile), None)
        if p is None:
            self.disconnect()
            return
        try:
            token = self.vault.get(p.id)
        except RuntimeError:
            self._monitor.stop()
            self._connected_profile = None
            self.session.disconnected()
            self.details.setText("Credential store unavailable. Reconnect manually.")
            self.status_changed.emit("BACKEND OFFLINE")
            return
        self._probe(p, token, monitoring=True)

    def _discovery_done(self, profile_id, epoch, monitoring, result, error):
        if epoch != self._epoch:
            return  # Late response after disconnect or another request.
        if monitoring:
            self._monitor_inflight = False
        else:
            self._connecting = False
            self.test_button.setEnabled(True)
            self.selector.setEnabled(True)
        self._worker = None
        probe_token, self._probe_token = self._probe_token, None  # Held only for this attempt.
        if error:
            self._monitor.stop()
            self._connected_profile = None
            code, message = error
            if monitoring and code in TRANSIENT_ERRORS:
                self.session.reconnecting()
            else:
                self.session.disconnected()
            if code in ("AUTH_REQUIRED", "FORBIDDEN"):
                self.details.setText("Authentication rejected. Check or reimport client token.")
                self.status_changed.emit("BACKEND UNAUTHORIZED")
            elif code == "INCOMPATIBLE_API":
                self.details.setText("Incompatible backend API. Update backend or Studio.")
                self.status_changed.emit("BACKEND INCOMPATIBLE")
            elif monitoring and code in TRANSIENT_ERRORS:
                self._connected_profile = profile_id
                self._retry_count += 1
                self._monitor.setInterval(min(60000, 5000 * (2 ** min(self._retry_count, 4))))
                self._monitor.start()
                self.details.setText(
                    f"Backend unavailable ({code}). Retrying in background; server jobs are untouched."
                )
                self.status_changed.emit("BACKEND RECONNECTING")
            else:
                self.details.setText(f"{code}: {message}. Use Connect / Test to retry.")
                self.status_changed.emit("BACKEND OFFLINE")
            return
        p = next((x for x in self.profiles if x.id == profile_id), None)
        if p is None:
            self.disconnect()
            return
        if p.instance_id and p.instance_id != result.instance_id:
            # Pause health probes while the dialog is open so another mismatch dialog
            # cannot stack on top of this one; a successful accept restarts the monitor.
            self._monitor.stop()
            answer = QMessageBox.warning(
                self, "Backend identity changed",
                "This address now reports a DIFFERENT Morphorum installation. "
                "The instance ID is not a cryptographic trust anchor. "
                "Accept the new identity only after independently confirming the host.\n\n"
                f"Previously: {p.instance_id}\nNow: {result.instance_id}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._monitor.stop()
                self._connected_profile = None
                self.session.disconnected()
                self.status_changed.emit("BACKEND IDENTITY MISMATCH")
                self.details.setText("Identity mismatch rejected. Connection stopped.")
                return
        if p.boot_id and p.boot_id != result.boot_id:
            self._restart_notice = True  # Stays visible until the user disconnects.
        # Only touch the disk when the pinned identity actually changed; every health
        # probe used to rewrite the profile file.
        identity_changed = (p.instance_id, p.boot_id) != (result.instance_id, result.boot_id)
        p.instance_id = result.instance_id
        p.boot_id = result.boot_id
        save_note = ""
        if identity_changed:
            try:
                self.store.save(self.profiles)
            except OSError as exc:
                # The connection itself is fine; do not drop it over a failed save.
                save_note = f"\nConnected, but the profile could not be saved: {exc}"
        available = ", ".join(k for k, v in result.features.items() if v) or "none advertised"
        self.details.setText(
            f"Connected: {p.name} | backend {result.version} | mode {result.mode}\n"
            f"Instance: {result.instance_id}\nBoot: {result.boot_id}\n"
            f"Features enabled: {available}"
            + ("\nBackend restarted: refresh job state before continuing."
               if self._restart_notice else "")
            + save_note
        )
        newly_connected = self._connected_profile != p.id
        self._connected_profile = p.id
        self._publish_session(p, result, probe_token)
        self._retry_count = 0
        self._monitor.setInterval(15000)
        self._monitor.start()
        self.status_changed.emit("BACKEND CONNECTED")
        if newly_connected:
            self.connection_succeeded.emit(p.id)

    def _publish_session(self, profile, result, token=None):
        if token is None:
            try:
                token = self.vault.get(profile.id)
            except RuntimeError:
                token = None
        self.session.connected(SessionInfo(
            profile.id, profile.name, profile.url, result.version, result.mode,
            result.instance_id, result.boot_id, dict(result.features),
        ), token)

    def disconnect(self):
        self.session.disconnected()
        self._monitor.stop()
        self._connected_profile = None
        self._retry_count = 0
        self._restart_notice = False
        self._epoch += 1  # Ignore results from any in-flight background request.
        self._connecting = False
        self._monitor_inflight = False
        self.selector.setEnabled(True)
        self.test_button.setEnabled(True)
        self.details.setText("Disconnected from Studio (backend remains running).")
        self.status_changed.emit("BACKEND OFFLINE")

    def closeEvent(self, event):
        self.disconnect()
        super().closeEvent(event)
