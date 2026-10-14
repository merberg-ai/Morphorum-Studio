"""Animation render operations (S3.2): durable start, watching, resume, frames and previews.

Same rules as the Image Lab service: the request is journalled before the POST, job state comes
from REST GETs (the backend's answer always wins), and results from an older connection are
discarded. Unlike an image job, a render outlives the backend process: after a restart it shows up
as ``interrupted`` and can be resumed from the frames already on disk.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.images import DEFINITIVE, JournalEntry, SubmissionJournal
from morphorum_studio.backend.projects import ProjectsApi
from morphorum_studio.backend.renders import RenderApi, RenderJob
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.validation import ValidationApi, summary
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner

POLL_MS = 1000
POLL_SLOW_MS = 3000
GIVE_UP_AFTER = 8
KIND = "animation"


class RenderService(QObject):
    list_ready = Signal(str, object)  # project id, tuple[RenderJob]
    submitted = Signal(object, object)  # JournalEntry, RenderJob
    job_updated = Signal(object)  # RenderJob (authoritative)
    pending_ready = Signal(object)  # list[JournalEntry] whose POST outcome is unknown
    frame_ready = Signal(str, int, object)  # render id, frame, PNG bytes | None
    preview_ready = Signal(str, object)  # render id, GIF bytes | None
    copy_saved = Signal(str)
    failed = Signal(str, str, str)  # operation, code, message
    busy_changed = Signal(bool)
    cleared = Signal()

    def __init__(self, session: BackendSession, journal: SubmissionJournal,
                 parent: QObject | None = None, runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._journal = journal
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._busy = False
        self._watched: str | None = None
        self._polling = False
        self._failures = 0
        self._list_seq = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.poll_now)
        session.changed.connect(self._session_changed)

    # -- state --------------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._session.state == "connected" and self._session.feature("animation_render")

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def watched(self) -> str | None:
        return self._watched

    @property
    def profile_id(self) -> str | None:
        info = self._session.info
        return info.profile_id if info else None

    def _client(self, timeout: float = 10.0) -> BackendClient | None:
        return self._session.client(timeout=timeout) if self.available else None

    def _stale(self, epoch: int) -> bool:
        return epoch != self._session.epoch or self._session.state == "offline"

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._timer.stop()
            self._watched = None
            self._polling = False
            self._failures = 0
            self._list_seq += 1
            self._set_busy(False)
            self.cleared.emit()
        elif self._session.state != "connected":
            self._timer.stop()
        elif self._watched and not self._timer.isActive() and not self._polling:
            self._timer.start(POLL_MS)

    # -- listing ------------------------------------------------------------------------

    def load_list(self, project_id: str) -> None:
        client = self._client()
        if client is None:
            return
        self._list_seq += 1
        seq, epoch = self._list_seq, self._session.epoch

        def done(result, error):
            if self._stale(epoch) or seq != self._list_seq:
                return
            if error:
                self.failed.emit("list", *error)
            else:
                self.list_ready.emit(project_id, result)

        self._run(client, lambda c: RenderApi(c).for_project(project_id), done)

    # -- starting -----------------------------------------------------------------------

    def start(self, project_id: str) -> None:
        """Read the complete saved project, journal it, then ask the backend to render it."""
        profile = self.profile_id
        client = self._client(30.0)
        if profile is None or client is None or self._busy:
            return
        self._set_busy(True)
        epoch = self._session.epoch
        held: dict[str, JournalEntry] = {}

        def work(c: BackendClient):
            project = ProjectsApi(c).raw(project_id)
            try:
                verdict = ValidationApi(c).check(project)
            except BackendError as exc:
                if exc.code != "NOT_FOUND":  # an older backend without the endpoint just skips this
                    raise
            else:
                if not verdict.valid:
                    raise BackendError("INVALID_REQUEST",
                                       "Fix the schedule errors before rendering: " + summary(verdict))
            entry = self._journal.begin(profile, {"project": project}, kind=KIND)
            held["entry"] = entry
            job = RenderApi(c).submit(entry)
            self._journal.submitted(entry, job.id)
            return entry, job

        def done(result, error):
            if self._stale(epoch):
                return
            self._set_busy(False)
            if error:
                self._after_failed_post(held.get("entry"), error)
                return
            entry, job = result
            self.submitted.emit(entry, job)
            self.watch(job.id, first=job)

        self._run(client, work, done)

    def retry(self, entry: JournalEntry) -> None:
        """Resend an unfinished entry with its original key and project body."""
        client = self._client(30.0)
        if client is None or self._busy or entry.profile_id != self.profile_id:
            return
        self._set_busy(True)
        epoch = self._session.epoch

        def work(c: BackendClient):
            job = RenderApi(c).submit(entry)
            self._journal.submitted(entry, job.id)
            return job

        def done(result, error):
            if self._stale(epoch):
                return
            self._set_busy(False)
            if error:
                self._after_failed_post(entry, error)
                return
            self.submitted.emit(entry, result)
            self.watch(result.id, first=result)

        self._run(client, work, done)

    def _after_failed_post(self, entry: JournalEntry | None, error: tuple[str, str]) -> None:
        if entry is not None:
            if error[0] in DEFINITIVE:
                self._journal.finish(entry.key)  # Refused: nothing started, nothing to recover.
            else:
                self.pending_ready.emit(self._journal.entries(self.profile_id, KIND))
        self.failed.emit("start", *error)

    def discard(self, key: str) -> None:
        self._journal.finish(key)

    def check_pending(self) -> None:
        """Reconcile journal entries after a restart, an outage or a backend restart."""
        profile = self.profile_id
        client = self._client()
        if profile is None or client is None:
            return
        entries = self._journal.entries(profile, KIND)
        unknown = [e for e in entries if e.state == "pending"]
        known = [e for e in entries if e.state == "submitted" and e.job_id]
        epoch = self._session.epoch

        def work(c: BackendClient):
            api = RenderApi(c)
            resume: RenderJob | None = None
            for entry in known:
                try:
                    job = api.get(entry.job_id)
                except BackendError as exc:
                    if exc.code == "NOT_FOUND":
                        self._journal.finish(entry.key)
                    continue
                if job.final:
                    self._journal.finish(entry.key)
                elif resume is None:
                    resume = job
            return resume

        def done(result, error):
            if self._stale(epoch):
                return
            if unknown:
                self.pending_ready.emit(unknown)
            if result is not None and self._watched is None:
                self.watch(result.id, first=result)

        if known:
            self._run(client, work, done)
        elif unknown:
            self.pending_ready.emit(unknown)

    # -- watching -----------------------------------------------------------------------

    def watch(self, render_id: str, first: RenderJob | None = None) -> None:
        self._watched = render_id
        self._failures = 0
        self._timer.stop()
        if first is not None:
            self.job_updated.emit(first)
            if first.final:
                self._finished(first)
                return
        self.poll_now()

    def stop_watching(self) -> None:
        self._watched = None
        self._timer.stop()

    def poll_now(self) -> None:
        render_id = self._watched
        client = self._client()
        if render_id is None or client is None or self._polling:
            return
        self._polling = True
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            self._polling = False
            if render_id != self._watched:
                return
            if error:
                self._failures += 1
                if error[0] == "NOT_FOUND" or self._failures >= GIVE_UP_AFTER:
                    self._watched = None
                    self.failed.emit("job", *error)
                    return
                self._timer.start(POLL_SLOW_MS)
                return
            self._failures = 0
            self.job_updated.emit(result)
            if result.final:
                self._finished(result)
            else:
                self._timer.start(POLL_MS if result.status == "rendering" else POLL_SLOW_MS)

        self._run(client, lambda c: RenderApi(c).get(render_id), done)

    def _finished(self, job: RenderJob) -> None:
        self._watched = None
        self._timer.stop()
        for entry in self._journal.entries(self.profile_id, KIND):
            if entry.job_id == job.id:
                self._journal.finish(entry.key)

    # -- controls -----------------------------------------------------------------------

    def cancel(self, render_id: str) -> None:
        client = self._client()
        if client is None:
            return
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            if error:
                self.failed.emit("cancel", *error)
            else:
                self.job_updated.emit(result)
                if result.final:
                    self._finished(result)
                elif self._watched == render_id:
                    self.poll_now()

        self._run(client, lambda c: RenderApi(c).cancel(render_id), done)

    def resume(self, project_id: str, render_id: str) -> None:
        client = self._client()
        if client is None or self._busy:
            return
        self._set_busy(True)
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            self._set_busy(False)
            if error:
                self.failed.emit("resume", *error)
            else:
                self.watch(result.id, first=result)

        self._run(client, lambda c: RenderApi(c).resume(project_id, render_id), done)

    # -- frames, previews, copies -------------------------------------------------------

    def fetch_frame(self, project_id: str, render_id: str, frame: int) -> None:
        client = self._client(30.0)
        if client is None:
            return
        epoch = self._session.epoch

        def done(result, error):
            if not self._stale(epoch):
                self.frame_ready.emit(render_id, frame, None if error else result)

        self._run(client, lambda c: RenderApi(c).frame_bytes(project_id, render_id, frame), done)

    def fetch_preview(self, project_id: str, render_id: str) -> None:
        client = self._client(60.0)
        if client is None:
            return
        epoch = self._session.epoch

        def done(result, error):
            if not self._stale(epoch):
                self.preview_ready.emit(render_id, None if error else result)

        self._run(client, lambda c: RenderApi(c).preview_bytes(project_id, render_id), done)

    def save_frame(self, project_id: str, render_id: str, frame: int, destination: str) -> None:
        self._save(lambda c: RenderApi(c).save_frame(project_id, render_id, frame, destination))

    def save_preview(self, project_id: str, render_id: str, destination: str) -> None:
        self._save(lambda c: RenderApi(c).save_preview(project_id, render_id, destination))

    def _save(self, fn: Any) -> None:
        client = self._client(60.0)
        if client is None:
            return
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            if error:
                self.failed.emit("copy", *error)
            else:
                self.copy_saved.emit(result)

        self._run(client, fn, done)
