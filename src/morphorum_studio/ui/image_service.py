"""Image Lab operations (S3.1): setup data, durable submission, job watching, results.

Submissions are journalled before the POST (see ``backend.images``). A job being watched is polled
over plain REST once a second (once every few seconds while the backend is struggling) and the
authoritative GET result always wins. Results from an older connection are discarded.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from morphorum_studio.backend.api import ReadApi
from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.images import (
    DEFINITIVE,
    ImageJob,
    ImagesApi,
    JournalEntry,
    SubmissionJournal,
)
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner

POLL_MS = 1000
POLL_SLOW_MS = 4000
GIVE_UP_AFTER = 8


class ImageLabService(QObject):
    setup_ready = Signal(object, object, object)  # checkpoints, loras, {family: FamilyDefaults}
    submitted = Signal(object, object)  # JournalEntry, ImageJob
    job_updated = Signal(object)  # ImageJob (authoritative)
    recent_ready = Signal(object)  # tuple[ImageJob]
    pending_ready = Signal(object)  # list[JournalEntry] whose POST outcome is unknown
    image_ready = Signal(str, str, object)  # job id, filename, PNG bytes | None
    copy_saved = Signal(str)
    failed = Signal(str, str, str)  # operation, code, message
    busy_changed = Signal(bool)  # a submission is in flight
    cleared = Signal()

    def __init__(self, session: BackendSession, journal: SubmissionJournal,
                 parent: QObject | None = None, runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._journal = journal
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._submitting = False
        self._watched: str | None = None
        self._polling = False
        self._failures = 0
        self._setup_seq = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.poll_now)
        session.changed.connect(self._session_changed)

    # -- state --------------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._session.state == "connected" and self._session.feature("sdxl_generation")

    @property
    def submitting(self) -> bool:
        return self._submitting

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

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._timer.stop()
            self._watched = None
            self._polling = False
            self._failures = 0
            self._setup_seq += 1
            if self._submitting:
                self._submitting = False
                self.busy_changed.emit(False)
            self.cleared.emit()
        elif self._session.state != "connected":
            self._timer.stop()
        elif self._watched and not self._timer.isActive() and not self._polling:
            self._timer.start(POLL_MS)  # back online: resume watching

    # -- setup --------------------------------------------------------------------------

    def load_setup(self) -> None:
        client = self._client()
        if client is None or not self._session.feature("model_discovery"):
            return
        self._setup_seq += 1
        seq, epoch = self._setup_seq, self._session.epoch

        def work(c: BackendClient):
            api = ReadApi(c)
            return (api.models(kind="checkpoints"), api.models(kind="loras"),
                    api.generation_defaults())

        def done(result, error):
            if self._stale(epoch) or seq != self._setup_seq:
                return
            if error:
                self.failed.emit("setup", *error)
            else:
                self.setup_ready.emit(*result)

        self._run(client, work, done)

    def load_recent(self) -> None:
        client = self._client()
        if client is None:
            return
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            if error:
                self.failed.emit("recent", *error)
            else:
                self.recent_ready.emit(result)

        self._run(client, lambda c: ImagesApi(c).recent(20), done)

    # -- journal ------------------------------------------------------------------------

    def check_pending(self) -> None:
        """Reconcile unfinished journal entries for this connection after a restart or outage."""
        profile = self.profile_id
        client = self._client()
        if profile is None or client is None:
            return
        entries = self._journal.entries(profile)
        unknown = [e for e in entries if e.state == "pending"]
        known = [e for e in entries if e.state == "submitted" and e.job_id]
        epoch = self._session.epoch

        def work(c: BackendClient):
            api = ImagesApi(c)
            resume = None
            for entry in known:
                try:
                    job = api.job(entry.job_id)
                except BackendError as exc:
                    if exc.code == "NOT_FOUND":
                        self._journal.finish(entry.key)  # The backend no longer has it.
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
                self.watch(result.id)

        if known:
            self._run(client, work, done)
        elif unknown:
            self.pending_ready.emit(unknown)

    def discard(self, key: str) -> None:
        self._journal.finish(key)

    # -- submission ---------------------------------------------------------------------

    def submit(self, payload: dict) -> None:
        profile = self.profile_id
        if profile is None or not self.available or self._submitting:
            return
        try:
            entry = self._journal.begin(profile, payload)
        except (OSError, ValueError) as exc:
            self.failed.emit("submit", "JOURNAL_ERROR", f"Could not record the submission: {exc}")
            return
        self._post(entry)

    def retry(self, entry: JournalEntry) -> None:
        """Send an unfinished entry again with its original key and body."""
        if self.available and not self._submitting and entry.profile_id == self.profile_id:
            self._post(entry)

    def _post(self, entry: JournalEntry) -> None:
        client = self._client(20.0)
        if client is None:
            return
        self._submitting = True
        self.busy_changed.emit(True)
        epoch = self._session.epoch

        def work(c: BackendClient):
            job = ImagesApi(c).submit(entry)
            self._journal.submitted(entry, job.id)
            return job

        def done(result, error):
            if self._stale(epoch):
                return
            self._submitting = False
            self.busy_changed.emit(False)
            if error:
                if error[0] in DEFINITIVE:
                    self._journal.finish(entry.key)  # The backend refused it; nothing to recover.
                else:
                    self.pending_ready.emit(self._journal.entries(self.profile_id))
                self.failed.emit("submit", *error)
                return
            self.submitted.emit(entry, result)
            self.watch(result.id, first=result)

        self._run(client, work, done)

    # -- watching -----------------------------------------------------------------------

    def watch(self, job_id: str, first: ImageJob | None = None) -> None:
        self._watched = job_id
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
        job_id = self._watched
        client = self._client()
        if job_id is None or client is None or self._polling:
            return
        self._polling = True
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            self._polling = False
            if job_id != self._watched:
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
                self._timer.start(POLL_SLOW_MS if result.status == "queued" else POLL_MS)

        self._run(client, lambda c: ImagesApi(c).job(job_id), done)

    def _finished(self, job: ImageJob) -> None:
        self._watched = None
        self._timer.stop()
        for entry in self._journal.entries(self.profile_id):
            if entry.job_id == job.id:
                self._journal.finish(entry.key)

    def cancel(self, job_id: str) -> None:
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
                elif self._watched == job_id:
                    self.poll_now()

        self._run(client, lambda c: ImagesApi(c).cancel(job_id), done)

    # -- results ------------------------------------------------------------------------

    def fetch_image(self, job_id: str, filename: str) -> None:
        client = self._client(30.0)
        if client is None:
            return
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            self.image_ready.emit(job_id, filename, None if error else result)

        self._run(client, lambda c: ImagesApi(c).image_bytes(job_id, filename), done)

    def save_copy(self, job_id: str, filename: str, destination: str) -> None:
        client = self._client(60.0)
        if client is None:
            return
        epoch = self._session.epoch

        def done(result: Any, error):
            if self._stale(epoch):
                return
            if error:
                self.failed.emit("copy", *error)
            else:
                self.copy_saved.emit(result)

        self._run(client, lambda c: ImagesApi(c).save_copy(job_id, filename, destination), done)
