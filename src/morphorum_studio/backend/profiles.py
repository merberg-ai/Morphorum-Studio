"""Nonsecret named backend profiles, persisted atomically in user config."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import uuid

from .client import normalize_base_url


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

    @classmethod
    def create(cls, name: str, url: str) -> "ConnectionProfile":
        if not name.strip():
            raise ValueError("Connection name required")
        return cls(uuid.uuid4().hex, name.strip(), normalize_base_url(url))


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_profile_path()

    def load(self) -> list[ConnectionProfile]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported connection profile schema")
        result = []
        for item in data["profiles"]:
            profile = ConnectionProfile(**item)
            profile.url = normalize_base_url(profile.url)
            result.append(profile)
        return result

    def save(self, profiles: list[ConnectionProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "profiles": [asdict(p) for p in profiles]}
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        finally:
            tmp.unlink(missing_ok=True)
