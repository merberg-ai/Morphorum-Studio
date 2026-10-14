"""Background refresh of dashboard data (telemetry and model catalogue).

Reads from the shared ``BackendSession``; it never opens its own connection or monitors
health. Requests run on the Qt thread pool, never overlap, stop when the page is hidden or
the connection leaves the ``connected`` state, and results that belong to an older
connection (``epoch`` changed) are discarded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal, Slot

from morphorum_studio.backend.api import ReadApi
from morphorum_studio.backend.client import BackendClient
from morphorum_studio.backend.schema import (
    FamilyDefaults,
    ModelFamily,
    ModelSummary,
    Telemetry,
)
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.worker import ApiWorker

TELEMETRY_INTERVAL_MS = 3000
TELEMETRY_MAX_BACKOFF_MS = 15000
MODELS_INTERVAL_MS = 60000
STALE_AFTER_S = 10.0

Callback = Callable[[Any, "tuple[str, str] | None"], None]
Runner = Callable[[BackendClient, Callable[[BackendClient], Any], Callback], None]


@dataclass(frozen=True)
class ModelCatalog:
    families: tuple[ModelFamily, ...]
    summary: ModelSummary
    defaults: dict[str, FamilyDefaults] | None  # None: the backend did not provide them


class _Call(QObject):
    """Carries one request's callback so completion is delivered on the GUI thread."""

    def __init__(self, parent: QObject, callback: Callback) -> None:
        super().__init__(parent)
        self._callback = callback
        self.worker: Any = None

    @Slot(object, object)
    def done(self, result, error) -> None:
        try:
            self._callback(result, error)
        finally:
            self.deleteLater()


def thread_pool_runner(owner: QObject) -> Runner:
    def run(client: BackendClient, fn: Callable[[BackendClient], Any], callback: Callback) -> None:
        call = _Call(owner, callback)
        worker = ApiWorker(client, fn)
        worker.setAutoDelete(False)  # The call object keeps the worker (and its signals) alive.
        call.worker = worker
        worker.signals.completed.connect(call.done)
        QThreadPool.globalInstance().start(worker)

    return run


