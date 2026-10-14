"""Brings the Studio-managed backend up while the splash screen is showing."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEventLoop, QTimer

STARTUP_LIMIT_MS = 100_000  # a little longer than the backend's own start timeout


def wait_for_backend(panel, on_progress: Callable[[str], None], limit_ms: int = STARTUP_LIMIT_MS) -> tuple[bool, str]:
    """Run the panel's startup and wait (keeping the splash alive) until it connects, fails or times out."""
    loop = QEventLoop()
    outcome: dict[str, object] = {}

    def done(ok: bool, reason: str) -> None:
        if "ok" not in outcome:
            outcome.update(ok=ok, reason=reason)
            loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: done(False, "The local backend did not become ready in time."))
    panel.startup_done.connect(done)
    panel.startup_progress.connect(on_progress)
    try:
        timer.start(limit_ms)
        panel.begin_startup()
        if "ok" not in outcome:  # startup can finish before the first event
            loop.exec()
    finally:
        timer.stop()
        panel.startup_done.disconnect(done)
        panel.startup_progress.disconnect(on_progress)
    return bool(outcome["ok"]), str(outcome["reason"])
