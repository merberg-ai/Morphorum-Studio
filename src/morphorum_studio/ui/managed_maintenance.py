"""Runs the maintenance jobs for the managed backend folder: update check, update, branch switch,
repair, health check and removal. One job at a time. The update and repair jobs are the backend's
own guarded scripts; Studio only starts them and shows their output.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from morphorum_studio.backend import maintenance as mt
from morphorum_studio.ui.managed_backend import KEEP_LINES, _environment, new_process
from morphorum_studio.ui.managed_install import kill_tree

CHECK, UPDATE, SWITCH, REPAIR, DOCTOR, REMOVE = "check", "update", "switch", "repair", "doctor", "remove"
LABELS = {CHECK: "Update check", UPDATE: "Update", SWITCH: "Branch switch", REPAIR: "Repair",
          DOCTOR: "Health check", REMOVE: "Removal"}
FAILURE_MARKERS = ("[X]", "UPDATE FAILED", "REPAIR FAILED", "INSTALLATION FAILED")


class MaintenanceDriver(QObject):
    busy_changed = Signal(bool)
    log_line = Signal(str)
    checked = Signal(object)  # GitStatus
    doctor_done = Signal(object, str)  # DoctorReport or None, message
    finished = Signal(str, bool, str)  # job, ok, plain-language message
    _from_thread = Signal(str, object)

    def __init__(self, process_factory: Callable[[], QProcess] = new_process,
                 checker: Callable[[str], mt.GitStatus] = mt.check_updates,
                 remover: Callable[[str], None] = mt.remove_tree,
                 killer: Callable[[QProcess], None] = kill_tree, threaded: bool = True,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._factory, self._check, self._remove, self._kill = process_factory, checker, remover, killer
        self._threaded = threaded
        self.job = ""
        self.lines: list[str] = []
        self._process: QProcess | None = None
        self._partial = ""
        self._output = ""
        self._failure_seen = False
        self._cancelled = False
        self._from_thread.connect(self._thread_result)

    @property
    def busy(self) -> bool:
        return bool(self.job)

    def _begin(self, job: str) -> bool:
        if self.job:
            return False
        self.job, self._failure_seen, self._cancelled, self._partial, self._output = job, False, False, "", ""
        self.lines.clear()
        self.busy_changed.emit(True)
        return True

    def _end(self, ok: bool, message: str) -> None:
        job, self.job = self.job, ""
        self._process = None
        self.busy_changed.emit(False)
        self.finished.emit(job, ok, message)

    def _say(self, line: str) -> None:
        self.lines.append(line)
        del self.lines[:-KEEP_LINES]
        self.log_line.emit(line)

    # -- jobs run off the UI thread ----------------------------------------------------

    def _spawn(self, kind: str, work: Callable[[], object]) -> None:
        def body() -> None:
            try:
                result: object = work()
            except (OSError, ValueError) as exc:
                result = exc
            self._from_thread.emit(kind, result)

        if self._threaded:
            threading.Thread(target=body, daemon=True).start()
        else:
            body()

    def _thread_result(self, kind: str, result: object) -> None:
        if kind != self.job:
            return
        if kind == CHECK:
            status = result if isinstance(result, mt.GitStatus) else mt.GitStatus(error="The check failed.")
            self.checked.emit(status)
            self._end(not status.error, status.error or "Checked.")
        elif isinstance(result, Exception):
            reason = getattr(result, "strerror", None) or str(result) or "It could not be removed."
            self._end(False, f"Some files could not be removed: {reason}. Close anything using the folder and try again.")
        else:
            self._end(True, "The folder was removed.")

    def check_for_updates(self, folder: str) -> bool:
        if not self._begin(CHECK):
            return False
        self._spawn(CHECK, lambda: self._check(folder))
        return True

    def remove(self, folder: str) -> bool:
        """Delete the folder. The caller has already confirmed and made sure the backend is stopped."""
        if mt.removal_problems(folder) or not self._begin(REMOVE):
            return False
        self._say("Removing " + folder)
        self._spawn(REMOVE, lambda: self._remove(folder))
        return True

    # -- jobs that run a program -----------------------------------------------------------

    def _run(self, job: str, program: str, args: list[str], cwd: str) -> bool:
        if not self._begin(job):
            return False
        process = self._factory()
        process.setProgram(program)
        process.setArguments(args)
        process.setWorkingDirectory(cwd)
        process.setProcessEnvironment(_environment(dict(os.environ)))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._exited)
        process.errorOccurred.connect(self._failed_to_start)
        self._process = process
        self._say(f"{LABELS[job]} started.")
        process.start()
        try:
            process.closeWriteChannel()
        except Exception:
            pass
        return True

    def update(self, folder: str, branch: str | None = None) -> bool:
        try:
            program, args = mt.update_command(Path(folder), branch)
        except ValueError as exc:
            self._say(str(exc))
            return False
        return self._run(SWITCH if branch else UPDATE, program, args, folder)

    def repair(self, folder: str) -> bool:
        program, args = mt.repair_command(Path(folder))
        return self._run(REPAIR, program, args, folder)

    def health_check(self, folder: str) -> bool:
        program, args = mt.doctor_command(Path(folder))
        return self._run(DOCTOR, program, args, folder)

    def cancel(self) -> None:
        if self._process is not None and self.job != DOCTOR:
            self._cancelled = True
            self._kill(self._process)

    def _read(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        self._output += chunk
        self._output = self._output[-200_000:]
        text = self._partial + chunk.replace("\r\n", "\n").replace("\r", "\n")
        *complete, self._partial = text.split("\n")
        for raw in complete:
            self._line(raw)

    def _line(self, raw: str) -> None:
        text = raw.rstrip()
        if not text.strip():
            return
        if self.job != DOCTOR:
            self._say(text)
        if any(marker in text.upper() for marker in FAILURE_MARKERS):
            self._failure_seen = True

    def _failed_to_start(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self._end(False, "The program could not be started, so this cannot run.")

    def _exited(self, code: int, _status=None) -> None:
        self._read()
        if self._partial.strip():
            self._line(self._partial)
        self._partial = ""
        job = self.job
        if not job:
            return
        if self._cancelled:
            self._end(False, f"{LABELS[job]} was cancelled.")
        elif job == DOCTOR:
            try:
                report = mt.parse_doctor(self._output)
            except ValueError as exc:
                self.doctor_done.emit(None, str(exc))
                self._end(False, str(exc))
                return
            for line in report.lines():
                self._say(line)
            self.doctor_done.emit(report, "")
            self._end(report.ok, "The health check found no problems." if report.ok
                      else "The health check found problems. See the output; Repair may fix them.")
        elif code == 0 and not self._failure_seen:
            self._end(True, f"{LABELS[job]} finished.")
        else:
            self._end(False, f"{LABELS[job]} failed (code {code}). See the output. "
                             "The backend's scripts roll back or keep a backup when they fail.")