class DashboardService(QObject):
    telemetry_updated = Signal(object)  # Telemetry
    telemetry_failed = Signal(str)  # error code
    latency_updated = Signal(float)  # milliseconds for the last telemetry round trip
    models_updated = Signal(object, object)  # ModelCatalog, (family id or None, tuple[ModelEntry])
    models_failed = Signal(str)
    cleared = Signal()

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._active = False
        self._watching = False  # the shell footer wants telemetry on every page
        self._poll_started = 0.0
        self._epoch = session.epoch
        self._telemetry_inflight = False
        self._models_inflight = False
        self._failures = 0
        self._catalog: ModelCatalog | None = None
        self._family: str | None = None
        self._telemetry_ok_at: float | None = None
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setSingleShot(True)
        self._telemetry_timer.timeout.connect(self._poll_telemetry)
        self._models_timer = QTimer(self)
        self._models_timer.setSingleShot(True)
        self._models_timer.timeout.connect(self.refresh_models)
        session.changed.connect(self._session_changed)

    # -- state --------------------------------------------------------------------------

    @property
    def catalog(self) -> ModelCatalog | None:
        return self._catalog

    @property
    def selected_family(self) -> str | None:
        return self._family

    def telemetry_is_stale(self) -> bool:
        if self._telemetry_ok_at is None:
            return False
        return monotonic() - self._telemetry_ok_at > STALE_AFTER_S

    # -- control ------------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        """Poll only while the dashboard is visible."""
        if active == self._active:
            return
        self._active = active
        self._apply_wanted()

    def set_watching(self, watching: bool) -> None:
        """Keep telemetry flowing on every page (for the shell footer), not only on Home."""
        if watching == self._watching:
            return
        self._watching = watching
        self._apply_wanted()

    @property
    def _wanted(self) -> bool:
        return self._active or self._watching

    def _apply_wanted(self) -> None:
        if self._wanted:
            self._start()
        else:
            self._telemetry_timer.stop()
            self._models_timer.stop()

    def select_family(self, family: str | None) -> None:
        self._family = family
        self.refresh_models()

    def refresh_models(self) -> None:
        self._models_timer.stop()
        if self._models_inflight or self._session.state != "connected":
            return
        client = self._session.client()
        if client is None or not self._session.feature("model_discovery"):
            return
        self._models_inflight = True
        epoch, family = self._session.epoch, self._family
        need_catalog = self._catalog is None

        def work(c: BackendClient):
            api = ReadApi(c)
            catalog = None
            if need_catalog:
                try:
                    defaults = api.generation_defaults()
                except Exception:  # Defaults are a nicety; the inventory must not depend on them.
                    defaults = None
                catalog = ModelCatalog(api.model_families(), api.model_summary(), defaults)
            return catalog, api.models(family=family)

        self._run(client, work, lambda result, error: self._models_done(epoch, family, result, error))

    def refresh_now(self) -> None:
        """Manual refresh of everything (Refresh button)."""
        self._catalog = None
        self.refresh_models()
        if not self._telemetry_inflight:
            self._telemetry_timer.stop()
            self._poll_telemetry()

    # -- internals ----------------------------------------------------------------------

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._telemetry_timer.stop()
            self._models_timer.stop()
            self._telemetry_inflight = False
            self._models_inflight = False
            self._failures = 0
            self._catalog = None
            self._family = None
            self._telemetry_ok_at = None
            self.cleared.emit()
        if self._session.state == "connected":
            self._start()
        else:
            self._telemetry_timer.stop()
            self._models_timer.stop()

    def _start(self) -> None:
        if self._session.state != "connected":
            return
        if self._catalog is None and not self._models_inflight:
            self.refresh_models()
        elif not self._models_inflight and not self._models_timer.isActive():
            self._models_timer.start(MODELS_INTERVAL_MS)  # Resume after an outage or hidden page.
        if self._wanted and not self._telemetry_inflight and not self._telemetry_timer.isActive():
            self._poll_telemetry()

    def _poll_telemetry(self) -> None:
        if (not self._wanted or self._telemetry_inflight or self._session.state != "connected"
                or not self._session.feature("gpu_telemetry")):
            return
        client = self._session.client()
        if client is None:
            return
        self._telemetry_inflight = True
        self._poll_started = monotonic()
        epoch = self._session.epoch
        self._run(client, lambda c: ReadApi(c).telemetry(),
                  lambda result, error: self._telemetry_done(epoch, result, error))

    def _stale(self, epoch: int) -> bool:
        return epoch != self._session.epoch or self._session.state == "offline"

    def _telemetry_done(self, epoch: int, result: Telemetry | None, error) -> None:
        if self._stale(epoch):
            return
        self._telemetry_inflight = False
        if error:
            self._failures += 1
            self.telemetry_failed.emit(error[0])
        else:
            self._failures = 0
            self._telemetry_ok_at = monotonic()
            self.latency_updated.emit((self._telemetry_ok_at - self._poll_started) * 1000.0)
            self.telemetry_updated.emit(result)
        if self._wanted and self._session.state == "connected":
            delay = min(TELEMETRY_MAX_BACKOFF_MS,
                        TELEMETRY_INTERVAL_MS * (2 ** min(self._failures, 3)))
            self._telemetry_timer.start(delay)

    def _models_done(self, epoch: int, family: str | None, result, error) -> None:
        if self._stale(epoch):
            return
        self._models_inflight = False
        if error:
            self.models_failed.emit(error[0])
        elif family != self._family:
            # The user picked another family while this request ran; fetch the right one.
            self.refresh_models()
            return
        else:
            catalog, models = result
            if catalog is not None:
                self._catalog = catalog
            if self._catalog is not None:
                self.models_updated.emit(self._catalog, (family, models))
        if self._session.state == "connected":
            self._models_timer.start(MODELS_INTERVAL_MS if not error else MODELS_INTERVAL_MS // 2)
