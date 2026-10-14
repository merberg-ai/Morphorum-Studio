"""C1: Studio-managed local backend (settings, folder checks, process manager, panel, mode switch)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from morphorum_studio.backend import managed
from morphorum_studio.backend.profiles import ConnectionProfile, ProfileStore
from morphorum_studio.ui import managed_backend as mb
from morphorum_studio.ui.connection_hub import ADVANCED, SIMPLE, ConnectionHub
from morphorum_studio.ui.connections_panel import ConnectionsPanel
from morphorum_studio.ui.managed_panel import ManagedPanel
from morphorum_studio.ui.preferences import StudioPreferences

QApplication.instance() or QApplication(["morphorum-studio-tests"])


class FakeVault:
    def __init__(self):
        self.items = {}

    def get(self, key):
        return self.items.get(key)

    def set(self, key, value):
        self.items[key] = value

    def delete(self, key):
        self.items.pop(key, None)


class FakeProcess(QObject):
    """Stands in for QProcess: records calls and lets a test drive its signals."""

    readyReadStandardOutput = Signal()
    finished = Signal(int, object)
    errorOccurred = Signal(object)

    def __init__(self):
        super().__init__()
        self.program, self.args, self.cwd, self.env = "", [], "", None
        self.started = self.killed = self.terminated = False
        self.output = b""
        self.on_start = None
        self._state = QProcess.ProcessState.NotRunning

    def setProgram(self, program): self.program = program
    def setArguments(self, args): self.args = list(args)
    def setWorkingDirectory(self, cwd): self.cwd = cwd
    def setProcessEnvironment(self, env): self.env = env
    def setProcessChannelMode(self, mode): pass
    def processId(self): return 4321
    def state(self): return self._state

    def start(self):
        self.started = True
        self._state = QProcess.ProcessState.Running
        if self.on_start:
            self.on_start(self)

    def terminate(self): self.terminated = True
    def kill(self): self.killed = True

    def waitForFinished(self, _ms=0):
        self.finish(0)
        return True

    def readAllStandardOutput(self):
        out, self.output = self.output, b""
        return out

    def say(self, text):
        self.output += text.encode()
        self.readyReadStandardOutput.emit()

    def finish(self, code):
        self._state = QProcess.ProcessState.NotRunning
        self.finished.emit(code, QProcess.ExitStatus.NormalExit)


def installed(tmp_path, name="morph"):
    folder = tmp_path / name
    (folder / "backend" / "morphorum").mkdir(parents=True, exist_ok=True)
    python = managed.python_path(folder)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("")
    (folder / "VERSION").write_text("0.1.0a1\n")
    return folder


class Rig:
    """A backend with a fake process, a controllable port probe and a temp run record."""

    def __init__(self, tmp_path):
        self.open_ports = set()
        self.processes = []
        self.backend = mb.ManagedBackend(
            record_path=tmp_path / "run.json", process_factory=self._new,
            probe=lambda port: port in self.open_ports, start_timeout_ms=1500, poll_ms=500)

    def _new(self):
        process = FakeProcess()
        self.processes.append(process)
        return process

    @property
    def process(self):
        return self.processes[-1]


# --------------------------------------------------------------------- pure helpers

def test_check_folder(tmp_path):
    assert not managed.check_folder(None).ok
    assert not managed.check_folder(tmp_path / "missing").ok
    empty = tmp_path / "empty"
    empty.mkdir()
    check = managed.check_folder(empty)
    assert not check.ok and len(check.problems) == 2
    folder = installed(tmp_path)
    check = managed.check_folder(folder)
    assert check.ok and check.version == "0.1.0a1"
    assert not managed.check_folder("bad\x00path").ok


def test_commands_are_loopback_only_and_never_pass_a_secret(tmp_path):
    folder = installed(tmp_path)
    program, args = managed.serve_command(folder, 7999)
    assert program == str(managed.python_path(folder))
    assert args == ["-m", "morphorum", "serve", "--host", "127.0.0.1", "--port", "7999", "--backend-only"]
    assert "--lan" not in args
    _program, issue = managed.issue_command(folder, tmp_path / "t.token")
    assert issue[:4] == ["-m", "morphorum", "clients", "issue"] and "--out" in issue
    env = managed.environment({"MORPHORUM_BACKEND_TOKEN": "x" * 40, "A": "1"})
    assert "MORPHORUM_BACKEND_TOKEN" not in env and env["A"] == "1" and env["PYTHONUNBUFFERED"] == "1"
    assert managed.loopback_url(7866) == "http://127.0.0.1:7866"


def test_settings_roundtrip_and_validation(tmp_path):
    store = managed.ManagedStore(tmp_path / "managed.json")
    assert store.load() == managed.ManagedSettings()  # missing file: defaults
    store.save(managed.ManagedSettings(folder=str(tmp_path), port=8123, stop_on_exit=False, profile_id="a" * 32))
    loaded = store.load()
    assert (loaded.port, loaded.stop_on_exit, loaded.profile_id) == (8123, False, "a" * 32)
    store.path.write_text(json.dumps({"port": 99999, "stop_on_exit": "yes", "folder": 5, "profile_id": "x",
                                      "extra": 1}))
    assert store.load() == managed.ManagedSettings()
    store.path.write_text("{not json")
    assert store.load() == managed.ManagedSettings()
    assert managed.default_folder().name == "morphorum-backend"


def test_issued_token_file_must_be_one_token(tmp_path):
    good = tmp_path / "a.token"
    good.write_text("﻿token-value-123\n", encoding="utf-8")
    assert managed.read_issued_token(good) == "token-value-123"
    for bad in ("", "two words", "x" * 5000):
        path = tmp_path / "b.token"
        path.write_text(bad)
        try:
            managed.read_issued_token(path)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad[:10]!r}")


def test_run_record(tmp_path):
    path = tmp_path / "run.json"
    assert managed.read_record(path) is None
    managed.write_record(path, str(tmp_path), 7866, 99)
    record = managed.read_record(path)
    assert managed.record_matches(record, str(tmp_path), 7866)
    assert not managed.record_matches(record, str(tmp_path), 7867)
    assert not managed.record_matches(record, str(tmp_path / "other"), 7866)
    assert not managed.record_matches(None, str(tmp_path), 7866)
    path.write_text('{"folder": 1}')
    assert managed.read_record(path) is None
    managed.clear_record(path)
    assert not path.exists()
    assert managed.clean_log_line("\x1b[32mhello\x1b[0m\x07 world  ") == "hello  world"


def test_profile_kind_roundtrips_and_old_files_stay_remote(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    remote = ConnectionProfile.create("Remote", "http://10.0.0.5:7866")
    local = ConnectionProfile.create("Local", "http://127.0.0.1:7866")
    local.kind = "managed"
    store.save([remote, local])
    assert [p.kind for p in store.load()] == ["remote", "managed"]
    old = json.loads(store.path.read_text())
    for item in old["profiles"]:
        item.pop("kind")
    store.path.write_text(json.dumps(old))
    assert [p.kind for p in store.load()] == ["remote", "remote"]
    old["profiles"][0]["kind"] = "weird"
    store.path.write_text(json.dumps(old))
    result = store.load_recovering()
    assert len(result.profiles) == 1 and result.warning


# --------------------------------------------------------------------- process manager

def test_states_before_start(tmp_path):
    rig = Rig(tmp_path)
    backend = rig.backend
    backend.configure("", 7866)
    assert backend.state == mb.UNCONFIGURED
    backend.configure(str(tmp_path / "nowhere"), 7866)
    assert backend.state == mb.ERROR
    folder = installed(tmp_path)
    backend.configure(str(folder), 7866)
    assert backend.state == mb.STOPPED and not backend.owned
    assert backend.stop() is False  # nothing Studio started


def test_start_run_and_output(tmp_path):
    rig = Rig(tmp_path)
    folder = installed(tmp_path)
    rig.backend.configure(str(folder), 7866)
    seen, ready = [], []
    rig.backend.log_line.connect(seen.append)
    rig.backend.ready.connect(lambda: ready.append(True))
    assert rig.backend.start() is True and rig.backend.state == mb.STARTING and rig.backend.owned
    process = rig.process
    assert process.started and process.cwd == str(folder)
    assert process.program == str(managed.python_path(folder))
    assert process.args[-1] == "--backend-only" and "7866" in process.args
    process.say("Morphorum backend-only API: 127.0.0.1:7866\nauth token fi")
    process.say("le: x\n\x1b[32mready\x1b[0m\n")
    assert seen == ["Morphorum backend-only API: 127.0.0.1:7866", "auth token file: x", "ready"]
    assert rig.backend.start() is False  # already running
    rig.backend._check_ready()
    assert rig.backend.state == mb.STARTING  # port not open yet
    rig.open_ports.add(7866)
    rig.backend._check_ready()
    assert rig.backend.state == mb.RUNNING and ready == [True]
    record = managed.read_record(tmp_path / "run.json")
    assert managed.record_matches(record, str(folder), 7866) and record["pid"] == 4321


def test_stop_only_stops_what_studio_started(tmp_path):
    rig = Rig(tmp_path)
    folder = installed(tmp_path)
    rig.backend.configure(str(folder), 7866)
    rig.backend.start()
    rig.open_ports.add(7866)
    rig.backend._check_ready()
    assert rig.backend.stop() is True and rig.backend.state == mb.STOPPING
    assert rig.process.killed if os.name == "nt" else rig.process.terminated
    rig.open_ports.clear()
    rig.process.finish(0)
    assert rig.backend.state == mb.STOPPED and not rig.backend.owned
    assert not (tmp_path / "run.json").exists()


def test_crash_is_reported_with_the_last_output(tmp_path):
    rig = Rig(tmp_path)
    rig.backend.configure(str(installed(tmp_path)), 7866)
    rig.backend.start()
    rig.open_ports.add(7866)
    rig.backend._check_ready()
    rig.process.say("CUDA out of memory\n")
    rig.process.finish(3)
    assert rig.backend.state == mb.CRASHED
    assert "exit code 3" in rig.backend.detail and "CUDA out of memory" in rig.backend.detail
    assert not rig.backend.owned


def test_failure_to_start_and_start_timeout(tmp_path):
    rig = Rig(tmp_path)
    rig.backend.configure(str(installed(tmp_path)), 7866)
    rig.backend.start()
    rig.process.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    assert rig.backend.state == mb.ERROR and not rig.backend.owned
    rig2 = Rig(tmp_path)
    rig2.backend.configure(str(installed(tmp_path, "m2")), 7866)
    rig2.backend.start()
    for _ in range(4):
        rig2.backend._check_ready()
    assert rig2.backend.state == mb.ERROR and rig2.process.killed
    rig2.process.finish(1)
    assert rig2.backend.state == mb.ERROR  # the timeout message is kept, not replaced by "crashed"


def test_port_in_use_and_adoption(tmp_path):
    rig = Rig(tmp_path)
    folder = installed(tmp_path)
    rig.open_ports.add(7866)
    rig.backend.configure(str(folder), 7866)
    assert rig.backend.state == mb.PORT_BUSY and rig.backend.start() is False and not rig.processes
    managed.write_record(tmp_path / "run.json", str(folder), 7866, 77)
    rig.backend.refresh()
    assert rig.backend.state == mb.ADOPTED and rig.backend.running
    assert rig.backend.stop() is False  # it cannot be positively identified, so Studio will not kill it
    rig.open_ports.clear()
    rig.backend.refresh()
    assert rig.backend.state == mb.STOPPED and not (tmp_path / "run.json").exists()


def test_shutdown_stops_and_waits(tmp_path):
    rig = Rig(tmp_path)
    rig.backend.configure(str(installed(tmp_path)), 7866)
    rig.backend.start()
    rig.open_ports.add(7866)
    rig.backend._check_ready()
    rig.backend.shutdown()
    assert rig.backend.state == mb.STOPPED and not rig.backend.owned


# --------------------------------------------------------------------- credential

def issuing(token_text="issued-secret-token-1", code=0):
    def fake(process):
        out = Path(process.args[process.args.index("--out") + 1])
        if token_text is not None:
            out.write_text(token_text, encoding="utf-8")
        process.say("Client issued: Morphorum Studio (managed) (abc)\n")
        process.finish(code)
    return fake


def run_issuer(tmp_path, on_start):
    folder = installed(tmp_path)
    holder = {}

    def factory():
        process = FakeProcess()
        process.on_start = on_start
        holder["p"] = process
        return process

    issuer = mb.CredentialIssuer(str(folder), factory)
    results = []
    issuer.done.connect(lambda token, message: results.append((token, message)))
    issuer.issue()
    return folder, issuer, results, holder["p"]


def test_credential_is_read_then_the_one_time_file_removed(tmp_path):
    folder, issuer, results, process = run_issuer(tmp_path, issuing())
    assert results == [("issued-secret-token-1", "")] and not issuer.busy
    assert list(managed.data_dir(folder).glob("studio-managed-*.token")) == []
    assert process.args[:4] == ["-m", "morphorum", "clients", "issue"]


def test_credential_failures_are_explained(tmp_path):
    _f, _i, results, _p = run_issuer(tmp_path, issuing(None, code=2))
    assert results[0][0] is None and "exit code 2" in results[0][1]
    _f, _i, results, _p = run_issuer(tmp_path, issuing("two words"))
    assert results[0][0] is None and "single token" in results[0][1]
    _f, _i, results, _p = run_issuer(tmp_path, lambda p: p.errorOccurred.emit(QProcess.ProcessError.FailedToStart))
    assert results[0][0] is None and "could not be started" in results[0][1]


# --------------------------------------------------------------------- panel

class FakeIssuer(QObject):
    done = Signal(object, str)
    instances = []

    def __init__(self, folder):
        super().__init__()
        self.folder, self.busy, self.asked = folder, False, 0
        FakeIssuer.instances.append(self)

    def issue(self):
        self.busy = True
        self.asked += 1

    def finish(self, token, message=""):
        self.busy = False
        self.done.emit(token, message)


class PanelRig:
    def __init__(self, tmp_path, jobs=0, ask=None, installer=None, confirm_close=None):
        FakeIssuer.instances = []
        self.tmp = tmp_path
        self.holder = QWidget()
        self.vault = FakeVault()
        self.prefs = StudioPreferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))
        self.connections = ConnectionsPanel(
            profile_store=ProfileStore(tmp_path / "profiles.json"), credential_store=self.vault,
            preferences=self.prefs)
        self.rig = Rig(tmp_path)
        self.jobs = jobs
        self.connected_calls = 0
        self.connections.connect_managed = self._connect
        self.folder = installed(tmp_path)
        self.panel = ManagedPanel(
            self.connections, self.rig.backend, store=managed.ManagedStore(tmp_path / "managed.json"),
            vault=self.vault, issuer_factory=FakeIssuer, active_jobs=lambda: self.jobs,
            ask_exit=ask or (lambda n: "stop"), choose_folder=lambda parent, start: str(self.folder),
            open_folder=lambda path: setattr(self, "opened", path), installer=installer,
            confirm_close_install=confirm_close, parent=self.holder)

    def _connect(self):
        self.connected_calls += 1
        return True

    def choose(self):
        self.panel.choose()

    def run_ready(self):
        self.rig.open_ports.add(self.panel.settings.port)
        self.rig.backend._check_ready()


def test_panel_starts_empty_and_asks_for_a_folder(tmp_path):
    r = PanelRig(tmp_path)
    assert r.panel.chip.text() == "No folder" and not r.panel.start_button.isEnabled()
    assert r.panel.folder_note.text() == "No folder chosen yet."
    assert not r.panel.open_button.isEnabled()
    r.choose()
    assert r.panel.chip.text() == "Stopped" and r.panel.start_button.isEnabled()
    assert "0.1.0a1" in r.panel.folder_note.text()
    assert managed.ManagedStore(tmp_path / "managed.json").load().folder == str(r.folder)
    r.panel.open_button.click()
    assert r.opened == str(r.folder)


def test_panel_rejects_a_folder_that_is_not_installed(tmp_path):
    r = PanelRig(tmp_path)
    r.folder = tmp_path / "just-a-folder"
    r.folder.mkdir()
    r.choose()
    assert not r.panel.start_button.isEnabled() and r.panel.chip.text() == "Needs attention"
    assert "not installed" in r.panel.folder_note.text()


def test_start_creates_a_profile_and_credential_then_launches_and_connects(tmp_path):
    r = PanelRig(tmp_path)
    r.choose()
    r.panel.start()
    profile = r.connections.managed_profile()
    assert profile.kind == "managed" and profile.url == "http://127.0.0.1:7866"
    assert len(FakeIssuer.instances) == 1 and FakeIssuer.instances[0].folder == str(r.folder)
    assert not r.rig.processes and not r.panel.start_button.isEnabled()
    FakeIssuer.instances[0].finish("secret-token-value")
    assert r.vault.get(profile.id) == "secret-token-value"
    assert r.rig.process.started and r.panel.chip.text() == "Starting"
    assert r.connected_calls == 0
    r.run_ready()
    assert r.panel.chip.text() == "Running" and r.connected_calls == 1
    assert r.panel.settings.profile_id == profile.id
    saved = (tmp_path / "profiles.json").read_text() + (tmp_path / "managed.json").read_text()
    assert "secret-token-value" not in saved  # the secret lives only in the credential store


def test_an_existing_credential_is_reused(tmp_path):
    r = PanelRig(tmp_path)
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    r.panel.start()
    assert not FakeIssuer.instances and r.rig.process.started


def test_a_failed_credential_explains_and_does_not_launch(tmp_path):
    r = PanelRig(tmp_path)
    r.choose()
    r.panel.start()
    FakeIssuer.instances[0].finish(None, "The backend could not create a credential (exit code 2).")
    assert "exit code 2" in r.panel.detail.text() and not r.rig.processes
    assert r.panel.start_button.isEnabled()


def test_stop_disconnects_first_and_confirms_when_jobs_run(tmp_path, monkeypatch):
    r = PanelRig(tmp_path, jobs=2)
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    r.panel.start()
    r.run_ready()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    r.panel.stop()
    assert asked and "2 job" in asked[0] and r.rig.backend.state == mb.RUNNING  # declined: nothing happens
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    r.panel.stop()
    assert r.rig.backend.state == mb.STOPPING
    r.rig.process.finish(0)
    assert r.panel.chip.text() == "Stopped" and r.panel.start_button.isEnabled()


def test_restart_stops_then_starts_again(tmp_path):
    r = PanelRig(tmp_path)
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    r.panel.start()
    r.run_ready()
    first = r.rig.process
    r.panel.restart()
    assert r.rig.backend.state == mb.STOPPING
    r.rig.open_ports.clear()
    first.finish(0)
    assert len(r.rig.processes) == 2 and r.rig.backend.state == mb.STARTING


def test_reset_credential_issues_a_new_one(tmp_path):
    r = PanelRig(tmp_path)
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "old")
    r.panel.reset_credential()
    assert r.vault.get(profile.id) is None and len(FakeIssuer.instances) == 1
    FakeIssuer.instances[0].finish("new-token")
    assert r.vault.get(profile.id) == "new-token"


def test_a_backend_from_an_earlier_session_can_be_connected_but_not_stopped(tmp_path):
    r = PanelRig(tmp_path)
    r.rig.open_ports.add(7866)
    managed.write_record(tmp_path / "run.json", str(r.folder), 7866, 55)
    r.choose()
    assert r.panel.chip.text() == "Already running" and r.panel.start_button.text() == "Connect"
    assert not r.panel.stop_button.isEnabled()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    r.panel.start()
    assert not r.rig.processes and r.connected_calls == 1


def test_a_port_in_use_by_something_else_blocks_start(tmp_path):
    r = PanelRig(tmp_path)
    r.rig.open_ports.add(7866)
    r.choose()
    assert r.panel.chip.text() == "Port in use" and not r.panel.start_button.isEnabled()
    r.panel.port.setValue(7867)
    assert r.panel.chip.text() == "Stopped" and r.panel.start_button.isEnabled()
    assert managed.ManagedStore(tmp_path / "managed.json").load().port == 7867


def test_closing_studio_stops_only_when_asked_to(tmp_path):
    r = PanelRig(tmp_path)
    assert r.panel.close_requested() is True  # nothing running
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    r.panel.start()
    r.run_ready()
    r.panel.stop_on_exit.setChecked(False)
    assert r.panel.close_requested() is True and r.rig.backend.state == mb.RUNNING
    r.panel.stop_on_exit.setChecked(True)
    assert r.panel.close_requested() is True and r.rig.backend.state == mb.STOPPED


def test_closing_with_running_jobs_asks_first(tmp_path):
    answers = iter(["cancel", "keep", "stop"])
    r = PanelRig(tmp_path, jobs=1, ask=lambda n: next(answers))
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    r.panel.start()
    r.run_ready()
    assert r.panel.close_requested() is False and r.rig.backend.state == mb.RUNNING
    assert r.panel.close_requested() is True and r.rig.backend.state == mb.RUNNING
    assert r.panel.close_requested() is True and r.rig.backend.state == mb.STOPPED


# --------------------------------------------------------------------- connections panel and hub

def test_the_managed_profile_is_not_listed_in_advanced_mode(tmp_path):
    r = PanelRig(tmp_path)
    p = r.connections
    first = p.ensure_managed_profile("http://127.0.0.1:7866")
    assert p.ensure_managed_profile("http://127.0.0.1:7866") is first  # one profile only
    assert p.selector.count() == 1  # just "New connection"
    p.refresh()
    assert p.selector.count() == 1
    first.instance_id = "i" * 32
    moved = p.ensure_managed_profile("http://127.0.0.1:7900")
    assert moved is first and moved.url == "http://127.0.0.1:7900" and moved.instance_id == ""
    assert p.auto_connect(first.id) is False  # never silently auto-connected
    assert [x.kind for x in ProfileStore(tmp_path / "profiles.json").load()] == ["managed"]


def test_connect_managed_uses_loopback_without_the_http_warning(tmp_path, monkeypatch):
    holder = QWidget()
    vault = FakeVault()
    panel = ConnectionsPanel(profile_store=ProfileStore(tmp_path / "p.json"), credential_store=vault,
                             preferences=StudioPreferences(QSettings(str(tmp_path / "x.ini"),
                                                                     QSettings.Format.IniFormat)),
                             parent=holder)
    probes = []
    monkeypatch.setattr(panel, "_probe", lambda profile, token, monitoring: probes.append((profile.kind, token)))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    assert panel.connect_managed() is False  # no managed profile yet
    profile = panel.ensure_managed_profile("http://127.0.0.1:7866")
    vault.set(profile.id, "tok")
    assert panel.connect_managed() is True
    assert probes == [("managed", "tok")]


def test_hub_defaults_and_remembers_the_mode(tmp_path):
    r = PanelRig(tmp_path)
    hub = ConnectionHub(r.connections, r.panel, r.prefs, parent=r.holder)
    assert hub.mode == SIMPLE  # a fresh install starts Simple
    hub.set_mode(ADVANCED)
    assert hub.mode == ADVANCED and r.prefs.ui("connection_mode") == ADVANCED
    again = ConnectionHub(r.connections, r.panel, r.prefs, parent=r.holder)
    assert again.mode == ADVANCED
    (tmp_path / "other").mkdir()
    saved = PanelRig(tmp_path / "other")
    saved.connections.profiles.append(ConnectionProfile.create("Workshop", "http://10.0.0.5:7866"))
    existing = ConnectionHub(saved.connections, saved.panel, saved.prefs, parent=saved.holder)
    assert existing.mode == ADVANCED  # people who already saved a connection keep today's view


def test_switching_the_view_does_not_disconnect(tmp_path):
    r = PanelRig(tmp_path)
    hub = ConnectionHub(r.connections, r.panel, r.prefs, parent=r.holder)
    calls = []
    r.connections.disconnect = lambda: calls.append(1)
    hub.set_mode(ADVANCED)
    hub.set_mode(SIMPLE)
    assert calls == []


# --------------------------------------------------------------------- opening Studio

from morphorum_studio.backend.session import SessionInfo  # noqa: E402
from morphorum_studio.ui.managed_startup import wait_for_backend  # noqa: E402


def events(panel):
    seen = {"done": [], "progress": []}
    panel.startup_done.connect(lambda ok, reason: seen["done"].append((ok, reason)))
    panel.startup_progress.connect(seen["progress"].append)
    return seen


def fresh(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    return folder


def prepared(tmp_path, **kwargs):
    r = PanelRig(tmp_path, **kwargs)
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    return r, profile


def connect_session(r, profile):
    r.connections.session.connected(
        SessionInfo(profile.id, profile.name, profile.url, "0.1", "backend-only", "i1", "b1", {}), "t")
    r.connections.status_changed.emit("BACKEND CONNECTED")


def test_startup_is_wanted_only_for_the_last_used_managed_backend(tmp_path):
    r, profile = prepared(tmp_path)
    assert r.panel.settings.autostart is True
    assert r.panel.startup_wanted(profile.id) is True
    assert r.panel.startup_wanted("") is False and r.panel.startup_wanted("0" * 32) is False
    r.panel.autostart.setChecked(False)
    assert r.panel.startup_wanted(profile.id) is False
    assert managed.ManagedStore(tmp_path / "managed.json").load().autostart is False
    r.panel.autostart.setChecked(True)
    r.panel.settings.folder = str(tmp_path / "gone")
    assert r.panel.startup_wanted(profile.id) is False
    bare = PanelRig(fresh(tmp_path, "bare"))
    assert bare.panel.startup_wanted("anything") is False  # no managed profile yet


def test_startup_starts_the_backend_and_reports_when_connected(tmp_path):
    r, profile = prepared(tmp_path)
    seen = events(r.panel)
    r.panel.begin_startup()
    assert r.rig.process.started and seen["progress"] == ["Starting the local backend…"]
    assert seen["done"] == []
    r.run_ready()
    assert r.connected_calls == 1 and seen["progress"][-1] == "Connecting to the local backend…"
    connect_session(r, profile)
    assert seen["done"] == [(True, "")]
    r.panel.begin_startup()  # a second call after finishing starts a fresh run, it never doubles up
    assert len(r.rig.processes) == 1


def test_startup_connects_to_a_backend_left_from_an_earlier_session(tmp_path):
    r = PanelRig(tmp_path)
    r.rig.open_ports.add(7866)
    managed.write_record(tmp_path / "run.json", str(r.folder), 7866, 5)
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    seen = events(r.panel)
    r.panel.begin_startup()
    assert not r.rig.processes and r.connected_calls == 1
    connect_session(r, profile)
    assert seen["done"] == [(True, "")]


def test_startup_reports_each_way_it_can_fail(tmp_path):
    r, profile = prepared(tmp_path)
    r.rig.open_ports.add(7866)  # something else owns the port
    r.rig.backend.refresh()
    seen = events(r.panel)
    r.panel.begin_startup()
    assert seen["done"][0][0] is False and "port 7866" in seen["done"][0][1]
    # a crash while starting
    r2, _p = prepared(fresh(tmp_path, "two"))
    seen2 = events(r2.panel)
    r2.panel.begin_startup()
    r2.rig.process.say("Traceback: boom\n")
    r2.rig.process.finish(1)
    assert seen2["done"][0][0] is False and "exit code 1" in seen2["done"][0][1]
    assert "Traceback: boom" in r2.panel.detail.text()  # still explained once Studio is open
    # a rejected credential
    r3, p3 = prepared(fresh(tmp_path, "three"))
    seen3 = events(r3.panel)
    r3.panel.begin_startup()
    r3.run_ready()
    r3.connections.status_changed.emit("BACKEND UNAUTHORIZED")
    assert seen3["done"][0][0] is False and "rejected" in seen3["done"][0][1]
    # a connection that fails after the backend is up
    r4, _p4 = prepared(fresh(tmp_path, "four"))
    seen4 = events(r4.panel)
    r4.panel.begin_startup()
    r4.connections.status_changed.emit("BACKEND OFFLINE")  # before connecting: not a failure yet
    assert seen4["done"] == []
    r4.run_ready()
    r4.connections.status_changed.emit("BACKEND OFFLINE")
    assert seen4["done"][0][0] is False


def test_startup_fails_cleanly_when_no_credential_can_be_made(tmp_path):
    r = PanelRig(tmp_path)
    r.choose()
    r.connections.ensure_managed_profile("http://127.0.0.1:7866")  # no stored credential
    seen = events(r.panel)
    r.panel.begin_startup()
    assert seen["progress"][-1] == "Preparing the backend credential…"
    FakeIssuer.instances[0].finish(None, "The backend could not create a credential (exit code 2).")
    assert seen["done"] == [(False, "The backend could not create a credential (exit code 2).")]
    assert not r.rig.processes


class FakePanel(QObject):
    startup_done = Signal(bool, str)
    startup_progress = Signal(str)

    def __init__(self, script):
        super().__init__()
        self.script, self.begun = script, 0

    def begin_startup(self):
        self.begun += 1
        self.script(self)


def test_waiting_for_the_backend_behind_the_splash():
    from PySide6.QtCore import QTimer
    steps = []
    # finishes later, from the event loop
    later = FakePanel(lambda p: QTimer.singleShot(20, lambda: (p.startup_progress.emit("Connecting"),
                                                               p.startup_done.emit(True, ""))))
    assert wait_for_backend(later, steps.append, limit_ms=5000) == (True, "")
    assert steps == ["Connecting"]
    # finishes before the loop even starts
    instant = FakePanel(lambda p: p.startup_done.emit(False, "nope"))
    assert wait_for_backend(instant, steps.append, limit_ms=5000) == (False, "nope")
    # never finishes
    never = FakePanel(lambda p: None)
    ok, reason = wait_for_backend(never, steps.append, limit_ms=50)
    assert ok is False and "in time" in reason
