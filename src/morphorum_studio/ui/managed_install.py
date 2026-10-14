"""Installs the Morphorum backend into the managed folder by running the backend's own installer.

Studio downloads the backend's ``scripts/bootstrap.ps1`` for the chosen branch and runs it with
the folder, branch and port already answered, so it never waits for input. Studio writes only
to the folder the person chose. Cancelling stops the installer; running Install again resumes.
"""
from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from morphorum_studio.backend import managed
from morphorum_studio.ui.managed_backend import KEEP_LINES, _environment, new_process

IDLE, DOWNLOADING, RUNNING, SUCCEEDED, FAILED, CANCELLED = (
    "idle", "downloading", "running", "succeeded", "failed", "cancelled")
FAIL_TEXT = "INSTALLATION FAILED"


def kill_tree(process: QProcess) -> None:
    """End the installer and everything it started (pip, git, winget)."""
    pid = int(process.processId() or 0)
    if os.name == "nt" and pid:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                           creationflags=0x08000000)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    process.kill()


class InstallDriver(QObject):
    state_changed = Signal(str, str)  # state, plain-language detail
    stage = Signal(str)  # the installer's current section
    log_line = Signal(str)
    finished = Signal(bool, str)  # ok, message
    _downloaded = Signal(str)  # '' when fine, otherwise the reason (from the download thread)

    def __init__(self, work_dir: Path | None = None, process_factory: Callable[[], QProcess] = new_process,
                 fetch: Callable[[str, Path], None] = managed.fetch_bootstrap,
                 killer: Callable[[QProcess], None] = kill_tree, threaded: bool = True,
                 checker: Callable[..., managed.Preflight] = managed.preflight,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work_dir or managed.default_settings_path().with_name("install")
        self._factory, self._fetch, self._kill, self._threaded = process_factory, fetch, killer, threaded
        self._check = checker
        self.state, self.detail, self.section = IDLE, "", ""
        self.failure_seen = False
        self._process: QProcess | None = None
        self._plan: tuple[str, str, int] | None = None
        self._cancelled = False
        self._partial = ""
        self.lines: list[str] = []
        self._downloaded.connect(self._after_download)

    @property
    def busy(self) -> bool:
        return self.state in (DOWNLOADING, RUNNING)

    def _set(self, state: str, detail: str = "") -> None:
        self.state, self.detail = state, detail
        self.state_changed.emit(state, detail)

    def _say(self, line: str) -> None:
        self.lines.append(line)
        del self.lines[:-KEEP_LINES]
        self.log_line.emit(line)

    # -- start --------------------------------------------------------------------------

    def start(self, folder: str, branch: str, port: int) -> bool:
        """Begin installing. Refuses unless the preflight passes; the caller has the person's consent."""
        if self.busy:
            return False
        check = self._check(folder, port, branch)
        if not check.ok:
            self._set(FAILED, " ".join(check.problems))
            self.finished.emit(False, self.detail)
            return False
        self._plan, self._cancelled, self._partial, self.failure_seen = (folder, branch, int(port)), False, "", False
        self.lines.clear()
        self.section = ""
        self._set(DOWNLOADING, "Downloading the installer…")
        self._say("Downloading the Morphorum installer for branch " + branch)
        url, script = managed.bootstrap_url(branch), self._work / "bootstrap.ps1"
        if self._threaded:
            threading.Thread(target=self._download, args=(url, script), daemon=True).start()
        else:
            self._download(url, script)
        return True

    def _download(self, url: str, script: Path) -> None:
        try:
            self._fetch(url, script)
            reason = ""
        except OSError as exc:
            reason = str(exc) or "The installer could not be downloaded."
        self._downloaded.emit(reason)

    def _after_download(self, reason: str) -> None:
        if self._cancelled or self._plan is None:
            return
        if reason:
            self._end(FAILED, reason)
            return
        folder, branch, port = self._plan
        program, args = managed.install_command(self._work / "bootstrap.ps1", Path(folder), branch, port)
        process = self._factory()
        process.setProgram(program)
        process.setArguments(args)
        process.setProcessEnvironment(_environment(dict(os.environ)))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._exited)
        process.errorOccurred.connect(self._failed_to_start)
        self._process = process
        self._set(RUNNING, "Installing Morphorum. This can take 10 to 30 minutes.")
        process.start()
        try:
            process.closeWriteChannel()  # nothing should ask a question; if it does it fails instead of hanging
        except Exception:
            pass

    # -- output -------------------------------------------------------------------------

    def _read(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        text = self._partial + chunk.replace("\r\n", "\n").replace("\r", "\n")
        *complete, self._partial = text.split("\n")
        for raw in complete:
            self._line(raw)

    def _line(self, raw: str) -> None:
        kind, text = managed.parse_install_line(raw)
        if not text:
            return
        self._say(text if kind == managed.KIND_TEXT else raw.strip())
        if kind == managed.KIND_SECTION:
            self.section = text.title() if text.isupper() else text
            self.stage.emit(self.section)
        elif kind == managed.KIND_FAIL and FAIL_TEXT in text.upper():
            self.failure_seen = True

    # -- ending -------------------------------------------------------------------------

    def _failed_to_start(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self._process = None
            self._end(FAILED, "Windows PowerShell could not be started, so the installer cannot run.")

    def _exited(self, code: int, _status=None) -> None:
        self._read()
        if self._partial.strip():
            self._line(self._partial)
        self._partial, self._process = "", None
        if self._cancelled:
            self._end(CANCELLED, "Installation cancelled. Install again to continue where it stopped.")
        elif code == 0 and not self.failure_seen and self._plan and managed.check_folder(self._plan[0]).ok:
            self._end(SUCCEEDED, "Morphorum is installed.")
        elif code == 0 and not self.failure_seen:
            self._end(FAILED, "The installer finished but the folder is not a complete Morphorum install. "
                              "See the output.")
        else:
            self._end(FAILED, f"The installer stopped with an error (code {code}). See the output; "
                              "Install again resumes after the cause is fixed.")

    def cancel(self) -> None:
        if not self.busy:
            return
        self._cancelled = True
        if self._process is not None:
            self._set(RUNNING, "Cancelling…")
            self._kill(self._process)
        else:
            self._end(CANCELLED, "Installation cancelled.")

    def _end(self, state: str, message: str) -> None:
        self._set(state, message)
        self.finished.emit(state == SUCCEEDED, message)
