"""C4: keeping the managed backend healthy (git checks, doctor report, scripts, removal)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from test_managed import FakeProcess, PanelRig, installed

from morphorum_studio.backend import managed
from morphorum_studio.backend import maintenance as mt
from morphorum_studio.ui import managed_maintenance as mm

_MADE: list = []


@pytest.fixture(autouse=True)
def _destroy_widgets():
    """Delete each test's Qt objects before the next test, while Qt is healthy (see tests/conftest.py)."""
    yield
    from shiboken6 import delete, isValid

    while _MADE:
        obj = _MADE.pop()
        if isValid(obj):
            delete(obj)
    QApplication.processEvents()


# ------------------------------------------------------------------ git status

def scripted(answers):
    """A fake ``run`` answering by the git subcommand."""
    calls = []

    def run(args, timeout=0):
        calls.append(args)
        sub = next(a for a in args[3:] if not a.startswith("-"))
        value = answers.get(sub, (0, ""))
        if callable(value):
            value = value(args)
        if isinstance(value, Exception):
            raise value
        return value

    run.calls = calls
    return run


def healthy(behind=2, ahead=0, dirty="", branch="dev-backend"):
    def rev_list(args):
        return (0, f"{behind}\n" if args[-1].startswith("HEAD..") else f"{ahead}\n")

    def rev_parse(args):
        return (0, f"{branch}\n" if "--abbrev-ref" in args else "abcdef012345\n")

    return {"rev-parse": rev_parse, "fetch": (0, ""), "rev-list": rev_list, "status": (0, dirty),
            "for-each-ref": (0, "origin/HEAD\norigin/main\norigin/dev-backend\norigin/bad name\n")}


def test_update_available_is_reported_with_branches(tmp_path):
    status = mt.check_updates(tmp_path, scripted(healthy()))
    assert status.update_available and status.behind == 2 and not status.dirty
    assert status.branch == "dev-backend" and status.commit == "abcdef012345"
    assert status.branches == ("dev-backend", "main")  # HEAD and unusable names are dropped


def test_up_to_date_and_dirty(tmp_path):
    status = mt.check_updates(tmp_path, scripted(healthy(behind=0, ahead=3, dirty=" M file.py\n")))
    assert not status.update_available and status.ahead == 3 and status.dirty


def test_a_branch_missing_from_the_remote_counts_as_nothing_to_update(tmp_path):
    status = mt.check_updates(tmp_path, scripted(healthy(branch="local-only")))
    assert status.behind == 0 and "local-only" not in status.branches


def test_not_a_git_folder_and_network_failure(tmp_path):
    assert "not a Git copy" in mt.check_updates(tmp_path, scripted({"rev-parse": (128, "")})).error
    assert "not a Git copy" in mt.check_updates(tmp_path, scripted({"rev-parse": FileNotFoundError()})).error
    answers = healthy()
    answers["fetch"] = (1, "")
    assert "GitHub" in mt.check_updates(tmp_path, scripted(answers)).error
    answers = healthy()
    answers["rev-list"] = (0, "not a number")
    assert "could not compare" in mt.check_updates(tmp_path, scripted(answers)).error
    answers = healthy()
    answers["fetch"] = subprocess.TimeoutExpired("git", 1)
    assert "GitHub" in mt.check_updates(tmp_path, scripted(answers)).error


def test_install_info_reads_what_the_installer_recorded(tmp_path):
    assert mt.read_install_info(tmp_path) == {} and mt.describe_install(tmp_path) == "Morphorum"
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "install.json").write_text(json.dumps(
        {"morphorum_version": "0.2.0", "git_branch": "main", "git_commit": "0123456789abcdef"}))
    assert mt.describe_install(tmp_path) == "Morphorum 0.2.0 · branch main · commit 01234567"
    (tmp_path / "data" / "install.json").write_text("[1]")
    assert mt.read_install_info(tmp_path) == {}


# ------------------------------------------------------------------ commands and doctor

