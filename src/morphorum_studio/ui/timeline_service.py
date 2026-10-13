"""Timeline loading and read-only evaluation (S4.1).

Everything numeric comes from the backend: the track list from its timeline snapshot, curves
from ``schedule-series`` and per-frame values from ``resolve-timeline``. Answers that arrive after
the project, the frame or the connection changed are dropped.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.client import BackendClient
from morphorum_studio.backend.projects import ProjectsApi
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.timeline import Series, Timeline, TimelineApi
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


class TimelineService(QObject):
    loaded = Signal(object)  # Timeline
    series_ready = Signal(str, object)  # track id, Series | None (None: the backend refused)
    resolved = Signal(object)  # Resolved
    failed = Signal(str, str, str)  # operation, code, message
    busy_changed = Signal(bool)
    cleared = Signal()

    def __init__(self, session: BackendSession, parent: QObject | None = None,
                 runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._seq = 0  # bumps when the project changes
        self._frame_seq = 0
        self._busy = False
        self.timeline: Timeline | None = None
        self._raw: dict | None = None
        self._series: dict[str, Series | None] = {}
        session.changed.connect(self._session_changed)

    @property
    def available(self) -> bool:
        return self._session.state == "connected" and self._session.feature("timeline")

    @property
    def busy(self) -> bool:
        return self._busy

    def _client(self, timeout: float = 15.0) -> BackendClient | None:
        return self._session.client(timeout=timeout) if self.available else None

    def _stale(self, epoch: int, seq: int | None = None) -> bool:
        return (epoch != self._session.epoch or self._session.state == "offline"
                or (seq is not None and seq != self._seq))

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self.forget()
            self.cleared.emit()

    def forget(self) -> None:
        self._seq += 1
        self._frame_seq += 1
        self.timeline = None
        self._raw = None
        self._series.clear()
        self._set_busy(False)

    # -- loading ------------------------------------------------------------------------

    def load(self, project_id: str) -> None:
        client = self._client(30.0)
        if client is None:
            return
        self.forget()
        seq, epoch = self._seq, self._session.epoch
        self._set_busy(True)

        def work(c: BackendClient):
            return TimelineApi(c).timeline(project_id), ProjectsApi(c).raw(project_id)

        def done(result, error):
            if self._stale(epoch, seq):
                return
            self._set_busy(False)
            if error:
                self.failed.emit("load", *error)
                return
            self.timeline, self._raw = result
            self.loaded.emit(self.timeline)

        self._run(client, work, done)

    # -- evaluation ---------------------------------------------------------------------

    def request_series(self, track_id: str) -> None:
        timeline, raw = self.timeline, self._raw
        track = timeline.track(track_id) if timeline else None
        if track is None or raw is None or track.kind != "numeric" or not track.field:
            return
        if track_id in self._series:
            self.series_ready.emit(track_id, self._series[track_id])
            return
        client = self._client()
        if client is None:
            return
        seq, epoch = self._seq, self._session.epoch

        def done(result, error):
            if self._stale(epoch, seq):
                return
            if error:
                self._series[track_id] = None
                self.failed.emit("series", *error)
            else:
                self._series[track_id] = result
            self.series_ready.emit(track_id, self._series[track_id])

        self._run(client, lambda c: TimelineApi(c).series(raw, track.field, 160), done)

    def request_frame(self, frame: int) -> None:
        timeline, raw = self.timeline, self._raw
        if timeline is None or raw is None or not 0 <= frame < timeline.max_frames:
            return
        client = self._client()
        if client is None:
            return
        self._frame_seq += 1
        frame_seq, seq, epoch = self._frame_seq, self._seq, self._session.epoch

        def done(result, error):
            if self._stale(epoch, seq) or frame_seq != self._frame_seq:
                return
            if error:
                self.failed.emit("frame", *error)
            else:
                self.resolved.emit(result)

        self._run(client, lambda c: TimelineApi(c).resolve(raw, frame, timeline), done)
