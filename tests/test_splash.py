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
        assert splash_logo_path().name == "splash-logo.jpg"
        assert splash_logo_path().is_file()
        assert splash_logo_path().read_bytes().startswith(bytes.fromhex("ffd8ff"))
    finally:
        splash.close()
        assert app is not None

def test_packaged_logo_decodes_without_qt_jpeg_warnings():
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtGui import QPixmap

    app = QApplication.instance() or QApplication([])
    warnings = []
    previous = qInstallMessageHandler(lambda mode, context, message: warnings.append(message))
    try:
        pixmap = QPixmap(str(splash_logo_path()))
        assert not pixmap.isNull()
    finally:
        qInstallMessageHandler(previous)
    assert not [message for message in warnings if "jpeg" in message.lower() or "corrupt" in message.lower()]
    assert app is not None
