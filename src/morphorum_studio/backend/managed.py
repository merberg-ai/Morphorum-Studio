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
ALL_INTERFACES = "0.0.0.0"
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
    auto_restart: bool = True  # start the backend again if it stops unexpectedly
    lan: bool = False  # listen on the local network instead of this PC only


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
    for key in ("stop_on_exit", "autostart", "auto_restart", "lan"):
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

def serve_command(folder: Path, port: int, lan: bool = False) -> tuple[str, list[str]]:
    """Run the API-only server: on loopback, or on every interface only when ``lan`` was chosen."""
    return str(python_path(folder)), ["-m", "morphorum", "serve", "--host", ALL_INTERFACES if lan else LOOPBACK,
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


# ---------------------------------------------------------------------------- installing
#
# Studio does not reimplement the backend's installer. It downloads the backend's own
# ``scripts/bootstrap.ps1`` for the chosen branch and runs it with an explicit folder, branch
# and port, so the installer never has to ask a question. Only the person's consent starts it.

REPO = "merberg-ai/Morphorum"
DEFAULT_BRANCH = "main"
BOOTSTRAP_URL = "https://raw.githubusercontent.com/" + REPO + "/{branch}/scripts/bootstrap.ps1"
MIN_FREE_BYTES = 8 * 1024**3  # the backend's own installer wants 8 GiB free
MAX_BOOTSTRAP_BYTES = 512 * 1024
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
_MARKER = re.compile(r"^\s*(>>|\[>\]|\[\+\]|\[!\]|\[X\])\s*(.*)$")
KIND_SECTION, KIND_STEP, KIND_OK, KIND_WARN, KIND_FAIL, KIND_TEXT = (
    "section", "step", "ok", "warn", "fail", "text")
_MARKER_KIND = {">>": KIND_SECTION, "[>]": KIND_STEP, "[+]": KIND_OK, "[!]": KIND_WARN, "[X]": KIND_FAIL}


def valid_branch(branch: str) -> bool:
    return bool(_BRANCH.fullmatch(branch)) and ".." not in branch and not branch.endswith(("/", ".lock"))


def bootstrap_url(branch: str = DEFAULT_BRANCH) -> str:
    if not valid_branch(branch):
        raise ValueError("That is not a usable branch name.")
    return BOOTSTRAP_URL.format(branch=branch)


def is_checkout(folder: str | os.PathLike) -> bool:
    """A folder the backend's installer may resume: a git checkout or an install marker."""
    path = Path(folder)
    return (path / ".git").exists() or (path / "data" / "install.json").is_file()


@dataclass
class Preflight:
    problems: list[str]  # any of these stops the install
    warnings: list[str]
    resume: bool = False  # an unfinished checkout will be continued, not replaced

    @property
    def ok(self) -> bool:
        return not self.problems


def _nearest_existing(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path


def _free_bytes(path: Path) -> int | None:
    import shutil
    try:
        return shutil.disk_usage(_nearest_existing(path)).free
    except OSError:
        return None


def preflight(folder: str, port: int, branch: str = DEFAULT_BRANCH, *, windows: bool | None = None,
              free_bytes: int | None = None) -> Preflight:
    """Everything that can be checked before touching the disk. Never raises."""
    windows = (os.name == "nt") if windows is None else windows
    problems: list[str] = []
    warnings: list[str] = []
    resume = False
    if not windows:
        problems.append("Installing from Studio is available on Windows. "
                        "On this system, install Morphorum yourself and choose its folder.")
    if not valid_branch(branch):
        problems.append("The backend branch name is not valid.")
    if type(port) is not int or not 1 <= port <= 65535:
        problems.append("The port must be between 1 and 65535.")
    if not folder or _CONTROL.search(folder):
        problems.append("Choose a folder for the backend.")
        return Preflight(problems, warnings)
    path = Path(folder)
    if not path.is_absolute():
        problems.append("The folder must be a full path.")
        return Preflight(problems, warnings)
    if path == Path(path.anchor):
        problems.append("Choose a folder, not a drive root.")
        return Preflight(problems, warnings)
    if path.exists():
        if not path.is_dir():
            problems.append("That path is a file, not a folder.")
        elif is_checkout(path):
            resume = True
        elif any(path.iterdir()):
            problems.append("That folder is not empty and is not a Morphorum folder. Choose an empty or new folder.")
    parent = _nearest_existing(path)
    if not os.access(parent, os.W_OK):
        problems.append("Studio cannot write to that location. Choose another folder.")
    free = _free_bytes(path) if free_bytes is None else free_bytes
    if free is not None and free < MIN_FREE_BYTES and not resume:
        problems.append(f"At least {MIN_FREE_BYTES // 1024**3} GiB of free space is needed; "
                        f"{free / 1024**3:.1f} GiB is available.")
    if windows and len(str(path)) > 120:
        warnings.append("This path is long. Windows can fail on long paths; a shorter folder is safer.")
    if windows and not path.anchor.upper().startswith(os.environ.get("SystemDrive", "C:").upper()):
        warnings.append("This is not the system drive. Git and FFmpeg still install on the system drive.")
    if port_open(port):
        warnings.append(f"Port {port} is in use right now. You can change the port after installing.")
    return Preflight(problems, warnings, resume)


def install_command(script: Path, folder: Path, branch: str, port: int) -> tuple[str, list[str]]:
    """The backend's own bootstrap, given every answer up front so it never prompts."""
    if not valid_branch(branch):
        raise ValueError("That is not a usable branch name.")
    return "powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                              "-InstallDir", str(folder), "-Branch", branch, "-Port", str(int(port))]


def parse_install_line(line: str) -> tuple[str, str]:
    """Classify one line of installer output by the markers the backend prints."""
    text = clean_log_line(line).strip()
    found = _MARKER.match(text)
    if found:
        return _MARKER_KIND[found.group(1)], found.group(2).strip()
    return KIND_TEXT, text


def fetch_bootstrap(url: str, dest: Path, opener=None) -> None:
    """Download the backend's bootstrap script (https only, size-capped). Raises OSError."""
    import urllib.error
    import urllib.request

    if not url.startswith("https://raw.githubusercontent.com/"):
        raise OSError("Refusing to download the installer from an unexpected address.")
    open_url = opener or (lambda u: urllib.request.urlopen(u, timeout=30))
    try:
        with open_url(url) as response:
            data = response.read(MAX_BOOTSTRAP_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise OSError(f"Could not download the installer: {getattr(exc, 'reason', exc)}") from exc
    if not data or len(data) > MAX_BOOTSTRAP_BYTES or b"InstallDir" not in data:
        raise OSError("The downloaded installer does not look right, so it was not run.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


# ---------------------------------------------------------------------------- lifecycle helpers

LAN_WARNING = (
    "Other computers on your network will be able to reach this backend. It asks for a credential, "
    "but traffic is plain HTTP and not encrypted. Use this only on a network you trust, never on the "
    "internet. Windows may ask to allow the connection through its firewall."
)


def lan_address(port: int) -> str:
    """This PC's address on the local network as other computers would use it, or '' if unknown."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # no packet is sent; this only selects the outgoing interface
        host = probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()
    return f"http://{host}:{int(port)}" if host and not host.startswith("127.") else ""


def parse_listening_pid(netstat: str, port: int) -> int | None:
    """The PID listening on ``port`` in the output of ``netstat -ano -p tcp``."""
    suffix = f":{int(port)}"
    for line in netstat.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING" \
                and parts[1].endswith(suffix):
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


def parse_process_name(tasklist_csv: str) -> str:
    """The image name from one ``tasklist /FO CSV /NH`` row, or ''."""
    line = tasklist_csv.strip().splitlines()[0] if tasklist_csv.strip() else ""
    if line.startswith('"'):
        name = line.split('","')[0].lstrip('"')
        return "" if name.upper().startswith("INFO:") else name
    return ""


def describe_port_owner(port: int, run=None) -> str:
    """Best effort, Windows only: 'python.exe (PID 1234)' for whatever listens on ``port``; '' if unknown."""
    if os.name != "nt" and run is None:
        return ""
    import subprocess

    def default_run(args: list[str]) -> str:
        return subprocess.run(args, capture_output=True, text=True, timeout=5,
                              creationflags=0x08000000).stdout

    run = run or default_run
    try:
        pid = parse_listening_pid(run(["netstat", "-ano", "-p", "tcp"]), port)
        if pid is None:
            return ""
        name = parse_process_name(run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]))
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{name} (PID {pid})" if name else f"PID {pid}"