def test_script_commands(tmp_path):
    program, args = mt.update_command(tmp_path)
    assert program == "powershell.exe" and args[-1].endswith("update_windows.ps1") and "-Branch" not in args
    assert mt.update_command(tmp_path, "feature/x")[1][-2:] == ["-Branch", "feature/x"]
    with pytest.raises(ValueError):
        mt.update_command(tmp_path, "bad branch")
    assert mt.repair_command(tmp_path)[1][-1].endswith("repair_windows.ps1")
    program, args = mt.doctor_command(tmp_path)
    assert program.endswith(("python", "python.exe")) and args == ["-m", "morphorum", "doctor", "--json"]


DOCTOR = {"ok": False, "version": "0.2.0", "branch": "main", "commit": "abc",
          "checks": [{"name": "python", "ok": True, "detail": "3.12"}, {"name": "ffmpeg", "ok": False, "detail": "missing"}]}


def test_doctor_report_parses_and_tolerates_log_lines():
    report = mt.parse_doctor("loading...\n" + json.dumps(DOCTOR) + "\n")
    assert not report.ok and report.version == "0.2.0" and len(report.checks) == 2
    lines = report.lines()
    assert lines[0].endswith("needs attention") and "PROBLEM  ffmpeg: missing" in lines[2]
    assert mt.parse_doctor(json.dumps({**DOCTOR, "ok": True})).lines()[0].endswith("all good")


@pytest.mark.parametrize("text", ["", "no json", "{bad", "[1]", '{"checks": 3}'])
def test_doctor_report_errors_are_plain(text):
    with pytest.raises(ValueError):
        mt.parse_doctor(text)


# ------------------------------------------------------------------ removal safety

def test_removal_refuses_dangerous_or_foreign_folders(tmp_path):
    assert mt.removal_problems("")
    assert "full path" in mt.removal_problems("relative")[0]
    assert "drive root" in mt.removal_problems(Path(tmp_path.anchor))[0]
    assert "drive root" in mt.removal_problems(Path.home())[0]
    assert "does not exist" in mt.removal_problems(tmp_path / "nope")[0]
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "photos.jpg").write_text("x")
    assert "does not look like" in mt.removal_problems(plain)[0]
    assert "contains Studio" in mt.removal_problems(tmp_path, studio_root=tmp_path / "sub")[0]
    assert mt.removal_problems(installed(tmp_path)) == []
    git_only = tmp_path / "git"
    (git_only / ".git").mkdir(parents=True)
    assert mt.removal_problems(git_only) == []


def test_removal_refuses_a_link(tmp_path):
    real = installed(tmp_path)
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted")
    assert "link" in mt.removal_problems(link)[0]


def test_personal_contents_and_remove_tree(tmp_path):
    folder = installed(tmp_path)
    (folder / "outputs").mkdir()
    (folder / "projects").mkdir()
    (folder / "projects" / "song.json").write_text("{}")
    (folder / "cache").mkdir()  # empty: not listed
    assert mt.personal_contents(folder) == ["projects"]
    readonly = folder / "backend" / "morphorum" / "x.txt"
    readonly.write_text("x")
    os.chmod(readonly, 0o444)
    mt.remove_tree(folder)
    assert not folder.exists()


# ------------------------------------------------------------------ driver

def driver(**kw):
    made = []

    def factory():
        process = FakeProcess()
        made.append(process)
        _MADE.append(process)
        return process

    d = mm.MaintenanceDriver(process_factory=factory, threaded=False, **kw)
    _MADE.append(d)
    d.made = made
    d.events = []
    d.finished.connect(lambda job, ok, message: d.events.append((job, ok, message)))
    return d


def test_update_runs_the_script_and_reports_success(tmp_path):
    d = driver()
    assert d.update(str(tmp_path)) and d.busy and d.job == mm.UPDATE
    assert not d.repair(str(tmp_path))  # one job at a time
    process = d.made[0]
    assert process.args[-1].endswith("update_windows.ps1") and process.cwd == str(tmp_path)
    process.say("  >> Updating\n  [+] Done\n")
    process.finish(0)
    assert d.events == [(mm.UPDATE, True, "Update finished.")] and not d.busy
    assert any("Done" in line for line in d.lines)


