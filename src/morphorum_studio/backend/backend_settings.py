"""The backend's own settings, as the Morphorum web UI edits them (model folders, managed model
storage and memory behaviour). Studio shows only what the backend reports and sends only what
changed. The web UI's browser look-and-feel settings (theme, fonts, scale, preview count) are
about that web page, so Studio leaves them alone.

Paths are on the backend's computer. Relative paths are resolved by the backend.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .client import BackendClient, BackendError
from .schema import _object, _text

MAX_FAMILIES = 20
MAX_PATHS = 200
MAX_PATH = 1024
PATH_KEYS = ("checkpoints", "loras")
PERFORMANCE_FLAGS = (
    ("unload_after_generation", "Unload after generation",
     "Unload the model only after the whole batch has finished, freeing GPU memory between runs."),
    ("sdxl_vae_tiling", "SDXL VAE tiling",
     "Decode SDXL images in tiles to use less GPU memory, which can be a little slower."),
)


@dataclass(frozen=True)
class Family:
    id: str
    label: str
    external: bool  # checkpoints are folders the person points at
    loras: bool  # LoRA folders are configurable
    managed: bool  # Morphorum stores this family's downloads in a folder it manages


@dataclass(frozen=True)
class PathCheck:
    path: str
    ok: bool
    message: str


@dataclass(frozen=True)
class BackendSettings:
    families: tuple[Family, ...]
    paths: dict[str, dict[str, list[str]]]  # family -> kind -> folders
    managed: dict[str, str]  # managed family -> storage folder
    flags: dict[str, bool]
    checks: dict[tuple[str, str], list[PathCheck]] = field(default_factory=dict)

    def copy(self) -> BackendSettings:
        return BackendSettings(self.families, copy.deepcopy(self.paths), dict(self.managed), dict(self.flags),
                               dict(self.checks))


def _path_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:MAX_PATHS]:
        text = _text(item, MAX_PATH)
        if text:
            out.append(text)
    return out


def _check(item: Mapping[str, Any]) -> PathCheck | None:
    path = _text(item.get("path"), MAX_PATH)
    if path is None:
        return None
    ok = item.get("is_directory") is True and item.get("readable") is True
    if item.get("exists") is False:
        message = "This folder does not exist yet."
    elif item.get("is_directory") is False:
        message = "This is not a folder."
    elif item.get("readable") is False:
        message = "The backend cannot read this folder."
    else:
        message = "Folder found."
    return PathCheck(path, ok, message)


def parse_settings(payload: Any) -> BackendSettings:
    root = _object(payload, "Settings")
    settings = _object(root.get("settings"), "Settings")
    families: list[Family] = []
    raw_families = root.get("model_families")
    for item in (raw_families if isinstance(raw_families, list) else [])[:MAX_FAMILIES]:
        if not isinstance(item, Mapping):
            continue
        fid = _text(item.get("id"), 40)
        if not fid:
            continue
        source = item.get("source") == "external"
        families.append(Family(
            fid, _text(item.get("label"), 60) or fid, source,
            item.get("supports_loras") is True and item.get("lora_source", "external") == "external",
            item.get("source") == "managed"))
    if not families:
        raise BackendError("INVALID_RESPONSE", "The backend did not describe its model families")
    models = settings.get("models") if isinstance(settings.get("models"), Mapping) else {}
    paths: dict[str, dict[str, list[str]]] = {}
    for fam in families:
        entry = models.get(fam.id) if isinstance(models.get(fam.id), Mapping) else {}
        paths[fam.id] = {kind: _path_list(entry.get(kind)) for kind in PATH_KEYS
                         if (kind == "checkpoints" and fam.external) or (kind == "loras" and fam.loras)}
    locations = {}
    managed_root = settings.get("managed_models")
    raw_locations = managed_root.get("locations") if isinstance(managed_root, Mapping) else None
    for fam in families:
        if fam.managed:
            text = _text(raw_locations.get(fam.id), MAX_PATH) if isinstance(raw_locations, Mapping) else None
            locations[fam.id] = text or ""
    perf = settings.get("performance") if isinstance(settings.get("performance"), Mapping) else {}
    flags = {key: perf.get(key) is True for key, _label, _help in PERFORMANCE_FLAGS}
    checks: dict[tuple[str, str], list[PathCheck]] = {}
    validation = root.get("validation")
    for item in (validation if isinstance(validation, list) else [])[:MAX_PATHS * 6]:
        if isinstance(item, Mapping):
            fid, kind, found = _text(item.get("family"), 40), _text(item.get("kind"), 20), _check(item)
            if fid and kind and found:
                checks.setdefault((fid, kind), []).append(found)
    return BackendSettings(tuple(families), paths, locations, flags, checks)


@dataclass(frozen=True)
class ScanResult:
    total: int | None
    warnings: tuple[str, ...]
    counts: dict[str, dict[str, int]]  # family -> kind -> files found

    def describe(self, labels: dict[str, str] | None = None) -> str:
        labels = labels or {}
        if self.total is None:
            text = "Rescan finished."
        elif self.total == 0:
            text = ("The rescan found no models. Check the folders above hold .safetensors, .ckpt, .pt or .pth "
                    "files (checkpoints also accept .bin and .gguf).")
        else:
            parts = [f"{labels.get(f, f)} {k}: {n}" for f, kinds in self.counts.items() for k, n in kinds.items()]
            text = f"Rescan finished: {self.total} file(s) found" + (f" ({', '.join(parts)})." if parts else ".")
        if self.warnings:
            text += " " + " ".join(self.warnings[:3])
        return text


def parse_scan(reply: Any) -> ScanResult:
    reply = reply if isinstance(reply, Mapping) else {}
    total = reply.get("total")
    warnings = reply.get("warnings")
    notes = tuple(t for t in (_text(w, 300) for w in (warnings if isinstance(warnings, list) else [])[:20]) if t)
    counts: dict[str, dict[str, int]] = {}
    raw = reply.get("counts")
    for family, kinds in (raw.items() if isinstance(raw, Mapping) else []):
        if isinstance(kinds, Mapping) and isinstance(family, str):
            counts[family[:40]] = {str(k)[:20]: n for k, n in kinds.items() if type(n) is int and n >= 0}
    return ScanResult(total if type(total) is int and total >= 0 else None, notes, counts)


def build_update(before: BackendSettings, after: BackendSettings) -> dict[str, Any]:
    """The smallest PUT body that turns ``before`` into ``after`` (empty when nothing changed)."""
    body: dict[str, Any] = {}
    for family, kinds in after.paths.items():
        for kind, folders in kinds.items():
            clean = [f.strip() for f in folders if f.strip()]
            if clean != before.paths.get(family, {}).get(kind, []):
                body.setdefault("models", {}).setdefault(family, {})[kind] = clean
    for family, folder in after.managed.items():
        if folder.strip() != before.managed.get(family, ""):
            if not folder.strip():
                continue  # the backend always keeps a storage folder; an empty box means "unchanged"
            body.setdefault("managed_models", {}).setdefault("locations", {})[family] = folder.strip()
    for key, value in after.flags.items():
        if value != before.flags.get(key):
            body.setdefault("performance", {})[key] = bool(value)
    return body


class SettingsApi:
    def __init__(self, client: BackendClient) -> None:
        self.client = client

    def load(self) -> BackendSettings:
        return parse_settings(self.client.get_json("/api/settings"))

    def save(self, update: Mapping[str, Any]) -> BackendSettings:
        reply, _etag = self.client.send_json("PUT", "/api/settings", update)
        if not isinstance(reply, Mapping) or reply.get("status") != "saved":
            raise BackendError("INVALID_RESPONSE", "The backend did not confirm the save")
        return parse_settings(reply)

    def check_path(self, path: str) -> PathCheck:
        reply, _etag = self.client.send_json("POST", "/api/settings/validate-path", {"path": path})
        found = _check({**_object(reply, "Path check"), "path": reply.get("path") or path})
        if found is None:
            raise BackendError("INVALID_RESPONSE", "The backend did not describe that folder")
        return found

    def rescan(self) -> ScanResult:
        """Ask the backend to rescan its model folders and report what it found."""
        reply, _etag = self.client.send_json("POST", "/api/models/scan", {})
        return parse_scan(reply)
