"""Live backend console (S3 follow-up): one background stream per connection.

The backend's console ring is fetched once for history, then a server-sent-event stream resumes
from the last id. If the stream drops it reconnects with backoff, and the backend itself reports
a gap or a restart, which are shown as markers instead of being papered over. Polling the console
endpoint would write a console line per poll, so a stream is the right tool here.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.console import ConsoleApi, ConsoleEntry, Gap, Reset
from morphorum_studio.backend.session import BackendSession

MAX_ENTRIES = 5000
BACKOFF = (1.0, 2.0, 4.0, 8.0, 10.0)


class ConsoleService(QObject):
    entries_added = Signal(object)  # list[ConsoleEntry]
    marker = Signal(str)  # a note about the stream itself (gap, restart, reconnect)
    state_changed = Signal(str)  # live | connecting | reconnecting | stopped
    cleared = Signal()
    _incoming = Signal(str, object)

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 spawn: Callable[[Callable[[], None]], None] | None = None,
                 wait: Callable[[float], None] | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._spawn = spawn or self._spawn_thread
        self._pause = wait or self._sleep
        self._epoch = session.epoch
        self._gen = 0
        self._running = False
        self._state = "stopped"
        self._cursor = 0
        self._boot: str | None = None
        self.entries: deque[ConsoleEntry] = deque(maxlen=MAX_ENTRIES)
        self._incoming.connect(self._deliver)
        session.changed.connect(self._session_changed)
        self._session_changed()

    # -- state --------------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def available(self) -> bool:
        return self._session.state in ("connected", "reconnecting") and self._session.info is not None

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self.stop()
            self._reset_history()
        if self._session.state == "connected" and not self._running:
            self.start()
        elif self._session.state == "offline":
            self.stop()

    def _reset_history(self) -> None:
        self.entries.clear()
        self._cursor = 0
        self._boot = None
        self.cleared.emit()

    def clear_view(self) -> None:
        """Forget what Studio holds; the backend's own buffer is untouched and the stream goes on."""
        self.entries.clear()
        self.cleared.emit()

    # -- running ------------------------------------------------------------------------

    def start(self) -> None:
        if self._running or self._session.state != "connected":
            return
        stream_client = self._session.client(timeout=30.0)
        snapshot_client = self._session.client(timeout=10.0)
        if stream_client is None or snapshot_client is None:
            return
        self._gen += 1
        gen = self._gen
        self._running = True
        self._set_state("connecting")
        self._spawn(lambda: self._loop(gen, snapshot_client, stream_client))

    def stop(self) -> None:
        self._gen += 1
        self._running = False
        self._set_state("stopped")

    def _spawn_thread(self, fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, name="console-stream", daemon=True).start()

    def _sleep(self, seconds: float) -> None:
        threading.Event().wait(seconds)

    # -- background loop (not the GUI thread) -------------------------------------------

    def _loop(self, gen: int, snapshot_client: BackendClient, stream_client: BackendClient) -> None:
        def stopped() -> bool:
            return gen != self._gen

        attempt = 0
        have_history = self._cursor > 0
        while not stopped():
            try:
                if not have_history:
                    entries, boot = ConsoleApi(snapshot_client).snapshot(0, 500)
                    if stopped():
                        return
                    self._incoming.emit("history", (entries, boot))
                    have_history = True
                self._incoming.emit("state", "live")
                for item in ConsoleApi(stream_client).stream(self._cursor, self._boot, stopped):
                    if stopped():
                        return
                    attempt = 0
                    self._incoming.emit("item", item)
                if stopped():
                    return
                self._incoming.emit("state", "reconnecting")
            except BackendError as exc:
                if stopped():
                    return
                if exc.code in ("AUTH_REQUIRED", "FORBIDDEN"):
                    self._incoming.emit("fatal", f"The console stream was refused ({exc})")
                    return
                self._incoming.emit("state", "reconnecting")
            except ValueError:
                self._incoming.emit("fatal", "The console stream could not be opened")
                return
            self._pause(BACKOFF[min(attempt, len(BACKOFF) - 1)])
            attempt += 1

    # -- GUI thread ---------------------------------------------------------------------

    def _deliver(self, kind: str, payload) -> None:
        if kind == "history":
            entries, boot = payload
            self._boot = boot
            fresh = [e for e in entries if e.id > self._cursor]
            self._append(fresh)
        elif kind == "item":
            if isinstance(payload, ConsoleEntry):
                if payload.id > self._cursor:
                    self._append([payload])
            elif isinstance(payload, Gap):
                self.marker.emit("Some console lines were dropped by the backend before Studio read them.")
            elif isinstance(payload, Reset):
                self._cursor = 0
                self._boot = None
                self.marker.emit("The backend restarted; the console starts over.")
                self.entries.clear()
                self.cleared.emit()
        elif kind == "state":
            if payload == "reconnecting" and self._state == "live":
                self.marker.emit("Console stream interrupted; reconnecting…")
            self._set_state(payload)
        elif kind == "fatal":
            self._running = False
            self._set_state("stopped")
            self.marker.emit(str(payload))

    def _append(self, entries: list[ConsoleEntry]) -> None:
        if not entries:
            return
        self._cursor = max(self._cursor, entries[-1].id)
        self.entries.extend(entries)
        self.entries_added.emit(entries)
