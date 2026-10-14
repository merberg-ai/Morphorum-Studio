"""C3: backend lifetime (job object), crash recovery, port conflicts, LAN option, status strips."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
import subprocess
import sys
import time
import pytest
from PySide6.QtWidgets import QWidget
from test_managed import FakeJob, PanelRig, Rig, installed

from morphorum_studio.backend import managed
from morphorum_studio.backend.winjob import JobObject
from morphorum_studio.ui import managed_backend as mb
from morphorum_studio.ui.managed_status import ManagedStatusChip, ManagedStatusStrip, summary, usable

_MADE = []


# ------------------------------------------------------------------ helpers

def test_serve_command_listens_on_this_pc_unless_lan_was_chosen(tmp_path):
    _program, local = managed.serve_command(tmp_path, 7866)
    _program, lan = managed.serve_command(tmp_path, 7866, lan=True)
    assert local[local.index("--host") + 1] == "127.0.0.1"
    assert lan[lan.index("--host") + 1] == "0.0.0.0" and "--backend-only" in lan


def test_settings_keep_lan_and_restart_choices(tmp_path):
    store = managed.ManagedStore(tmp_path / "m.json")
    assert (store.load().lan, store.load().auto_restart) == (False, True)
    store.save(managed.ManagedSettings(lan=True, auto_restart=False))
    assert (store.load().lan, store.load().auto_restart) == (True, False)
    (tmp_path / "m.json").write_text('{"lan": "yes", "auto_restart": 1}')
    assert (store.load().lan, store.load().auto_restart) == (False, True)  # only real booleans count


def test_lan_address_is_empty_or_a_url():
    value = managed.lan_address(7866)
    assert value == "" or re.fullmatch(r"http://\d+\.\d+\.\d+\.\d+:7866", value)


NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1032
  TCP    127.0.0.1:7866         0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:78660        0.0.0.0:0              LISTENING       99
"""


def test_port_owner_is_found_from_system_output():
    assert managed.parse_listening_pid(NETSTAT, 7866) == 4242
    assert managed.parse_listening_pid(NETSTAT, 7000) is None
    assert managed.parse_process_name('"python.exe","4242","Console","1","52,000 K"\n') == "python.exe"
    assert managed.parse_process_name("INFO: No tasks are running which match the specified criteria.") == ""

    def run(args):
        return NETSTAT if args[0] == "netstat" else '"python.exe","4242","Console","1","52,000 K"\n'

    assert managed.describe_port_owner(7866, run=run) == "python.exe (PID 4242)"
    assert managed.describe_port_owner(7000, run=run) == ""

    def broken(args):
        raise OSError("no netstat")

    assert managed.describe_port_owner(7866, run=broken) == ""


# ------------------------------------------------------------------ job object

@pytest.mark.skipif(os.name == "nt", reason="the job object is Windows only")
def test_job_object_is_a_no_op_off_windows():
    job = JobObject()
    assert not job.available and job.assign(1234) is False
    job.close()


@pytest.mark.skipif(os.name != "nt", reason="needs Windows job objects")
def test_closing_the_job_ends_the_process():
    job = JobObject()
    assert job.available
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        if not job.assign(child.pid):
            pytest.skip("this runner already confines the process in a job that forbids nesting")
        job.close()
        deadline = time.time() + 15
        while child.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()


def started(rig, folder, port=7866):
    rig.backend.configure(str(folder), port)
    assert rig.backend.start()
    rig.open_ports.add(port)
    rig.backend._check_ready()
    assert rig.backend.state == mb.RUNNING


def test_backend_is_tied_to_studio_once_it_has_a_process_id(tmp_path):
    rig = Rig(tmp_path)
    started(rig, installed(tmp_path))
    assert rig.job.assigned == [4321]
    rig.backend._check_ready()
    assert rig.job.assigned == [4321]  # only once


def test_failure_to_tie_is_reported_not_fatal(tmp_path):
    rig = Rig(tmp_path, job=FakeJob(works=False))
    lines = []
    rig.backend.log_line.connect(lines.append)
    started(rig, installed(tmp_path))
    assert any("tie the backend" in line for line in lines) and rig.backend.state == mb.RUNNING


# ------------------------------------------------------------------ crash recovery