def test_update_failure_is_detected_from_the_exit_code_and_from_output(tmp_path):
    d = driver()
    d.update(str(tmp_path))
    d.made[0].finish(2)
    assert d.events[-1][1] is False and "failed (code 2)" in d.events[-1][2]
    d.repair(str(tmp_path))
    d.made[1].say("  [X] REPAIR FAILED\n")
    d.made[1].finish(0)
    assert d.events[-1][:2] == (mm.REPAIR, False)


def test_branch_switch_passes_the_branch_and_rejects_bad_names(tmp_path):
    d = driver()
    assert not d.update(str(tmp_path), "bad branch") and not d.busy
    assert d.update(str(tmp_path), "dev-backend") and d.job == mm.SWITCH
    assert d.made[0].args[-2:] == ["-Branch", "dev-backend"]


def test_cancel_stops_the_script_and_says_so(tmp_path):
    killed = []
    d = driver(killer=killed.append)
    d.update(str(tmp_path))
    d.cancel()
    assert killed == [d.made[0]]
    d.made[0].finish(1)
    assert d.events[-1] == (mm.UPDATE, False, "Update was cancelled.")


def test_health_check_parses_the_report_and_keeps_json_out_of_the_log(tmp_path):
    d = driver()
    reports = []
    d.doctor_done.connect(lambda report, message: reports.append((report, message)))
    d.health_check(str(tmp_path))
    d.made[0].say(json.dumps(DOCTOR) + "\n")
    d.made[0].finish(1)
    assert reports[0][0].ok is False and d.events[-1][:2] == (mm.DOCTOR, False)
    assert not any(line.startswith("{") for line in d.lines) and any("PROBLEM" in line for line in d.lines)
    d.health_check(str(tmp_path))
    d.made[1].say("garbage")
    d.made[1].finish(0)
    assert reports[1][0] is None and d.events[-1][1] is False


def test_program_that_cannot_start_ends_the_job(tmp_path):
    from PySide6.QtCore import QProcess

    d = driver()
    d.repair(str(tmp_path))
    d.made[0].errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    assert d.events[-1][1] is False and not d.busy


def test_check_and_remove_run_through_injected_workers(tmp_path):
    folder = installed(tmp_path)
    removed = []
    d = driver(checker=lambda f: mt.GitStatus("main", "abc", behind=1), remover=removed.append)
    statuses = []
    d.checked.connect(statuses.append)
    assert d.check_for_updates(str(folder))
    assert statuses[0].update_available and d.events[-1] == (mm.CHECK, True, "Checked.")
    assert d.remove(str(folder)) and removed == [str(folder)]
    assert d.events[-1] == (mm.REMOVE, True, "The folder was removed.")
    assert not d.remove(str(tmp_path / "missing"))  # refused by the safety check


def test_remove_failure_is_explained(tmp_path):
    def boom(_folder):
        raise PermissionError(13, "Access is denied")

    d = driver(remover=boom)
    d.remove(str(installed(tmp_path)))
    assert d.events[-1][1] is False and "Access is denied" in d.events[-1][2]


# ------------------------------------------------------------------ panel

def panel_rig(tmp_path, **kw):
    d = driver(checker=kw.pop("checker", lambda f: mt.GitStatus("main", "abc", behind=1, branches=("dev", "main"))),
               remover=kw.pop("remover", lambda f: mt.remove_tree(f)))
    answers = kw.pop("answers", [True])
    asked = []

    def confirm(name, personal):
        asked.append((name, personal))
        return answers[0]

    r = PanelRig(tmp_path, panel_kw={"maintenance": d, "confirm_remove": confirm})
    r.maintenance, r.asked = d, asked
    r.choose()
    return r


def test_card_is_hidden_without_a_folder_and_shows_install_info(tmp_path):
    r = PanelRig(tmp_path, panel_kw={"maintenance": driver()})
    r.holder.show()
    assert not r.panel.maint_card.isVisible()
    r.choose()
    assert r.panel.maint_card.isVisible()
    assert r.panel.install_info.text() == "Morphorum"  # no install.json in the fake install


