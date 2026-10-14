"""Background operations for the new-project wizard and the model browser (S4.4)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.api import ReadApi
from morphorum_studio.backend.client import BackendClient
from morphorum_studio.backend.loras import LoraApi
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.setup import Choices, SetupApi
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


class _Service(QObject):
    failed = Signal(str, str, str)  # operation, code, message
    busy_changed = Signal(bool)
    cleared = Signal()
    feature = "project_crud"

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._seq = 0
        self._busy = False
        session.changed.connect(self._session_changed)

    @property
    def available(self) -> bool:
        return self._session.state == "connected" and self._session.feature(self.feature)

    @property
    def busy(self) -> bool:
        return self._busy

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._seq += 1
            self._set_busy(False)
            self.cleared.emit()

    def _go(self, op: str, work, signal, timeout: float = 30.0, busy: bool = True) -> None:
        client: BackendClient | None = self._session.client(timeout=timeout) if self.available else None
        if client is None or (busy and self._busy):
            return
        self._seq += 1
        seq, epoch = self._seq, self._session.epoch
        if busy:
            self._set_busy(True)

        def done(result, error):
            if epoch != self._session.epoch or self._session.state == "offline" or seq != self._seq:
                return
            if busy:
                self._set_busy(False)
            if error:
                self.failed.emit(op, *error)
            else:
                signal.emit(result)

        self._run(client, work, done)


class SetupService(_Service):
    """Template, checkpoint list, backend review and create for the new-project wizard."""

    setup_ready = Signal(object, object)  # template dict, tuple[ModelEntry] checkpoints
    reviewed = Signal(object)  # Validation
    created = Signal(object)  # ProjectDetail

    def load(self) -> None:
        discover = self._session.feature("model_discovery")

        def work(c: BackendClient):
            checkpoints = ReadApi(c).models(kind="checkpoints") if discover else ()
            return SetupApi(c).template(), checkpoints
        self._go("setup", work, _Splat(self.setup_ready), 20.0)

    def review(self, template: dict, choices: Choices) -> None:
        self._go("review", lambda c: SetupApi(c).review(template, choices), self.reviewed)

    def create(self, template: dict, choices: Choices) -> None:
        self._go("create", lambda c: SetupApi(c).create(template, choices), self.created)


class _Splat:
    """Emits a 2-tuple result as two signal arguments."""

    def __init__(self, signal) -> None:
        self._signal = signal

    def emit(self, result) -> None:
        self._signal.emit(*result)


class ModelsService(_Service):
    """Read-only checkpoint and LoRA listing plus LoRA inspection."""

    feature = "model_discovery"
    _looking = False
    library_ready = Signal(object, object)  # tuple[ModelEntry] checkpoints, tuple[ModelEntry] loras
    inspected = Signal(object)  # LoraDetail
    civitai_ready = Signal(str, object)  # model id, CivitaiMatch
    lookup_busy = Signal(bool)

    def load(self) -> None:
        def work(c: BackendClient):
            api = ReadApi(c)
            return api.models(kind="checkpoints"), api.models(kind="loras")
        self._go("library", work, _Splat(self.library_ready), 20.0)

    def inspect(self, model_id: str) -> None:
        self._go("inspect", lambda c: LoraApi(c).inspect(model_id), self.inspected, 30.0, busy=False)

    def lookup(self, model_id: str) -> None:
        """Civitai lookup (hashing a large file can take a while). Tracked apart from browsing so
        selecting another LoRA while it runs does not discard the answer."""
        client = self._session.client(timeout=60.0) if self.available else None
        if client is None or self._looking:
            return
        self._looking = True
        epoch = self._session.epoch
        self.lookup_busy.emit(True)

        def done(result, error):
            if epoch != self._session.epoch or self._session.state == "offline":
                return
            self._looking = False
            self.lookup_busy.emit(False)
            if error:
                self.failed.emit("lookup", *error)
            else:
                self.civitai_ready.emit(model_id, result)

        self._run(client, lambda c: LoraApi(c).civitai(model_id), done)

    @property
    def looking(self) -> bool:
        return self._looking

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._looking = False
        super()._session_changed()
