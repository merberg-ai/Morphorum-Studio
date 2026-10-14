"""Nonsecret named backend profiles, persisted atomically in user config."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import uuid

from .client import BackendError, normalize_base_url


def default_profile_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "Morphorum-Studio" / "connections.json"


@dataclass
class ConnectionProfile:
    id: str
    name: str
    url: str
    instance_id: str = ""
    boot_id: str = ""
    kind: str = "remote"  # "managed": the local backend Studio runs itself (see managed.py)

    @classmethod
    def create(cls, name: str, url: str) -> "ConnectionProfile":
        if not name.strip():
            raise ValueError("Connection name required")
        return cls(uuid.uuid4().hex, name.strip(), normalize_base_url(url))


@dataclass
class LoadResult:
    """Profiles that could be read, plus a user-facing warning if anything was skipped."""

    profiles: list[ConnectionProfile]
    warning: str | None = None
    backup: Path | None = None


_PROFILE_FIELDS = {f.name for f in fields(ConnectionProfile)}


def _parse_profile(item: object) -> ConnectionProfile:
    """Strictly build one profile; raises ValueError for anything unusable."""
    if not isinstance(item, dict):
        raise ValueError("profile entry is not an object")
    # Unknown keys (for example from a newer Studio) are ignored rather than fatal.
    data = {k: v for k, v in item.items() if k in _PROFILE_FIELDS}
    if not all(isinstance(data.get(k), str) and data[k] for k in ("id", "name", "url")):
        raise ValueError("profile is missing id, name or url")
    for key in ("instance_id", "boot_id"):
        if not isinstance(data.get(key, ""), str):
            raise ValueError(f"profile {key} is not text")
    if data.get("kind", "remote") not in ("remote", "managed"):
        raise ValueError("profile kind is not recognised")
    try:
        profile = ConnectionProfile(**data)
        profile.url = normalize_base_url(profile.url)
    except BackendError as exc:
        raise ValueError(str(exc)) from exc
    return profile


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_profile_path()

    def load(self) -> list[ConnectionProfile]:
        """Strict load. Raises ValueError (or OSError) if the file is unusable."""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except UnicodeError as exc:
            raise ValueError("connection profile file is not valid UTF-8") from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported connection profile schema")
        entries = data.get("profiles")
        if not isinstance(entries, list):
            raise ValueError("connection profile file has no profile list")
        return [_parse_profile(item) for item in entries]

    def load_recovering(self) -> LoadResult:
        """Load what is usable; never raise because of a damaged or newer-format file.

        If anything has to be skipped, the original file is first copied to a timestamped
        ``.recovered-*`` sibling so a later save cannot destroy the only copy.
        """
        if not self.path.exists():
            return LoadResult([])
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("unsupported schema version")
            entries = data.get("profiles")
            if not isinstance(entries, list):
                raise ValueError("missing profile list")
        except (OSError, ValueError) as exc:  # JSONDecodeError and UnicodeError are ValueErrors
            backup = self._backup()
            return LoadResult([], self._message(
                f"The saved connections file could not be read ({exc}). "
                "Starting with no saved connections.", backup), backup)
        profiles: list[ConnectionProfile] = []
        skipped = 0
        for item in entries:
            try:
                profiles.append(_parse_profile(item))
            except ValueError:
                skipped += 1
        if not skipped:
            return LoadResult(profiles)
        backup = self._backup()
        return LoadResult(profiles, self._message(
            f"{skipped} saved connection(s) were unreadable and skipped.", backup), backup)

    def _backup(self) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = self.path.with_name(f"{self.path.name}.recovered-{stamp}")
        try:
            shutil.copy2(self.path, target)
        except OSError:
            return None
        return target

    @staticmethod
    def _message(text: str, backup: Path | None) -> str:
        if backup is None:
            return text + " A backup copy could not be made."
        return f"{text} The original was kept as {backup.name}."

    def save(self, profiles: list[ConnectionProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "profiles": [asdict(p) for p in profiles]}
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            # Created owner-only from the start (mode is ignored on Windows).
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
            fd = os.open(tmp, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        finally:
            tmp.unlink(missing_ok=True)
