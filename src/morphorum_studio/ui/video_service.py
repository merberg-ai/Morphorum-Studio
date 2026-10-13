"""Video export operations (S3.3): availability, durable start, watching, verified downloads.

Same rules as the render service: the request is journalled before the POST (so a retry reuses
the same idempotency key), job state comes from REST GETs, and answers from an older connection
are dropped. Playback copies are downloaded and verified first, then played from a local cache.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.images import DEFINITIVE, JournalEntry, SubmissionJournal
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.backend.videos import (
    VideoApi,
    VideoAvailability,
    VideoExport,
    cached_video,
    prune_cache,
)
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner

POLL_MS = 1000
GIVE_UP_AFTER = 8
KIND = "video"


class VideoService(QObject):
    availability_ready = Signal(object)  # VideoAvailability | None
    list_ready = Signal(str, str, object)  # project, render, tuple[VideoExport]
    export_updated = Signal(object)  # VideoExport
    pending_ready = Signal(object)  # list[JournalEntry]
    copy_saved = Signal(str)
    playback_ready = Signal(object, str)  # VideoExport, local path
    failed = Signal(str, str, str)
    busy_changed = Signal(bool)
    cleared = Signal()

    def __init__(self, session: BackendSession, journal: SubmissionJournal, cache_dir: str | Path,
                 parent: QObject | None = None, runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._journal = journal
        self._cache = Path(cache_dir)
        self._run = runner or thread_pool_runner(self)
        self._epoch = session.epoch
        self._busy = False
        self._watched: str | None = None
        self._polling = False
        self._failures = 0
        self._seq = 0
        self.availability: VideoAvailability | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.poll_now)
        session.changed.connect(self._session_changed)

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
            self._seq += 1
            self.availability = None
            self._set_busy(False)
            self.cleared.emit()
        elif self._session.state != "connected":
            self._timer.stop()
        elif self._watched and not self._timer.isActive() and not self._polling:
            self._timer.start(POLL_MS)

    # -- availability and listing -------------------------------------------------------

    def load_availability(self) -> None:
        client = self._client()
        if client is None:
            return
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            self.availability = None if error else result
            if error:
                self.failed.emit("availability", *error)
            self.availability_ready.emit(self.availability)

        self._run(client, lambda c: VideoApi(c).availability(), done)

    def load_list(self, project_id: str, render_id: str) -> None:
        client = self._client()
        if client is None:
            return
        self._seq += 1
        seq, epoch = self._seq, self._session.epoch

        def done(result, error):
            if self._stale(epoch) or seq != self._seq:
                return
            if error:
                self.failed.emit("list", *error)
            else:
                self.list_ready.emit(project_id, render_id, result)

        self._run(client, lambda c: VideoApi(c).exports(project_id, render_id), done)

    # -- starting -----------------------------------------------------------------------

    def start(self, project_id: str, render_id: str, fmt: str, quality: str, fps: int | None) -> None:
        profile = self.profile_id
        client = self._client(30.0)
        if profile is None or client is None or self._busy:
            return
        body: dict = {"format": fmt, "quality": quality}
        if fps is not None:
            body["fps"] = fps
        self._set_busy(True)
        epoch = self._session.epoch
        held: dict[str, JournalEntry] = {}

        def work(c: BackendClient):
            entry = self._journal.begin(
                profile, {"project_id": project_id, "render_id": render_id, "body": body}, kind=KIND)
            held["entry"] = entry
            export = VideoApi(c).start(entry)
            if export.id:
                self._journal.submitted(entry, export.id)
            return entry, export

        self._run(client, work, lambda r, e: self._started(epoch, held, r, e))

    def retry(self, entry: JournalEntry) -> None:
        client = self._client(30.0)
        if client is None or self._busy or entry.profile_id != self.profile_id:
            return
        self._set_busy(True)
        epoch = self._session.epoch

        def work(c: BackendClient):
            export = VideoApi(c).start(entry)
            if export.id:
                self._journal.submitted(entry, export.id)
            return entry, export

        self._run(client, work, lambda r, e: self._started(epoch, {"entry": entry}, r, e))

    def _started(self, epoch: int, held: dict, result, error) -> None:
        if self._stale(epoch):
            return
        self._set_busy(False)
        entry = held.get("entry")
        if error:
            if entry is not None:
                if error[0] in DEFINITIVE:
                    self._journal.finish(entry.key)
                else:
                    self.pending_ready.emit(self._journal.entries(self.profile_id, KIND))
            self.failed.emit("start", *error)
            return
        _entry, export = result
        self.watch(export)

    def discard(self, key: str) -> None:
        self._journal.finish(key)

    def check_pending(self) -> None:
        """Entries whose POST outcome is unknown can be retried safely with their original key."""
        profile = self.profile_id
        if profile is None:
            return
        unknown = [e for e in self._journal.entries(profile, KIND) if e.state == "pending"]
        if unknown:
            self.pending_ready.emit(unknown)

    # -- watching -----------------------------------------------------------------------

    def watch(self, export: VideoExport) -> None:
        self.export_updated.emit(export)
        if export.final or not export.id:
            self._finished(export)
            return
        self._watched = export.id
        self._failures = 0
        self._timer.stop()
        self.poll_now()

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
                self._timer.start(POLL_MS * 3)
                return
            self._failures = 0
            self.export_updated.emit(result)
            if result.final:
                self._finished(result)
            else:
                self._timer.start(POLL_MS)

        self._run(client, lambda c: VideoApi(c).job(job_id), done)

    def _finished(self, export: VideoExport) -> None:
        if export.id and self._watched == export.id:
            self._watched = None
        self._timer.stop()
        for entry in self._journal.entries(self.profile_id, KIND):
            if entry.job_id == export.id:
                self._journal.finish(entry.key)

    # -- files --------------------------------------------------------------------------

    def save(self, export: VideoExport, destination: str) -> None:
        client = self._client(600.0)
        if client is None or not export.downloadable:
            return
        epoch = self._session.epoch

        def done(result, error):
            if self._stale(epoch):
                return
            if error:
                self.failed.emit("copy", *error)
            else:
                self.copy_saved.emit(result)

        self._run(client, lambda c: VideoApi(c).download(export, destination), done)

    def prepare_playback(self, export: VideoExport) -> None:
        """Verified local copy in the cache (reused when still intact), then ``playback_ready``."""
        if not export.downloadable:
            return
        local = cached_video(self._cache, export)
        if local is not None:
            self.playback_ready.emit(export, str(local))
            return
        client = self._client(600.0)
        if client is None:
            return
        epoch = self._session.epoch
        target = self._cache / f"{export.sha256[:24]}.{export.format}"  # type: ignore[index]

        def work(c: BackendClient):
            try:
                self._cache.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise BackendError("FILE_ERROR", "Could not create the playback cache") from exc
            path = VideoApi(c).download(export, target)
            prune_cache(self._cache)
            return path

        def done(result, error):
            if self._stale(epoch):
                return
            if error:
                self.failed.emit("playback", *error)
            else:
                self.playback_ready.emit(export, result)

        self._run(client, work, done)