def test_check_enables_update_and_lists_branches(tmp_path):
    r = panel_rig(tmp_path)
    p = r.panel
    assert not p.update_button.isEnabled() and p.check_button.isEnabled() and p.repair_button.isEnabled()
    p.check_button.click()
    assert "1 update(s) available" in p.maint_note.text()
    assert p.update_button.isEnabled()
    assert [p.branch_box.itemText(i) for i in range(p.branch_box.count())] == ["dev", "main"]
    assert p.branch_box.currentText() == "main" and not p.switch_button.isEnabled()
    p.branch_box.setCurrentText("dev")
    p._update()
    assert p.switch_button.isEnabled()


def test_local_changes_block_update_and_switch(tmp_path):
    r = panel_rig(tmp_path, checker=lambda f: mt.GitStatus("main", "a", behind=1, dirty=True, branches=("dev", "main")))
    p = r.panel
    p.check_button.click()
    assert "Local changes" in p.maint_note.text()
    p.branch_box.setCurrentText("dev")
    p._update()
    assert not p.update_button.isEnabled() and not p.switch_button.isEnabled()
    p.update_backend()
    assert not r.maintenance.busy


def test_update_runs_only_while_the_backend_is_stopped(tmp_path):
    r = panel_rig(tmp_path)
    p = r.panel
    p.check_button.click()
    profile = r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    r.vault.set(profile.id, "kept")
    p.start()
    assert r.rig.backend.owned
    for button in (p.update_button, p.repair_button, p.doctor_button, p.remove_button, p.switch_button):
        assert not button.isEnabled()
    p.repair()
    p.update_backend()
    assert not r.maintenance.busy


def test_update_flow_rechecks_afterwards(tmp_path):
    r = panel_rig(tmp_path)
    p = r.panel
    p.check_button.click()
    p.update_button.click()
    assert r.maintenance.job == mm.UPDATE and p.log_toggle.isChecked()
    assert not p.check_button.isEnabled() and not p.remove_button.isEnabled()  # busy
    process = r.maintenance.made[0]
    process.say("  [+] updated\n")
    process.finish(0)
    assert not r.maintenance.busy and p.git_status is not None  # re-checked after a successful update


def test_failed_repair_shows_the_reason_and_keeps_status(tmp_path):
    r = panel_rig(tmp_path)
    r.panel.repair_button.click()
    r.maintenance.made[0].finish(3)
    assert "failed (code 3)" in r.panel.maint_note.text() and r.panel.repair_button.isEnabled()


def test_remove_needs_confirmation_and_forgets_the_connection(tmp_path):
    answers = [False]
    r = panel_rig(tmp_path, answers=answers)
    p = r.panel
    (r.folder / "projects").mkdir()
    (r.folder / "projects" / "a.json").write_text("{}")
    r.connections.ensure_managed_profile("http://127.0.0.1:7866")
    p.remove_button.click()
    assert r.asked == [(r.folder.name, ["projects"])] and r.folder.exists()  # declined: nothing happens
    assert r.connections.managed_profile() is not None
    answers[0] = True
    p.remove_button.click()
    assert not r.folder.exists()
    assert r.connections.managed_profile() is None
    assert p.settings.folder == "" and p.chip.text() == "No folder"
    assert managed.ManagedStore(tmp_path / "managed.json").load().folder == ""


def test_remove_is_refused_for_a_folder_that_is_not_morphorum(tmp_path):
    r = panel_rig(tmp_path)
    (r.folder / "backend" / "morphorum").rmdir()
    (r.folder / "backend").rmdir()
    for item in sorted(r.folder.rglob("*"), reverse=True):
        item.unlink() if item.is_file() else item.rmdir()
    (r.folder / "holiday.jpg").write_text("x")
    r.panel.remove_folder()
    assert not r.asked and r.folder.exists() and "does not look like" in r.panel.maint_note.text()


def test_remove_failure_keeps_settings(tmp_path):
    def boom(_folder):
        raise PermissionError(13, "Access is denied")

    r = panel_rig(tmp_path, remover=boom)
    r.panel.remove_button.click()
    assert "Access is denied" in r.panel.maint_note.text()
    assert r.panel.settings.folder == str(r.folder)


def test_remove_managed_profile_without_a_profile_is_fine(tmp_path):
    r = PanelRig(tmp_path, panel_kw={"maintenance": driver()})
    assert r.connections.remove_managed_profile() is True
