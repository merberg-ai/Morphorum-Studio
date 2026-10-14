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

    def recent_projects(self, profile_id: str) -> list[str]:
        """Most recently opened project ids for one connection profile (newest first)."""
        raw = str(self.settings.value("projects/recent/" + profile_id, "") or "")
        return [item for item in raw.split(",") if item]

    def remember_project(self, profile_id: str, project_id: str, keep: int = 8) -> None:
        items = [project_id] + [p for p in self.recent_projects(profile_id) if p != project_id]
        self.settings.setValue("projects/recent/" + profile_id, ",".join(items[:keep]))

    def forget_project(self, profile_id: str, project_id: str) -> None:
        items = [p for p in self.recent_projects(profile_id) if p != project_id]
        self.settings.setValue("projects/recent/" + profile_id, ",".join(items))

    def image_model(self, profile_id: str) -> str:
        return str(self.settings.value("imagelab/model/" + profile_id, "") or "")

    def set_image_model(self, profile_id: str, model_id: str) -> None:
        self.settings.setValue("imagelab/model/" + profile_id, model_id)

    def workspace(self) -> str:
        return str(self.settings.value("window/workspace", "Home") or "Home")

    def set_workspace(self, name: str) -> None:
        self.settings.setValue("window/workspace", name)

    def ui(self, key: str, default: str = "") -> str:
        """A remembered view setting (filters, toggles) under ``ui/<key>``."""
        return str(self.settings.value(f"ui/{key}", default) or default)

    def set_ui(self, key: str, value: str) -> None:
        self.settings.setValue(f"ui/{key}", value)

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