class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


def crash(rig):
    rig.open_ports.clear()  # the process is gone, so its port is free again
    rig.processes[-1].finish(1)


def test_a_crash_while_running_restarts_up_to_three_times(tmp_path):
    clock = Clock()
    rig = Rig(tmp_path, clock=clock, restart_delays_ms=(10, 20, 30))
    scheduled = []
    rig.backend.restart_scheduled.connect(lambda attempt, delay: scheduled.append((attempt, delay)))
    started(rig, installed(tmp_path))
    for attempt in (1, 2, 3):
        crash(rig)
        assert rig.backend.state == mb.CRASHED and f"attempt {attempt} of 3" in rig.backend.detail
        rig.backend._auto_restart()
        assert rig.backend.state == mb.STARTING
        rig.open_ports.add(7866)
        rig.backend._check_ready()
        assert rig.backend.state == mb.RUNNING
    crash(rig)
    assert scheduled == [(1, 10), (2, 20), (3, 30)]
    assert "used up" in rig.backend.detail and not rig.backend._restart_timer.isActive()
    rig.backend.reset_restarts()
    assert rig.backend.restarts == 0


def test_steady_running_resets_the_restart_budget(tmp_path):
    clock = Clock()
    rig = Rig(tmp_path, clock=clock, restart_delays_ms=(10, 20, 30))
    started(rig, installed(tmp_path))
    crash(rig)
    rig.backend._auto_restart()
    rig.open_ports.add(7866)
    rig.backend._check_ready()
    assert rig.backend.restarts == 1
    clock.now += mb.STEADY_SECONDS + 1
    crash(rig)
    assert rig.backend.restarts == 1 and "attempt 1 of 3" in rig.backend.detail  # reset to 0 first, then used one


def test_no_restart_when_it_never_started_or_was_stopped_or_disabled(tmp_path):
    rig = Rig(tmp_path, restart_delays_ms=(10,))
    rig.backend.configure(str(installed(tmp_path)), 7866)
    rig.backend.start()
    crash(rig)  # died before it was ready
    assert rig.backend.state == mb.CRASHED and not rig.backend._restart_timer.isActive()

    rig2 = Rig(tmp_path / "b", restart_delays_ms=(10,))
    (tmp_path / "b").mkdir()
    started(rig2, installed(tmp_path / "b"))
    rig2.backend.stop()
    rig2.processes[-1].finish(0)
    assert rig2.backend.state == mb.STOPPED and not rig2.backend._restart_timer.isActive()

    rig3 = Rig(tmp_path / "c", restart_delays_ms=(10,))
    (tmp_path / "c").mkdir()
    rig3.backend.auto_restart = False
    started(rig3, installed(tmp_path / "c"))
    crash(rig3)
    assert rig3.backend.state == mb.CRASHED and not rig3.backend._restart_timer.isActive()


def test_starting_by_hand_cancels_a_pending_restart(tmp_path):
    rig = Rig(tmp_path, restart_delays_ms=(60000,))
    started(rig, installed(tmp_path))
    crash(rig)
    assert rig.backend._restart_timer.isActive()
    rig.backend.start()
    assert not rig.backend._restart_timer.isActive() and rig.backend.state == mb.STARTING


def test_panel_reconnects_after_an_automatic_restart(tmp_path):
    r = PanelRig(tmp_path, restart_delays_ms=(10,))
    r.choose()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    r.panel.start()
    r.run_ready()
    assert r.connected_calls == 1
    r.rig.open_ports.clear()
    r.rig.processes[-1].finish(1)
    assert r.rig.backend.state == mb.CRASHED
    r.rig.backend._auto_restart()
    r.run_ready()
    assert r.connected_calls == 2


# ------------------------------------------------------------------ port conflicts

def test_port_owner_is_named_in_the_message(tmp_path):
    rig = Rig(tmp_path)
    rig.backend._owner_lookup = lambda port: "python.exe (PID 4242)"
    rig.open_ports.add(7866)
    rig.backend.configure(str(installed(tmp_path)), 7866)
    assert rig.backend.state == mb.PORT_BUSY and "python.exe (PID 4242)" in rig.backend.detail


