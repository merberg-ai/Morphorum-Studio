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

    from PySide6.QtGui import QIcon

    from .ui.fonts import load_bundled_fonts
    from .ui.main_window import StudioMainWindow
    from .ui.shell import asset_path
    from .ui.theme import application_stylesheet

    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([sys.argv[0]])
    assert app is not None
    app.setApplicationName("Morphorum Studio")
    app.setOrganizationName("Morphorum")
    app.setStyle("Fusion")
    load_bundled_fonts()
    app.setStyleSheet(application_stylesheet())
    icon_path = asset_path("app-icon.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    from .ui.preferences import StudioPreferences
    from .ui.splash import StudioSplash

    preferences = StudioPreferences()
    splash = None
    total = 3
    if preferences.enabled("show_splash", True):
        splash = StudioSplash()
        splash.show()
        splash.stage("Loading desktop preferences…", 1, total)
        app.processEvents()
        splash.stage("Preparing native workspaces…", 2, total)
        app.processEvents()
    window = StudioMainWindow(preferences=preferences)
    # If the backend Studio used last is the one it manages itself, bring it up now.
    managed_startup = window.managed_startup_wanted()
    failure = ""
    if splash and managed_startup:
        from .ui.managed_startup import wait_for_backend

        total = 4
        splash.stage("Starting the local backend…", 3, total)
        app.processEvents()
        ok, reason = wait_for_backend(window.managed_panel, lambda text: splash.stage(text, 3, total))
        failure = "" if ok else reason or "The local backend could not be started."
    if splash:
        splash.stage("Restoring desktop session…", total, total)
        app.processEvents()
    window.show()
    if splash:
        splash.finish(window)
    if failure:
        window.show_startup_failure(failure)
    elif managed_startup and not splash:
        window.begin_managed_startup()  # no splash to wait behind: bring it up in the background
    if not owns_app:
        return 0  # The embedding application owns its event loop.
    return app.exec()
