"""Test-session teardown guard.

Many UI tests build Qt objects without a parent and wire them together with signals. When the
interpreter tears those down after Qt has been finalised, PySide6 can crash the process at exit
("shared QObject was deleted directly" followed by a segmentation fault) even though every test
passed. After the report has been printed, collect garbage while Qt is still healthy and leave
without running that interpreter teardown, keeping pytest's real exit status.
"""

import gc
import os
import sys

_status = {"code": None}


def pytest_sessionfinish(session, exitstatus):
    _status["code"] = int(exitstatus)
    if "PySide6" in sys.modules:
        app_module = sys.modules.get("PySide6.QtWidgets")
        app = app_module.QApplication.instance() if app_module else None
        if app is not None:
            app.closeAllWindows()
            app.processEvents()
        gc.collect()


def pytest_unconfigure(config):
    code = _status["code"]
    if code is not None and "PySide6" in sys.modules:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