def test_use_a_free_port_moves_to_the_next_one(tmp_path):
    r = PanelRig(tmp_path)
    r.choose()
    r.rig.open_ports.add(7866)
    r.rig.backend.refresh()
    assert r.rig.backend.state == mb.PORT_BUSY
    assert r.panel.port_button.isVisibleTo(r.panel) and r.panel.port_button.isEnabled()
    r.panel.port_button.click()
    assert r.panel.settings.port > 7866 and r.panel.port.value() == r.panel.settings.port
    assert r.rig.backend.state == mb.STOPPED and not r.panel.port_button.isVisibleTo(r.panel)
    assert "will use port" in r.panel.detail.text()


# ------------------------------------------------------------------ LAN

def test_lan_needs_a_confirmed_warning(tmp_path):
    r = PanelRig(tmp_path, confirm_lan=lambda: False)
    r.choose()
    r.panel.lan.setChecked(True)
    assert not r.panel.lan.isChecked() and not r.panel.settings.lan and not r.rig.backend.lan


def test_lan_applies_to_the_next_start_and_shows_the_address(tmp_path):
    r = PanelRig(tmp_path)
    r.choose()
    assert "this PC only" in r.panel.lan_note.text()
    r.panel.lan.setChecked(True)
    assert r.panel.settings.lan and r.rig.backend.lan
    assert "http://192.168.1.20:7866" in r.panel.lan_note.text() and "Not encrypted" in r.panel.lan_note.text()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    r.panel.start()
    args = r.rig.processes[-1].args
    assert args[args.index("--host") + 1] == "0.0.0.0"
    assert not r.panel.lan.isEnabled()  # fixed while the backend runs
    assert managed.ManagedStore(tmp_path / "managed.json").load().lan is True
    r.run_ready()
    assert "reachable from your network" in r.rig.backend.detail


def test_restart_setting_is_saved_and_applied(tmp_path):
    r = PanelRig(tmp_path)
    r.panel.auto_restart.setChecked(False)
    assert r.rig.backend.auto_restart is False
    assert managed.ManagedStore(tmp_path / "managed.json").load().auto_restart is False


# ------------------------------------------------------------------ status strips

def make_strips(tmp_path, calls):
    rig = Rig(tmp_path, restart_delays_ms=(60000,))
    holder = QWidget()
    strip = ManagedStatusStrip(rig.backend, lambda: calls.append("start"), lambda: calls.append("stop"), holder)
    chip = ManagedStatusChip(rig.backend, holder)
    _MADE.append((holder, rig))
    return rig, strip, chip


def test_status_strip_and_chip_follow_the_backend(tmp_path):
    calls = []
    rig, strip, chip = make_strips(tmp_path, calls)
    assert not usable(rig.backend) and strip.isHidden() and chip.isHidden()
    rig.backend.configure(str(installed(tmp_path)), 7866)
    assert usable(rig.backend) and strip.chip.text() == "Stopped" and chip.text() == "Local backend: Stopped"
    assert not strip.isHidden() and not strip.start_button.isHidden() and strip.stop_button.isHidden()
    strip.start_button.click()
    assert calls == ["start"]
    rig.backend.start()
    rig.open_ports.add(7866)
    rig.backend._check_ready()
    assert strip.chip.text() == "Running" and summary(rig.backend) == "Running"
    assert strip.start_button.isHidden() and not strip.stop_button.isHidden()
    strip.stop_button.click()
    assert calls == ["start", "stop"]
    rig.open_ports.clear()
    rig.processes[-1].finish(1)
    assert strip.chip.text() == "Stopped unexpectedly"
    assert "Starting it again" in strip.detail.text()


def test_strip_is_hidden_without_an_installed_folder(tmp_path):
    rig, strip, chip = make_strips(tmp_path, [])
    rig.backend.configure(str(tmp_path / "nothing"), 7866)
    assert not usable(rig.backend) and strip.isHidden() and chip.isHidden()


@pytest.fixture(autouse=True)
def _destroy_widgets():
    yield
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete, isValid

    while _MADE:
        for obj in _MADE.pop():
            for widget in (obj, getattr(obj, "backend", None)):
                if widget is not None and hasattr(widget, "deleteLater") and isValid(widget):
                    delete(widget)
    QApplication.processEvents()
