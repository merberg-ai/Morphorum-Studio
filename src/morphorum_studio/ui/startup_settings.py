"""Pre-S2 native startup and session settings."""
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from .preferences import StudioPreferences


OPTIONS = (
    ("show_splash", "Show branded splash screen on startup", True),
    ("restore_geometry", "Restore window size and screen position", True),
    ("restore_workspace", "Reopen the last workspace", True),
    ("auto_connect", "Automatically connect to last successful backend", False),
)


class StartupSettingsPanel(QWidget):
    def __init__(self, preferences: StudioPreferences, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("STARTUP & SESSION / STUDIO"))
        title = QLabel("Desktop preferences")
        title.setObjectName("pageHeading")
        layout.addWidget(title)
        hint = QLabel(
            "Changes save immediately. Auto-connect uses the last successful backend and requires saved trust for HTTP. "
            "Studio never stores bearer credentials here."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.options = {}
        for key, label, default in OPTIONS:
            control = QCheckBox(label)
            control.setChecked(self.preferences.enabled(key, default))
            control.toggled.connect(
                lambda checked, setting=key: self.preferences.set_enabled(setting, checked)
            )
            self.options[key] = control
            layout.addWidget(control)
        layout.addStretch()
