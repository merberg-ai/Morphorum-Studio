"""Studio-managed local backend: settings, folder checks and the commands used to run it.

Nothing here touches Qt or the network beyond a loopback port probe, so it can be tested
directly. The process itself is run by ``ui/managed_backend.py``.

Studio never installs PyTorch or CUDA on its own; it runs the backend's own installer in a
later step and, in this step, manages a Morphorum folder that already exists. It only ever
stops a backend process it started itself.
"""
from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .profiles import default_profile_path

KIND_MANAGED = "managed"
DEFAULT_PORT = 7866  # the backend's own backend-only default
FOLDER_NAME = "morphorum-backend"
CLIENT_NAME = "Morphorum Studio (managed)"
CLIENT_DAYS = 365  # the backend allows 1-365
LOOPBACK = "127.0.0.1"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def default_settings_path() -> Path:
    return default_profile_path().with_name("managed.json")


def default_folder() -> Path:
    """``<Studio folder>/morphorum-backend``; a per-user folder when Studio is not a source checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "morphorum_studio").is_dir():
            return parent / FOLDER_NAME
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "Morphorum-Studio" / FOLDER_NAME


@dataclass
class ManagedSettings:
    folder: str = ""
    port: int = DEFAULT_PORT
    stop_on_exit: bool = True
    autostart: bool = True  # start and connect when Studio opens, if this was the last backend used
    profile_id: str = ""  # the connection profile Studio keeps for this backend


_FIELDS = {f.name for f in fields(ManagedSettings)}


def _clean(data: object) -> ManagedSettings:
    if not isinstance(data, dict):
        return ManagedSettings()
    kept = {k: v for k, v in data.items() if k in _FIELDS}
    out = ManagedSettings()
    if isinstance(kept.get("folder"), str) and not _CONTROL.search(kept["folder"]):
        out.folder = kept["folder"]
    port = kept.get("port")
    if type(port) is int and 1 <= port <= 65535:
        out.port = port
    for key in ("stop_on_exit", "autostart"):
        if isinstance(kept.get(key), bool):
            setattr(out, key, kept[key])
    if isinstance(kept.get("profile_id"), str) and re.fullmatch(r"[0-9a-f]{32}", kept["profile_id"]):
        out.profile_id = kept["profile_id"]
    return out


class ManagedStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_settings_path()

    def load(self) -> ManagedSettings:
        """Never raises: an unreadable file means defaults (the folder is simply not chosen yet)."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ManagedSettings()
        return _clean(data)

    def save(self, settings: ManagedSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(asdict(_clean(asdict(settings))), indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------- the folder

def python_path(folder: Path) -> Path:
    sub = Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python"
    return Path(folder) / ".venv" / sub


def data_dir(folder: Path) -> Path:
    return Path(folder) / "data"


def read_version(folder: Path) -> str:
    try:
        text = (Path(folder) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text[:40] if re.fullmatch(r"[0-9A-Za-z.+_-]{1,40}", text[:40] or "x") else ""


@dataclass(frozen=True)
class FolderCheck:
    ok: bool
    problems: tuple[str, ...] = ()
    version: str = ""


def check_folder(path: str | os.PathLike | None) -> FolderCheck:
    """Is ``path`` an installed Morphorum folder Studio can run?"""
    if not path or _CONTROL.search(str(path)):
        return FolderCheck(False, ("Choose the folder where Morphorum is installed.",))
    folder = Path(path)
    if not folder.is_dir():
        return FolderCheck(False, ("That folder does not exist.",))
    problems = []
    if not (folder / "backend" / "morphorum").is_dir():
        problems.append("This does not look like a Morphorum folder (backend/morphorum is missing).")
    if not python_path(folder).is_file():
        problems.append("Morphorum is not installed here yet: its Python environment (.venv) is missing.")
    return FolderCheck(not problems, tuple(problems), read_version(folder))


# ---------------------------------------------------------------------------- commands

def serve_command(folder: Path, port: int) -> tuple[str, list[str]]:
    """Run the API-only server on loopback. LAN exposure is deliberately not offered here."""
    return str(python_path(folder)), ["-m", "morphorum", "serve", "--host", LOOPBACK,
                                      "--port", str(int(port)), "--backend-only"]


def issue_command(folder: Path, out: Path) -> tuple[str, list[str]]:
    return str(python_path(folder)), ["-m", "morphorum", "clients", "issue", CLIENT_NAME,
                                      "--days", str(CLIENT_DAYS), "--out", str(out)]


def environment(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1",
                "HF_HUB_DISABLE_PROGRESS_BARS": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
    env.pop("MORPHORUM_BACKEND_TOKEN", None)  # the child must not inherit a stray secret
    return env


def loopback_url(port: int) -> str:
    return f"http://{LOOPBACK}:{int(port)}"


def port_open(port: int, timeout: float = 0.15) -> bool:
    """True if something accepts connections on the loopback ``port``."""
    try:
        with socket.create_connection((LOOPBACK, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def free_port(start: int = DEFAULT_PORT, tries: int = 50) -> int | None:
    for port in range(start, min(start + tries, 65536)):
        if not port_open(port):
            return port
    return None


def read_issued_token(path: Path) -> str:
    """Read the one-time token file the backend wrote. Raises ValueError if it is not a single token."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError("The credential file was not created correctly.")
    token = path.read_text(encoding="utf-8-sig").strip()
    if not token or len(token) > 4096 or any(c.isspace() for c in token):
        raise ValueError("The credential file does not contain a single token.")
    return token


def clean_log_line(text: str) -> str:
    return _CONTROL.sub(" ", _ANSI.sub("", text)).rstrip()


# ---------------------------------------------------------------------------- run record

def default_record_path() -> Path:
    return default_profile_path().with_name("managed-run.json")


def write_record(path: Path, folder: str, port: int, pid: int) -> None:
    """Remember a backend this Studio started, so a later session can recognise it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"folder": folder, "port": int(port), "pid": int(pid)}), encoding="utf-8")


def read_record(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (isinstance(data, dict) and isinstance(data.get("folder"), str)
            and type(data.get("port")) is int and type(data.get("pid")) is int):
        return data
    return None


def clear_record(path: Path) -> None:
    Path(path).unlink(missing_ok=True)


def record_matches(record: dict | None, folder: str, port: int) -> bool:
    return bool(record) and record["port"] == int(port) and \
        os.path.normcase(os.path.abspath(record["folder"])) == os.path.normcase(os.path.abspath(folder))
