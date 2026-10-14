"""Runs and watches the Studio-managed backend process.

Studio only ever stops a process it started itself. A backend left over from an earlier
Studio session is recognised from a run record and reported as ``adopted``: Studio can
connect to it but will not kill a process it cannot positively identify.
"""
from __future__ import annotations

import os
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from morphorum_studio.backend import managed

# States
UNCONFIGURED, STOPPED, STARTING, RUNNING, STOPPING = (
    "unconfigured", "stopped", "starting", "running", "stopping")
ADOPTED, CRASHED, PORT_BUSY, ERROR = "adopted", "crashed", "port-busy", "error"
KEEP_LINES = 500
CREATE_NO_WINDOW = 0x08000000


def new_process() -> QProcess:
    process = QProcess()
    if os.name == "nt":
        def hide_console(args) -> None:
            try:
                args.flags = args.flags | CREATE_NO_WINDOW
            except Exception:  # A console window is untidy, never a reason to fail to start.
                pass

        try:  # No console window for a background service.
            process.setCreateProcessArgumentsModifier(hide_console)
        except (AttributeError, TypeError):
            pass
    return process


def _environment(env: dict[str, str]) -> QProcessEnvironment:
    out = QProcessEnvironment()
    for key, value in env.items():
        out.insert(key, value)
    return out


