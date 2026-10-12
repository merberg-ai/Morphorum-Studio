"""S0 smoke tests. Never connect to a backend or load a model."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from morphorum_studio import __version__
from morphorum_studio.app import main
from morphorum_studio.ui.main_window import PAGES, StudioMainWindow


def test_version_command(capsys):
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_navigation_and_initial_offline_state():
    app = QApplication.instance() or QApplication(["morphorum-studio-tests"])
    window = StudioMainWindow()
    try:
        assert window.navigation.count() == len(PAGES)
        assert window.pages.count() == len(PAGES)
        assert window.navigation.currentRow() == 0
        assert window.connection_status.text() == "BACKEND OFFLINE"
        window.navigation.setCurrentRow(5)
        assert window.pages.currentIndex() == 5
        window.navigation.setCurrentRow(1)
        assert window.pages.currentIndex() == 1
    finally:
        window.close()
        # App instance remains under Qt ownership until the test exits.
        assert app is not None
