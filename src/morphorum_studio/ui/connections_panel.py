"""Native S1.2 connection panel with explicit trust and off-thread discovery."""
from __future__ import annotations

from urllib.parse import urlsplit
from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QFileDialog
)

from morphorum_studio.backend.client import normalize_base_url
from morphorum_studio.backend.credentials import CredentialStore
from morphorum_studio.backend.profiles import ConnectionProfile, ProfileStore
from morphorum_studio.backend.worker import DiscoveryWorker


class ConnectionsPanel(QWidget):
    status_changed = Signal(str)

    def __init__(self, parent=None, profile_store=None, credential_store=None):
        super().__init__(parent)
        self.store = profile_store or ProfileStore()
        self.vault = credential_store or CredentialStore()
        self.profiles = self.store.load()
        self._busy = False
        self._worker = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("BACKEND CONNECTIONS / STUDIO"))
        layout.addWidget(QLabel("Connect to an existing Morphorum GPU backend. No local GPU needed."))
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.select_profile)
        layout.addWidget(self.selector)
        form = QFormLayout()
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("http://127.0.0.1:7866")
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Stored in OS credential manager; blank keeps existing")
        form.addRow("Profile name", self.name)
        form.addRow("Backend URL", self.url)
        form.addRow("Bearer token", self.token)
        layout.addLayout(form)
        self.import_button = QPushButton("Import Token File…")
        self.import_button.setToolTip("Import a backend-issued client token file into the OS credential store")
        layout.addWidget(self.import_button)
        guide = QLabel(
            "On the BACKEND host, issue a token with:\\n"
            '  .\\\\.venv\\\\Scripts\\\\python.exe -m morphorum clients issue "Studio PC" --days 90 --out ".\\\\data\\\\studio-client.token"\\n'
            "Transfer that file securely (USB or authenticated encrypted transfer), then import it here. "
            "Never put it in a repository or paste it into chat."
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)
        self.trust_http = QCheckBox("I trust this LAN/loopback or encrypted tunnel for HTTP credentials")
        layout.addWidget(self.trust_http)
        buttons = QHBoxLayout()
        self.new_button = QPushButton("New")
        self.save_button = QPushButton("Save profile")
        self.remove_button = QPushButton("Remove")
        self.test_button = QPushButton("Connect / Test")
        self.disconnect_button = QPushButton("Disconnect")
        for button in (self.new_button, self.save_button, self.remove_button,
                       self.test_button, self.disconnect_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.details = QLabel("No backend connected.")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        layout.addStretch()
        self.import_button.clicked.connect(self.import_token_file)
        self.new_button.clicked.connect(self.new_profile)
        self.save_button.clicked.connect(self.save_profile)
        self.remove_button.clicked.connect(self.remove_profile)
        self.test_button.clicked.connect(self.connect_profile)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.refresh()

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
        p = self.selected()
        self.name.setText(p.name if p else "")
        self.url.setText(p.url if p else "")
        self.token.clear()
        self.trust_http.setChecked(False)

    def new_profile(self):
        if self._busy:
            return
        self.selector.setCurrentIndex(0)
        self.disconnect()

    def save_profile(self):
        if self._busy:
            return
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
                if urlsplit(url).scheme == "http" and not self.trust_http.isChecked():
                    raise ValueError("Confirm trusted HTTP before storing/transmitting a token")
                self.vault.set(p.id, self.token.text())
            self.store.save(self.profiles)
            self.refresh(p.id)
            self.details.setText("Profile saved. Choose Connect / Test.")
            self.status_changed.emit("BACKEND OFFLINE")
        except (ValueError, RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Could not save connection", str(exc))

    def import_token_file(self):
        """Read a small host-issued secret locally, then store only in OS keyring."""
        if self._busy:
            return
        p = self.selected()
        if p is None:
            QMessageBox.information(self, "Save profile first",
                "Create and save a named connection before importing its token.")
            return
        if urlsplit(p.url).scheme == "http" and not self.trust_http.isChecked():
            QMessageBox.warning(self, "Trusted connection required",
                "Confirm this is a trusted LAN or encrypted tunnel before importing credentials.")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import backend-issued token file", "", "Token files (*.token *.txt);;All files (*)")
        if not filename:
            return
        try:
            path = Path(filename)
            if not path.is_file() or path.stat().st_size > 8192:
                raise ValueError("Token file must be a regular file smaller than 8 KiB")
            token = path.read_text(encoding="utf-8-sig").strip()
            if not token or len(token) > 4096 or any(c.isspace() for c in token):
                raise ValueError("File does not contain a valid single-line token")
            self.vault.set(p.id, token)
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Token import failed", str(exc))
            return
        self.token.clear()
        self.details.setText(
            "Token imported into OS credential storage. The source file was not deleted. "
            "Remove the transfer copy securely when no longer needed, then Connect / Test."
        )

    def remove_profile(self):
        if self._busy:
            return
        p = self.selected()
        if p is None:
            return
        if QMessageBox.question(self, "Remove connection", f"Remove profile '{p.name}'?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.vault.delete(p.id)
            self.profiles.remove(p)
            self.store.save(self.profiles)
            self.refresh()
            self.disconnect()
        except (RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Remove failed", str(exc))

    def connect_profile(self):
        if self._busy:
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
        if token and urlsplit(p.url).scheme == "http" and not self.trust_http.isChecked():
            QMessageBox.warning(self, "Unencrypted transport", "Confirm the trusted LAN checkbox before sending credentials over HTTP.")
            return
        self._busy = True
        self.test_button.setEnabled(False)
        self.details.setText("Connecting in background…")
        self.status_changed.emit("BACKEND CONNECTING")
        worker = DiscoveryWorker(p.url, token)
        self._worker = worker
        profile_id = p.id
        worker.signals.completed.connect(
            lambda result, error: self._discovery_done(profile_id, result, error)
        )
        QThreadPool.globalInstance().start(worker)

    def _discovery_done(self, profile_id, result, error):
        self._busy = False
        self.test_button.setEnabled(True)
        self._worker = None
        if error:
            self.details.setText(f"{error[0]}: {error[1]}")
            self.status_changed.emit("BACKEND OFFLINE")
            return
        p = next((x for x in self.profiles if x.id == profile_id), None)
        if p is None:
            self.disconnect()
            return
        if p.instance_id and p.instance_id != result.instance_id:
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
                self.disconnect()
                return
        changed_boot = bool(p.boot_id and p.boot_id != result.boot_id)
        p.instance_id = result.instance_id
        p.boot_id = result.boot_id
        try:
            self.store.save(self.profiles)
        except OSError as exc:
            self.details.setText(f"Connected, but could not save profile: {exc}")
            self.status_changed.emit("BACKEND OFFLINE")
            return
        available = ", ".join(k for k, v in result.features.items() if v) or "none advertised"
        self.details.setText(
            f"Connected: {p.name} | backend {result.version} | mode {result.mode}\n"
            f"Instance: {result.instance_id}\nBoot: {result.boot_id}\n"
            f"Features enabled: {available}"
            + ("\nBackend restarted: refresh job state before continuing." if changed_boot else "")
        )
        self.status_changed.emit("BACKEND CONNECTED")

    def disconnect(self):
        if self._busy:
            return
        self.details.setText("Disconnected from Studio (backend remains running).")
        self.status_changed.emit("BACKEND OFFLINE")
