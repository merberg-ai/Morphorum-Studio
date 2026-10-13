"""Splash startup stage and optional artwork fallback checks."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from morphorum_studio.ui.splash import StudioSplash, splash_logo_path


def test_splash_stages_without_network():
    app = QApplication.instance() or QApplication([])
    splash = StudioSplash()
    try:
        assert splash.pixmap().width() == 560
        assert splash.pixmap().height() == 430
        for stage in (1, 2, 3):
            splash.stage("Startup stage", stage)
            assert not splash.pixmap().isNull()
        assert splash_logo_path().name == "morphorum-studio-logo.png"
    finally:
        splash.close()
        assert app is not None
