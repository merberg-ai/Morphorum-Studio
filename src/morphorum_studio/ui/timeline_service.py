"""Timeline loading and read-only evaluation (S4.1).

Everything numeric comes from the backend: the track list from its timeline snapshot, curves
from ``schedule-series`` and per-frame values from ``resolve-timeline``. Answers that arrive after
the project, the frame or the connection changed are dropped.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.validation import ValidationApi
from morphorum_studio.backend.timeline import Edit, EditApi, Op, Series, Timeline, TimelineApi
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


class TimelineService(QObject):
    loaded = Signal(object)  # Timeline
    series_ready = Signal(str, object)  # track id, Series | None (None: the backend refused)
    resolved = Signal(object)  # Resolved
    edited = Signal(object)  # Timeline reloaded from the backend after an edit, undo or redo
    history_changed = Signal()
    validated = Signal(object)  # Validation | None (None: could not be checked)
    conflict = Signal(str)  # the project changed elsewhere; edits were refused
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
        self._project_id: str | None = None
        self._validate_seq = 0
        self._etag: str | None = None
        self._undo: list[Edit] = []
        self._redo: list[Edit] = []
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
        self._project_id = None
        self._etag = None
        self._series.clear()
        self._clear_history()
        self._set_busy(False)

    def _clear_history(self) -> None:
        if self._undo or self._redo:
            self._undo.clear()
            self._redo.clear()
            self.history_changed.emit()

    # -- loading ------------------------------------------------------------------------

    def load(self, project_id: str) -> None:
        client = self._client(30.0)
        if client is None:
            return
        self.forget()
        seq, epoch = self._seq, self._session.epoch
        self._set_busy(True)

        def work(c: BackendClient):
            api = EditApi(c)
            timeline = api.timeline(project_id)
            raw, etag = api.project_revision(project_id)
            return timeline, raw, etag

        def done(result, error):
            if self._stale(epoch, seq):
                return
            self._set_busy(False)
            if error:
                self.failed.emit("load", *error)
                return
            self.timeline, self._raw, self._etag = result
            self._project_id = project_id
            self.loaded.emit(self.timeline)

        self._run(client, work, done)

    # -- validation (S4.3) --------------------------------------------------------------

    def validate(self) -> None:
        """Ask the backend whether the saved project's schedules are valid (read-only)."""
        raw = self._raw
        client = self._client()
        if raw is None or client is None:
            return
        seq, epoch = self._seq, self._session.epoch
        self._validate_seq += 1
        check = self._validate_seq

        def done(result, error):
            if self._stale(epoch, seq) or check != self._validate_seq:
                return
            if error:
                self.failed.emit("validate", *error)
                self.validated.emit(None)
            else:
                self.validated.emit(result)

        self._run(client, lambda c: ValidationApi(c).check(raw), done)

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

    # -- editing (S4.2) -----------------------------------------------------------------

    @property
    def can_edit(self) -> bool:
        return (self.available and self.timeline is not None and self._etag is not None
                and not self._busy)

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1].label if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1].label if self._redo else None

    def apply(self, edit: Edit) -> None:
        self._execute(edit.forward, edit, "do")

    def undo(self) -> None:
        if self._undo and self.can_edit:
            edit = self._undo[-1]
            self._execute(edit.inverse, edit, "undo")

    def redo(self) -> None:
        if self._redo and self.can_edit:
            edit = self._redo[-1]
            self._execute(edit.forward, edit, "redo")

    def _execute(self, ops: tuple[Op, ...], edit: Edit, direction: str) -> None:
        project_id, etag = self._project_id, self._etag
        client = self._client(30.0)
        if not self.can_edit or client is None or project_id is None:
            return
        seq, epoch = self._seq, self._session.epoch
        self._set_busy(True)

        def work(c: BackendClient):
            api = EditApi(c)
            _, current = api.project_revision(project_id)
            if current != etag:
                raise BackendError("PROJECT_CHANGED",
                                   "The project changed elsewhere since it was loaded. Reload before editing.")
            for op in ops:
                api.run(project_id, op)
            timeline = api.timeline(project_id)
            raw, new_etag = api.project_revision(project_id)
            return timeline, raw, new_etag

        def done(result, error):
            if self._stale(epoch, seq):
                return
            self._set_busy(False)
            if error:
                # Whatever happened, the backend may now differ from what Studio holds: the
                # undo history no longer describes it, so drop it and let the page reload.
                refused = error[0] in ("INVALID_REQUEST", "VALIDATION_ERROR") and len(ops) == 1
                if not refused:
                    self._clear_history()
                if error[0] == "PROJECT_CHANGED":
                    self.conflict.emit(error[1])
                self.failed.emit("edit", *error)
                if not refused:
                    self.load(project_id)  # show what the backend really holds now
                return
            self.timeline, self._raw, self._etag = result
            self._series.clear()
            if direction == "do":
                self._undo.append(edit)
                self._redo.clear()
            elif direction == "undo":
                self._redo.append(self._undo.pop())
            else:
                self._undo.append(self._redo.pop())
            self.history_changed.emit()
            self.edited.emit(self.timeline)

        self._run(client, work, done)
