"""C2: installing the managed backend (preflight, command, output parsing, driver, panel)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from test_managed import FakeProcess, PanelRig, installed

from morphorum_studio.backend import managed
from morphorum_studio.ui import managed_install as mi

GIB = 1024**3


def target(tmp_path, name="backend"):
    return tmp_path / name


# ------------------------------------------------------------------ helpers

def test_branch_names_are_validated():
    for good in ("main", "dev-backend", "feature/x.y", "v1.2"):
        assert managed.valid_branch(good)
    for bad in ("", "-rf", "a b", "a..b", "x;y", "a/", "$(x)", "br.lock"):
        assert not managed.valid_branch(bad)
    assert managed.bootstrap_url("main").endswith("/main/scripts/bootstrap.ps1")
    with pytest.raises(ValueError):
        managed.bootstrap_url("a b")


def test_install_command_answers_every_question_up_front(tmp_path):
    program, args = managed.install_command(tmp_path / "b.ps1", tmp_path / "x", "main", 7866)
    assert program == "powershell.exe" and "-File" in args
    for flag, value in (("-InstallDir", str(tmp_path / "x")), ("-Branch", "main"), ("-Port", "7866")):
        assert args[args.index(flag) + 1] == value
    with pytest.raises(ValueError):
        managed.install_command(tmp_path / "b.ps1", tmp_path, "bad branch", 1)


def test_installer_output_markers_are_recognised():
    assert managed.parse_install_line("  >> AI DEPENDENCIES") == (managed.KIND_SECTION, "AI DEPENDENCIES")
    assert managed.parse_install_line("  [>] Cloning the Morphorum repository...")[0] == managed.KIND_STEP
    assert managed.parse_install_line("  [+] Git ready")[0] == managed.KIND_OK
    assert managed.parse_install_line("  [!] FFmpeg not found")[0] == managed.KIND_WARN
    assert managed.parse_install_line("  [X] INSTALLATION FAILED")[0] == managed.KIND_FAIL
    assert managed.parse_install_line("\x1b[32mplain pip line\x1b[0m") == (managed.KIND_TEXT, "plain pip line")


def test_preflight_accepts_a_fresh_folder(tmp_path):
    result = managed.preflight(str(target(tmp_path)), 7866, windows=True, free_bytes=20 * GIB)
    assert result.ok and not result.resume


def test_preflight_explains_each_problem(tmp_path):
    def problems(folder, **kw):
        kw.setdefault("windows", True)
        kw.setdefault("free_bytes", 20 * GIB)
        return " ".join(managed.preflight(str(folder), kw.pop("port", 7866), **kw).problems)

    assert "Windows" in problems(target(tmp_path), windows=False)
    assert "full path" in problems("relative/path")
    assert "drive root" in problems(Path(tmp_path.anchor))
    assert "Choose a folder" in problems("")
    assert "GiB" in problems(target(tmp_path), free_bytes=2 * GIB)
    assert "port" in problems(target(tmp_path), port=0)
    assert "branch" in problems(target(tmp_path), branch="a b")
    full = target(tmp_path, "full")
    full.mkdir()
    (full / "notes.txt").write_text("x")
    assert "not empty" in problems(full)
    file = target(tmp_path, "file")
    file.write_text("x")
    assert "file" in problems(file)


def test_preflight_resumes_an_unfinished_checkout_even_when_space_is_low(tmp_path):
    half = target(tmp_path, "half")
    (half / ".git").mkdir(parents=True)
    (half / "install.bat").write_text("")
    result = managed.preflight(str(half), 7866, windows=True, free_bytes=1 * GIB)
    assert result.ok and result.resume


def test_fetch_bootstrap_checks_what_it_downloads(tmp_path):
    class Body:
        def __init__(self, data): self.data = data
        def read(self, n=-1): return self.data[:n]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    url = managed.bootstrap_url("main")
    dest = tmp_path / "dl" / "bootstrap.ps1"
    managed.fetch_bootstrap(url, dest, opener=lambda u: Body(b"param([string]$InstallDir)"))
    assert dest.read_bytes().startswith(b"param")
    for bad in (b"", b"<html>not a script</html>", b"x" * (managed.MAX_BOOTSTRAP_BYTES + 5) + b"InstallDir"):
        with pytest.raises(OSError):
            managed.fetch_bootstrap(url, tmp_path / "bad.ps1", opener=lambda u, d=bad: Body(d))
    with pytest.raises(OSError):
        managed.fetch_bootstrap("https://example.com/bootstrap.ps1", tmp_path / "x.ps1", opener=lambda u: Body(b"InstallDir"))
    assert not (tmp_path / "bad.ps1").exists()


# ------------------------------------------------------------------ driver

def ok_check(*_a, **_k):
    return managed.Preflight([], [])


class DriverRig:
    def __init__(self, tmp_path, fetch=None, check=ok_check):
        self.tmp, self.processes, self.killed = tmp_path, [], []
        self.fetched = []
        self.driver = mi.InstallDriver(
            work_dir=tmp_path / "work", process_factory=self._new, fetch=fetch or self._fetch,
            killer=self.killed.append, threaded=False, checker=check)
        self.events, self.lines, self.stages = [], [], []
        self.driver.finished.connect(lambda ok, msg: self.events.append((ok, msg)))
        self.driver.log_line.connect(self.lines.append)
        self.driver.stage.connect(self.stages.append)

    def _new(self):
        process = FakeProcess()
        process.closeWriteChannel = lambda: setattr(process, "closed", True)
        self.processes.append(process)
        return process

    def _fetch(self, url, dest):
        self.fetched.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("param($InstallDir)")


def test_driver_runs_the_downloaded_bootstrap_and_reports_success(tmp_path):
    r = DriverRig(tmp_path)
    folder = target(tmp_path)
    assert r.driver.start(str(folder), "main", 7866)
    assert r.fetched == [managed.bootstrap_url("main")] and r.driver.state == mi.RUNNING
    process = r.processes[0]
    assert process.started and process.closed  # nothing can wait on a question
    assert process.args[process.args.index("-InstallDir") + 1] == str(folder)
    process.say("  >> PYTHON RUNTIME\r\n  [>] Creating the environment\n  partial")
    process.say(" line\n")
    assert r.driver.section == "Python Runtime" and r.stages == ["Python Runtime"]
    assert "partial line" in r.lines
    installed(tmp_path, "backend")
    process.finish(0)
    assert r.driver.state == mi.SUCCEEDED and r.events == [(True, "Morphorum is installed.")]


def test_driver_reports_a_failed_installer(tmp_path):
    r = DriverRig(tmp_path)
    r.driver.start(str(target(tmp_path)), "main", 7866)
    r.processes[0].say("  [X] INSTALLATION FAILED\n")
    r.processes[0].finish(1)
    assert r.driver.state == mi.FAILED and r.driver.failure_seen
    assert r.events[0][0] is False and "code 1" in r.events[0][1]


def test_exit_zero_without_a_complete_folder_is_not_success(tmp_path):
    r = DriverRig(tmp_path)
    r.driver.start(str(target(tmp_path)), "main", 7866)
    r.processes[0].finish(0)
    assert r.driver.state == mi.FAILED and "not a complete" in r.events[0][1]


def test_a_download_failure_never_starts_anything(tmp_path):
    def broken(url, dest):
        raise OSError("Could not download the installer: offline")

    r = DriverRig(tmp_path, fetch=broken)
    r.driver.start(str(target(tmp_path)), "main", 7866)
    assert not r.processes and r.driver.state == mi.FAILED and "offline" in r.events[0][1]


def test_preflight_failure_stops_before_downloading(tmp_path):
    r = DriverRig(tmp_path, check=lambda *a, **k: managed.Preflight(["Not enough space."], []))
    assert r.driver.start(str(target(tmp_path)), "main", 7866) is False
    assert not r.fetched and r.driver.state == mi.FAILED and r.events == [(False, "Not enough space.")]


def test_cancel_kills_the_installer_and_a_new_run_can_follow(tmp_path):
    r = DriverRig(tmp_path)
    r.driver.start(str(target(tmp_path)), "main", 7866)
    r.driver.cancel()
    assert r.killed == [r.processes[0]]
    r.processes[0].finish(1)
    assert r.driver.state == mi.CANCELLED and "continue" in r.events[0][1]
    assert r.driver.start(str(target(tmp_path)), "main", 7866) and len(r.processes) == 2


def test_cannot_start_twice(tmp_path):
    r = DriverRig(tmp_path)
    assert r.driver.start(str(target(tmp_path)), "main", 7866)
    assert r.driver.start(str(target(tmp_path)), "main", 7866) is False and len(r.processes) == 1


# ------------------------------------------------------------------ panel

def make(tmp_path, **kw):
    drv = DriverRig(tmp_path / "d")
    rig = PanelRig(tmp_path, installer=drv.driver, **kw)
    rig.drv = drv
    rig.holder.show()
    return rig


def test_install_needs_consent_and_defaults_to_the_studio_folder(tmp_path):
    r = make(tmp_path)
    panel = r.panel
    panel.show()
    assert panel.install_card.isVisible() and not panel.install_button.isEnabled()
    panel.install()  # without consent nothing happens
    assert not r.drv.processes
    panel.consent.setChecked(True)
    assert panel.install_button.isEnabled()
    panel.install_button.click()
    assert r.drv.processes and panel.settings.folder == str(managed.default_folder())
    assert panel.cancel_install_button.isVisible() and not panel.install_button.isVisible()
    assert not panel.choose_button.isEnabled() and not panel.start_button.isEnabled()


def test_a_finished_install_starts_the_backend_and_connects(tmp_path):
    r = make(tmp_path)
    folder = r.folder
    r.panel.settings.folder = str(folder)
    r.panel.consent.setChecked(True)
    r.panel.install()
    r.drv.processes[0].finish(0)
    assert r.drv.driver.state == mi.SUCCEEDED
    from test_managed import FakeIssuer
    FakeIssuer.instances[0].finish("secret-token-value")  # the credential step that follows the install
    assert r.rig.processes, "the backend should be launched after the install"
    assert not r.panel.consent.isChecked()


def test_a_failed_install_keeps_the_card_and_offers_resume(tmp_path):
    r = make(tmp_path)
    half = tmp_path / "half"
    (half / ".git").mkdir(parents=True)
    r.panel.show()
    r.panel.settings.folder = str(half)
    r.panel.consent.setChecked(True)
    r.panel.install()
    r.drv.processes[0].finish(1)
    assert r.panel.install_card.isVisible() and r.panel.install_button.text() == "Resume install"
    assert "code 1" in r.panel.install_stage.text() and not r.rig.processes


def test_install_card_hides_once_installed(tmp_path):
    r = make(tmp_path)
    r.panel.show()
    r.choose()
    assert not r.panel.install_card.isVisible()


def test_closing_during_an_install_asks_and_can_be_cancelled(tmp_path):
    r = make(tmp_path, confirm_close=lambda: False)
    r.panel.consent.setChecked(True)
    r.panel.install()
    assert r.panel.close_requested() is False and not r.drv.killed
    r.panel._confirm_close_install = lambda: True
    assert r.panel.close_requested() is True and r.drv.killed
