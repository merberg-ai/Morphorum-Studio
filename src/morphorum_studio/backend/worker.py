"""One-shot Qt network workers. Never call HTTP on GUI thread."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .client import BackendClient, BackendError


class WorkerSignals(QObject):
    completed = Signal(object, object)


class DiscoveryWorker(QRunnable):
    def __init__(self, url: str, token: str | None):
        super().__init__()
        self.url = url
        self.token = token
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = BackendClient(self.url, self.token).discover()
            self.signals.completed.emit(result, None)
        except BackendError as error:
            self.signals.completed.emit(None, (error.code, str(error)))
        except Exception:
            self.signals.completed.emit(None, ("CONNECTION_ERROR", "Backend connection failed"))


class ApiWorker(QRunnable):
    """Run one read-only call (``fn(client)``) on a pool thread and report ``(result, error)``.

    ``error`` is ``(code, message)``; messages never contain credentials.
    """

    def __init__(self, client: BackendClient, fn: Callable[[BackendClient], Any]):
        super().__init__()
        self._client = client
        self._fn = fn
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self._fn(self._client)
        except BackendError as error:
            self.signals.completed.emit(None, (error.code, str(error)))
        except Exception:
            self.signals.completed.emit(None, ("CONNECTION_ERROR", "Backend request failed"))
        else:
            self.signals.completed.emit(result, None)