class ManagedBackend(QObject):
    state_changed = Signal(str, str)  # state, plain-language detail
    log_line = Signal(str)
    ready = Signal()

    def __init__(self, record_path: Path | None = None, process_factory: Callable[[], QProcess] = new_process,
                 probe: Callable[[int], bool] = managed.port_open, parent: QObject | None = None,
                 poll_ms: int = 500, start_timeout_ms: int = 90_000, kill_after_ms: int = 4000) -> None:
        super().__init__(parent)
        self._record_path = record_path or managed.default_record_path()
        self._factory, self._probe = process_factory, probe
        self._kill_after = kill_after_ms
        self._timeout_ms, self._poll_ms = start_timeout_ms, poll_ms
        self.folder, self.port = "", managed.DEFAULT_PORT
        self.state, self.detail = UNCONFIGURED, "Choose a Morphorum folder."
        self.lines: deque[str] = deque(maxlen=KEEP_LINES)
        self._process: QProcess | None = None
        self._stopping = False
        self._waited_ms = 0
        self._partial = ""
        self._poll = QTimer(self)
        self._poll.setInterval(poll_ms)
        self._poll.timeout.connect(self._check_ready)
        self._killer = QTimer(self)
        self._killer.setSingleShot(True)
        self._killer.timeout.connect(self._force_kill)

    # -- state --------------------------------------------------------------------------

    def _set(self, state: str, detail: str = "") -> None:
        if (state, detail) == (self.state, self.detail):
            return
        self.state, self.detail = state, detail
        self.state_changed.emit(state, detail)

    @property
    def owned(self) -> bool:
        """True while Studio holds the process it started."""
        return self._process is not None and self.state in (STARTING, RUNNING, STOPPING)

    @property
    def running(self) -> bool:
        return self.state in (RUNNING, ADOPTED)

    def configure(self, folder: str, port: int) -> None:
        """Set the folder and port (only while nothing is running) and recompute the idle state."""
        if self.owned:
            return
        self.folder, self.port = folder, int(port)
        self.refresh()

    def refresh(self) -> None:
        """Work out the idle state: unconfigured, stopped, adopted (left over) or port in use."""
        if self.owned:
            return
        check = managed.check_folder(self.folder)
        if not self.folder:
            self._set(UNCONFIGURED, "Choose a Morphorum folder.")
        elif not check.ok:
            self._set(ERROR, " ".join(check.problems))
        elif self._probe(self.port):
            record = managed.read_record(self._record_path)
            if managed.record_matches(record, self.folder, self.port):
                self._set(ADOPTED, "A backend started by an earlier Studio session is already running.")
            else:
                self._set(PORT_BUSY, f"Another program is already using port {self.port}.")
        else:
            managed.clear_record(self._record_path)  # a stale record: nothing is listening
            self._set(STOPPED, "Stopped.")

    # -- start --------------------------------------------------------------------------

    def start(self) -> bool:
        if self.owned:
            return False
        self.refresh()
        if self.state != STOPPED:
            return False
        program, args = managed.serve_command(Path(self.folder), self.port)
        process = self._factory()
        process.setProgram(program)
        process.setArguments(args)
        process.setWorkingDirectory(self.folder)
        process.setProcessEnvironment(_environment(managed.environment()))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._failed)
        self._process, self._stopping, self._waited_ms, self._partial = process, False, 0, ""
        self.lines.clear()
        self._set(STARTING, "Starting the backend…")
        process.start()
        self._poll.start()
        return True

    def _check_ready(self) -> None:
        if self._process is None or self.state != STARTING:
            self._poll.stop()
            return
        self._waited_ms += self._poll_ms
        if self._probe(self.port):
            self._poll.stop()
            try:
                managed.write_record(self._record_path, self.folder, self.port,
                                     int(self._process.processId()))
            except OSError:
                pass  # The record only helps a later session recognise this backend.
            self._set(RUNNING, f"Running on port {self.port}.")
            self.ready.emit()
        elif self._waited_ms >= self._timeout_ms:
            self._poll.stop()
            self._stopping = True
            self._process.kill()
            self._set(ERROR, "The backend did not start listening in time. See the log.")

    # -- output -------------------------------------------------------------------------

    def _read(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        text = self._partial + chunk
        *complete, self._partial = text.split("\n")
        for raw in complete:
            line = managed.clean_log_line(raw)
            if line:
                self.lines.append(line)
                self.log_line.emit(line)

    def _flush(self) -> None:
        if self._partial.strip():
            line = managed.clean_log_line(self._partial)
            if line:
                self.lines.append(line)
                self.log_line.emit(line)
        self._partial = ""

    # -- ending -------------------------------------------------------------------------

    def _failed(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self._poll.stop()
            self._cleanup()
            self._set(ERROR, "Windows or Linux could not start the backend's Python. "
                             "Check that the folder is installed correctly.")

    def _finished(self, code: int, _status=None) -> None:
        self._poll.stop()
        self._killer.stop()
        self._read()
        self._flush()
        expected, was_error = self._stopping, self.state == ERROR
        self._cleanup()
        if expected and not was_error:
            self._set(STOPPED, "Stopped.")
        elif not was_error:
            tail = " | ".join(list(self.lines)[-3:])
            self._set(CRASHED, f"The backend stopped unexpectedly (exit code {code})."
                               + (f" Last output: {tail}" if tail else ""))

    def _cleanup(self) -> None:
        process, self._process = self._process, None
        managed.clear_record(self._record_path)
        if process is not None:
            process.deleteLater()

    # -- stop ---------------------------------------------------------------------------

    def stop(self) -> bool:
        """Stop the process Studio started. Returns False if there is nothing Studio may stop."""
        if self._process is None or self.state not in (STARTING, RUNNING):
            return False
        self._stopping = True
        self._poll.stop()
        self._set(STOPPING, "Stopping…")
        if os.name == "nt":
            self._process.kill()  # A console service has no window to ask politely.
        else:
            self._process.terminate()
            self._killer.start(self._kill_after)
        return True

    def _force_kill(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()

    def shutdown(self, wait_ms: int = 4000) -> None:
        """Stop and wait; used when Studio itself is closing."""
        process = self._process
        if process is None:
            return
        self.stop()
        if process.state() != QProcess.ProcessState.NotRunning and not process.waitForFinished(wait_ms):
            process.kill()
            process.waitForFinished(2000)


class CredentialIssuer(QObject):
    """Asks the backend for a revocable Studio credential (``clients issue``) without a server running."""

    done = Signal(object, str)  # token | None, message

    def __init__(self, folder: str, process_factory: Callable[[], QProcess] = new_process,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._folder = folder
        self._factory = process_factory
        self._process: QProcess | None = None
        self._out: Path | None = None

    @property
    def busy(self) -> bool:
        return self._process is not None

    def issue(self) -> None:
        if self._process is not None:
            return
        data = managed.data_dir(Path(self._folder))
        try:
            data.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.done.emit(None, f"Could not prepare the backend's data folder: {exc}")
            return
        self._out = data / f"studio-managed-{uuid.uuid4().hex}.token"
        program, args = managed.issue_command(Path(self._folder), self._out)
        process = self._factory()
        process.setProgram(program)
        process.setArguments(args)
        process.setWorkingDirectory(self._folder)
        process.setProcessEnvironment(_environment(managed.environment()))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._errored)
        self._process = process
        process.start()

    def _errored(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._end(None, "The backend's Python could not be started to create a credential.")

    def _finished(self, code: int, _status=None) -> None:
        process = self._process
        output = bytes(process.readAllStandardOutput()).decode("utf-8", "replace") if process else ""
        if code != 0:
            tail = managed.clean_log_line(output.strip().splitlines()[-1]) if output.strip() else ""
            self._end(None, f"The backend could not create a credential (exit code {code}). {tail}".strip())
            return
        try:
            token = managed.read_issued_token(self._out)
        except (OSError, ValueError) as exc:
            self._end(None, str(exc))
            return
        self._end(token, "")

    def _end(self, token, message: str) -> None:
        out, process = self._out, self._process
        self._process = self._out = None
        if out is not None:
            try:
                out.unlink(missing_ok=True)  # Studio created this one-time file; the secret now lives in the keyring.
            except OSError:
                pass
        if process is not None:
            process.deleteLater()
        self.done.emit(token, message)
