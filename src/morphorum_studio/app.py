"""Application bootstrap. No backend connection is attempted in S0."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="morphorum-studio",
        description="Native desktop frontend for Morphorum rendering backends.",
    )
    parser.add_argument("--version", action="store_true", help="Print the Studio version.")
    args = parser.parse_args(argv)
    if args.version:
        print(f"Morphorum Studio {__version__}")
        return 0

    # Qt is imported only when starting the GUI, keeping version/diagnostic
    # commands usable on machines without a display server.
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import StudioMainWindow
    from .ui.theme import DARK_STYLESHEET

    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([sys.argv[0]])
    assert app is not None
    app.setApplicationName("Morphorum Studio")
    app.setOrganizationName("Morphorum")
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)
    from .ui.preferences import StudioPreferences
    from .ui.splash import StudioSplash

    preferences = StudioPreferences()
    splash = None
    if preferences.enabled("show_splash", True):
        splash = StudioSplash()
        splash.show()
        splash.stage("Loading desktop preferences…")
        app.processEvents()
        splash.stage("Preparing native workspaces…")
        app.processEvents()
    window = StudioMainWindow(preferences=preferences)
    if splash:
        splash.stage("Restoring desktop session…")
        app.processEvents()
    window.show()
    if splash:
        splash.finish(window)
    if not owns_app:
        return 0  # The embedding application owns its event loop.
    return app.exec()
