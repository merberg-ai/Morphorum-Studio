"""Nonsecret Studio desktop preferences (OS-native QSettings)."""
from __future__ import annotations

from PySide6.QtCore import QSettings


class StudioPreferences:
    def __init__(self, settings: QSettings | None = None):
        self.settings = settings or QSettings("Morphorum", "Morphorum Studio")

    def enabled(self, key: str, default: bool) -> bool:
        value = self.settings.value("startup/" + key, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes")

    def set_enabled(self, key: str, enabled: bool) -> None:
        self.settings.setValue("startup/" + key, bool(enabled))

    def profile(self, key: str) -> str:
        return str(self.settings.value("connections/" + key, "") or "")

    def set_profile(self, key: str, value: str) -> None:
        self.settings.setValue("connections/" + key, value)

    def trusted_http(self, profile_id: str, url: str) -> bool:
        return str(self.settings.value(
            "http_consent/" + profile_id, ""
        ) or "") == url

    def set_trusted_http(self, profile_id: str, url: str, allowed: bool) -> None:
        self.settings.setValue("http_consent/" + profile_id, url if allowed else "")

    def workspace(self) -> str:
        return str(self.settings.value("window/workspace", "Home") or "Home")

    def set_workspace(self, name: str) -> None:
        self.settings.setValue("window/workspace", name)

    def save_window(self, window) -> None:
        self.settings.setValue("window/geometry", window.saveGeometry())
        self.settings.setValue("window/maximized", window.isMaximized())

    def restore_window(self, window) -> None:
        geometry = self.settings.value("window/geometry")
        if self.enabled("restore_geometry", True):
            if geometry:
                window.restoreGeometry(geometry)
            # Qt may restore a window onto a disconnected monitor. Recenter if needed.
            screens = window.screen().virtualSiblings() if window.screen() else []
            center = window.frameGeometry().center()
            if screens and not any(s.availableGeometry().contains(center) for s in screens):
                available = screens[0].availableGeometry()
                window.resize(min(window.width(), available.width()), min(window.height(), available.height()))
                window.move(available.center() - window.rect().center())
            if self.settings.value("window/maximized", False) in (True, "true", "True", 1):
                window.showMaximized()

    def sync(self) -> None:
        self.settings.sync()
