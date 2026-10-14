"""Audio analysis for the Motion Lab (S5.2a): send a WAV to the backend, or recover a project's
earlier one by its hash. Answers for an older project or connection are dropped."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from morphorum_studio.backend.audio import AudioAnalysis, AudioApi
from morphorum_studio.backend.client import BackendClient
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import Runner, thread_pool_runner


class AudioService(QObject):
    analyzed = Signal(object, str)  # AudioAnalysis, where the sound file for playback is ("" if none)
    failed = Signal(str, str, str)  # operation, code, message
    busy_changed = Signal(bool)
    cleared = Signal()

    def __init__(self, session: BackendSession, cache_dir: Path | str | None = None,
                 parent: QObject | None = None, runner: Runner | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._run = runner or thread_pool_runner(self)
        self._cache = Path(cache_dir) if cache_dir else None
        self._epoch = session.epoch
        self._seq = 0
        self._busy = False
        self._project_id: str | None = None
        self._analyses: dict[str, AudioAnalysis] = {}
        self._wavs: dict[str, str] = {}  # hash -> playable file on this PC
        session.changed.connect(self._session_changed)

    @property
    def available(self) -> bool:
        return self._session.state == "connected" and self._session.feature("timeline")

    @property
    def busy(self) -> bool:
        return self._busy

    def analysis(self, sha256: str) -> AudioAnalysis | None:
        return self._analyses.get(sha256)

    def playable(self, sha256: str) -> str:
        return self._wavs.get(sha256, "")

    def remember_file(self, sha256: str, path: str) -> None:
        self._wavs[sha256] = path

    def set_project(self, project_id: str | None) -> None:
        if project_id != self._project_id:
            self._seq += 1
            self._project_id = project_id
            self._analyses.clear()
            self._wavs.clear()
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _stale(self, epoch: int, seq: int) -> bool:
        return (epoch != self._session.epoch or self._session.state == "offline"
                or seq != self._seq)

    def _session_changed(self) -> None:
        if self._session.epoch != self._epoch:
            self._epoch = self._session.epoch
            self._seq += 1
            self._analyses.clear()
            self._wavs.clear()
            self._set_busy(False)
            self.cleared.emit()

    # -- calls ----------------------------------------------------------------------------

    def analyze(self, wav: bytes, local_file: str = "") -> None:
        """Have the backend measure these WAV bytes. ``local_file`` is kept for playback."""
        self._start("analyze", lambda c, p: AudioApi(c).analyze(p, wav),
                    lambda analysis: self._remember(analysis, local_file))

    def recover(self, sha256: str) -> None:
        """Fetch the project's stored WAV for ``sha256`` and analyse it again (same result)."""
        if sha256 in self._analyses:
            self.analyzed.emit(self._analyses[sha256], self._wavs.get(sha256, ""))
            return
        cache = self._cache

        def work(c: BackendClient, project_id: str):
            api = AudioApi(c)
            wav = api.fetch_wav(project_id, sha256)
            analysis = api.analyze(project_id, wav)
            path = ""
            if cache is not None:
                try:
                    cache.mkdir(parents=True, exist_ok=True)
                    target = cache / f"{analysis.sha256}.wav"
                    target.write_bytes(wav)
                    path = str(target)
                except OSError:
                    path = ""
            return analysis, path

        self._start("recover", work, lambda result: self._remember(*result))

    def _remember(self, analysis: AudioAnalysis, path: str) -> None:
        self._analyses[analysis.sha256] = analysis
        if path:
            self._wavs[analysis.sha256] = path
        self.analyzed.emit(analysis, self._wavs.get(analysis.sha256, ""))

    def _start(self, operation: str, work, on_result) -> None:
        client = self._session.client(timeout=120.0) if self.available else None
        project_id = self._project_id
        if client is None or project_id is None:
            return
        seq, epoch = self._seq, self._session.epoch
        self._set_busy(True)

        def done(result, error):
            if self._stale(epoch, seq):
                return
            self._set_busy(False)
            if error:
                self.failed.emit(operation, *error)
            else:
                on_result(result)

        self._run(client, lambda c: work(c, project_id), done)
