"""Runs and watches the Studio-managed backend process.

Studio only ever stops a process it started itself. A backend left over from an earlier
Studio session is recognised from a run record and reported as ``adopted``: Studio can
connect to it but will not kill a process it cannot positively identify.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from morphorum_studio.backend import managed
from morphorum_studio.backend.winjob import JobObject

# States
UNCONFIGURED, STOPPED, STARTING, RUNNING, STOPPING = (
    "unconfigured", "stopped", "starting", "running", "stopping")
ADOPTED, CRASHED, PORT_BUSY, ERROR = "adopted", "crashed", "port-busy", "error"
KEEP_LINES = 500
RESTART_DELAYS_MS = (2000, 5000, 15000)
STEADY_SECONDS = 60  # running this long counts as healthy, so the restart budget resets
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
    restart_scheduled = Signal(int, int)  # attempt number, delay in ms
    owner_found = Signal(int, str)  # port, who is using it
    _owner = Signal(int, str)  # from the lookup thread

    def __init__(self, record_path: Path | None = None, process_factory: Callable[[], QProcess] = new_process,
                 probe: Callable[[int], bool] = managed.port_open, parent: QObject | None = None,
                 poll_ms: int = 500, start_timeout_ms: int = 90_000, kill_after_ms: int = 4000,
                 job: JobObject | None = None, clock: Callable[[], float] = time.monotonic,
                 owner_lookup: Callable[[int], str] = managed.describe_port_owner, threaded_lookup: bool = True,
                 restart_delays_ms: tuple[int, ...] = RESTART_DELAYS_MS) -> None:
        super().__init__(parent)
        self._job = job if job is not None else JobObject()
        self._clock, self._owner_lookup, self._threaded_lookup = clock, owner_lookup, threaded_lookup
        self._delays = restart_delays_ms
        self.lan = False
        self.auto_restart = True
        self.restarts = 0  # automatic restarts since the backend last ran steadily
        self._ran_since = 0.0
        self._tied = False
        self.port_owner = ""
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._auto_restart)
        self._owner.connect(self._owner_ready)
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

    def configure(self, folder: str, port: int, lan: bool | None = None) -> None:
        """Set the folder, port and LAN choice (only while nothing is running) and recompute the idle state."""
        if self.owned:
            return
        self.folder, self.port = folder, int(port)
        if lan is not None:
            self.lan = bool(lan)
        self._restart_timer.stop()
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
                self._find_owner(self.port)
        else:
            managed.clear_record(self._record_path)  # a stale record: nothing is listening
            self._set(STOPPED, "Stopped.")

    def _find_owner(self, port: int) -> None:
        """Ask the system who is using the port, without holding up the window."""
        def work() -> None:
            try:
                text = self._owner_lookup(port)
            except Exception:  # Naming the program is a courtesy; never a failure.
                text = ""
            self._owner.emit(port, text)

        if self._threaded_lookup:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def _owner_ready(self, port: int, text: str) -> None:
        if not text or port != self.port or self.state != PORT_BUSY:
            return
        self.port_owner = text
        self.owner_found.emit(port, text)
        self._set(PORT_BUSY, f"Port {port} is already in use by {text}.")

    # -- start --------------------------------------------------------------------------

    def start(self) -> bool:
        if self.owned:
            return False
        self._restart_timer.stop()
        self.refresh()
        if self.state != STOPPED:
            return False
        program, args = managed.serve_command(Path(self.folder), self.port, self.lan)
        process = self._factory()
        process.setProgram(program)
        process.setArguments(args)
        process.setWorkingDirectory(self.folder)
        process.setProcessEnvironment(_environment(managed.environment()))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._failed)
        started = getattr(process, "started", None)
        if hasattr(started, "connect"):
            started.connect(self._tie_to_studio)
        self._tied = False
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
        self._tie_to_studio()
        if self._probe(self.port):
            self._poll.stop()
            try:
                managed.write_record(self._record_path, self.folder, self.port,
                                     int(self._process.processId()))
            except OSError:
                pass  # The record only helps a later session recognise this backend.
            self._ran_since = self._clock()
            where = " (reachable from your network)" if self.lan else ""
            self._set(RUNNING, f"Running on port {self.port}{where}.")
            self.ready.emit()
        elif self._waited_ms >= self._timeout_ms:
            self._poll.stop()
            self._stopping = True
            self._process.kill()
            self._set(ERROR, "The backend did not start listening in time. See the log.")

    def _tie_to_studio(self) -> None:
        """Put the backend in a Windows job so it ends with Studio, even if Studio crashes."""
        if self._tied or self._process is None:
            return
        pid = int(self._process.processId() or 0)
        if not pid:
            return
        self._tied = True
        if not self._job.available:
            if os.name == "nt":
                self._say_tie_failed()
            return
        if not self._job.assign(pid):
            self._say_tie_failed()

    def _say_tie_failed(self) -> None:
        line = "Studio could not tie the backend to its own lifetime; stop it from Studio before closing."
        self.lines.append(line)
        self.log_line.emit(line)

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
        was_running = self.state == RUNNING
        steady = was_running and self._clock() - self._ran_since >= STEADY_SECONDS
        self._cleanup()
        if expected and not was_error:
            self.restarts = 0
            self._set(STOPPED, "Stopped.")
        elif not was_error:
            if steady:
                self.restarts = 0
            tail = " | ".join(list(self.lines)[-3:])
            message = f"The backend stopped unexpectedly (exit code {code})." + (
                f" Last output: {tail}" if tail else "")
            retry = was_running and self.auto_restart and self.restarts < len(self._delays)
            if retry:
                delay = self._delays[self.restarts]
                message += f" Starting it again in {max(1, round(delay / 1000))} s " \
                           f"(attempt {self.restarts + 1} of {len(self._delays)}). Jobs that were running were interrupted."
            elif was_running and self.auto_restart:
                message += " Automatic restarts are used up; start it again when you are ready."
            self._set(CRASHED, message)
            if retry:
                self.restarts += 1
                self._restart_timer.start(delay)
                self.restart_scheduled.emit(self.restarts, delay)

    def reset_restarts(self) -> None:
        """A person chose to start it: give automatic recovery a fresh budget."""
        self.restarts = 0

    def _auto_restart(self) -> None:
        if self.state == CRASHED:
            self.start()

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
        self._restart_timer.stop()
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
