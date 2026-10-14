"""Keeping a Studio-managed Morphorum folder healthy: update checks, the backend's own update
and repair scripts, a health report, and removal.

Studio never edits the backend's source itself. Updating, switching branch and repairing run the
backend's own guarded scripts (they refuse to touch local changes, keep a backup and roll back on
failure). Everything here is pure or takes an injectable ``run`` so it can be tested.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .managed import check_folder, python_path, valid_branch

CREATE_NO_WINDOW = 0x08000000
GIT_TIMEOUT = 90
Run = Callable[[list[str], int], tuple[int, str]]
# Top-level folders that hold the person's own work or large downloads.
PERSONAL_FOLDERS = ("projects", "outputs", "data", "backups", "ckpts", "logs", "cache")


def default_run(args: list[str], timeout: int = GIT_TIMEOUT) -> tuple[int, str]:
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=flags)
    return done.returncode, done.stdout


@dataclass(frozen=True)
class GitStatus:
    branch: str = ""
    commit: str = ""
    behind: int = 0  # commits on the remote branch that this copy lacks
    ahead: int = 0
    dirty: bool = False  # tracked files changed locally
    branches: tuple[str, ...] = ()  # branches on the remote
    error: str = ""

    @property
    def update_available(self) -> bool:
        return self.behind > 0


def read_install_info(folder: str | os.PathLike) -> dict:
    """What the backend's installer recorded about this copy (version, branch, commit); {} if unknown."""
    try:
        data = json.loads((Path(folder) / "data" / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def describe_install(folder: str | os.PathLike) -> str:
    info = read_install_info(folder)
    version = info.get("morphorum_version")
    branch, commit = info.get("git_branch"), info.get("git_commit")
    parts = [f"Morphorum {version}" if isinstance(version, str) and version else "Morphorum"]
    if isinstance(branch, str) and branch:
        parts.append(f"branch {branch}")
    if isinstance(commit, str) and commit:
        parts.append(f"commit {commit[:8]}")
    return " · ".join(parts)


def check_updates(folder: str | os.PathLike, run: Run = default_run) -> GitStatus:
    """Fetch from the remote and compare. Never raises; problems come back in ``error``."""
    git = ["git", "-C", str(folder)]

    def out(*args: str, timeout: int = GIT_TIMEOUT) -> str:
        code, text = run([*git, *args], timeout)
        if code != 0:
            raise ValueError(args[0])
        return text.strip()

    try:
        branch = out("rev-parse", "--abbrev-ref", "HEAD")
        commit = out("rev-parse", "--short=12", "HEAD")
    except (OSError, ValueError, subprocess.SubprocessError):
        return GitStatus(error="This folder is not a Git copy of Morphorum, so Studio cannot check for updates.")
    try:
        out("fetch", "origin", "--prune", timeout=GIT_TIMEOUT)
    except (OSError, ValueError, subprocess.SubprocessError):
        return GitStatus(branch, commit, error="Could not reach GitHub. Check the connection and try again.")
    try:
        names = out("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").splitlines()
        branches = tuple(sorted({n[len("origin/"):] for n in names
                                 if n.startswith("origin/") and n != "origin/HEAD" and valid_branch(n[7:])}))
        dirty = bool(out("status", "--porcelain", "--untracked-files=no"))
        behind = ahead = 0
        if branch in branches:
            behind = int(out("rev-list", "--count", f"HEAD..origin/{branch}"))
            ahead = int(out("rev-list", "--count", f"origin/{branch}..HEAD"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return GitStatus(branch, commit, error="Git could not compare this copy with GitHub.")
    return GitStatus(branch, commit, behind, ahead, dirty, branches)


def script_command(folder: Path, script: str, *extra: str) -> tuple[str, list[str]]:
    return "powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                              str(Path(folder) / "scripts" / script), *extra]


def update_command(folder: Path, branch: str | None = None) -> tuple[str, list[str]]:
    """The backend's guarded updater; with ``branch`` it also switches to that branch."""
    if branch is not None:
        if not valid_branch(branch):
            raise ValueError("That is not a usable branch name.")
        return script_command(folder, "update_windows.ps1", "-Branch", branch)
    return script_command(folder, "update_windows.ps1")


def repair_command(folder: Path) -> tuple[str, list[str]]:
    return script_command(folder, "repair_windows.ps1")


def doctor_command(folder: Path) -> tuple[str, list[str]]:
    return str(python_path(folder)), ["-m", "morphorum", "doctor", "--json"]


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    version: str
    branch: str
    commit: str
    checks: tuple[tuple[str, bool, str], ...] = field(default_factory=tuple)

    def lines(self) -> list[str]:
        head = f"Health check: {'all good' if self.ok else 'needs attention'}"
        return [head] + [f"  {'OK     ' if ok else 'PROBLEM'}  {name}: {detail}" for name, ok, detail in self.checks]


def parse_doctor(text: str) -> DoctorReport:
    """The backend's ``doctor --json`` output (log lines before the JSON are tolerated). Raises ValueError."""
    start = text.find("{")
    if start < 0:
        raise ValueError("The health check printed no report.")
    try:
        data = json.JSONDecoder().raw_decode(text[start:])[0]
    except ValueError as exc:
        raise ValueError("The health check report could not be read.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise ValueError("The health check report was not in the expected form.")
    checks = []
    for item in data["checks"][:60]:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            checks.append((item["name"][:60], item.get("ok") is True, str(item.get("detail", ""))[:200]))
    return DoctorReport(data.get("ok") is True, str(data.get("version", ""))[:40], str(data.get("branch", ""))[:60],
                        str(data.get("commit", ""))[:40], tuple(checks))


# ---------------------------------------------------------------------------- removal

def removal_problems(folder: str | os.PathLike, studio_root: str | os.PathLike | None = None) -> list[str]:
    """Reasons Studio must not delete ``folder`` (empty list: it is a Morphorum folder and safe to remove)."""
    if not folder:
        return ["No folder is set up."]
    path = Path(folder)
    if not path.is_absolute():
        return ["The folder must be a full path."]
    if path == Path(path.anchor) or path == Path.home():
        return ["Studio will not remove a drive root or your home folder."]
    if not path.is_dir():
        return ["That folder does not exist."]
    if path.is_symlink():
        return ["That folder is a link, so Studio will not remove it."]
    if studio_root is not None:
        root = Path(studio_root).resolve()
        here = path.resolve()
        if here == root or here in root.parents:
            return ["That folder contains Studio itself."]
    if not (check_folder(path).ok or (path / ".git").exists() or (path / "data" / "install.json").is_file()):
        return ["That folder does not look like a Morphorum install, so Studio will not remove it."]
    return []


def personal_contents(folder: str | os.PathLike) -> list[str]:
    """Names of folders inside that probably hold the person's own work or large downloads."""
    path = Path(folder)
    return [name for name in PERSONAL_FOLDERS if (path / name).is_dir() and any((path / name).iterdir())]


def _unlock(function, target, _error) -> None:
    os.chmod(target, stat.S_IWRITE)  # Git objects are read-only on Windows
    function(target)


def remove_tree(folder: str | os.PathLike) -> None:
    """Delete the folder and everything in it. Raises OSError when something cannot be removed."""
    path = Path(folder)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_unlock)
    else:
        shutil.rmtree(path, onerror=_unlock)
