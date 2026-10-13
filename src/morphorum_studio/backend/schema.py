"""Typed, read-only views of backend system and model responses.

No Qt imports. Parsing is deliberately forgiving about *missing* data (a field the
backend did not report becomes ``None``, never a made-up zero) and strict about
*wrong* data (a value of the wrong type or out of range is treated as missing).
Only structurally unusable responses raise ``BackendError("INVALID_RESPONSE")``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .client import BackendError

MAX_TEXT = 160
MAX_MODELS = 2000

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


# ----------------------------------------------------------------------------- helpers

def _text(value: Any, limit: int = MAX_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _CONTROL.sub(" ", value).strip()
    return cleaned[:limit] or None


def _number(value: Any, low: float | None = None, high: float | None = None) -> float | None:
    """A finite real number inside [low, high], else None. Booleans are not numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if low is not None and number < low:
        return None
    if high is not None and number > high:
        return None
    return number


def _whole(value: Any, low: int = 0) -> int | None:
    number = _number(value, low)
    if number is None or number != int(number):
        return None
    return int(number)


def _object(payload: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise BackendError("INVALID_RESPONSE", f"{what} response was not a JSON object")
    return payload


# ----------------------------------------------------------------------------- telemetry

@dataclass(frozen=True)
class GpuDevice:
    index: int
    name: str
    utilization_percent: float | None = None
    memory_total_mib: float | None = None
    memory_used_mib: float | None = None
    memory_free_mib: float | None = None
    temperature_c: float | None = None

    @property
    def memory_used_fraction(self) -> float | None:
        if self.memory_total_mib and self.memory_used_mib is not None:
            return min(1.0, max(0.0, self.memory_used_mib / self.memory_total_mib))
        return None


@dataclass(frozen=True)
class RamInfo:
    total_bytes: int | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None
    used_percent: float | None = None


@dataclass(frozen=True)
class Telemetry:
    cpu_percent: float | None = None
    ram: RamInfo | None = None
    gpu_backend: str | None = None
    gpus: tuple[GpuDevice, ...] = ()


def parse_telemetry(payload: Any) -> Telemetry:
    data = _object(payload, "Telemetry")

    ram = None
    raw_ram = data.get("ram")
    if isinstance(raw_ram, Mapping):
        total = _whole(raw_ram.get("total_bytes"), 1)
        used = _whole(raw_ram.get("used_bytes"))
        if total is not None and used is not None and used > total:
            used = None  # Inconsistent: report unknown rather than something impossible.
        ram = RamInfo(
            total_bytes=total,
            used_bytes=used,
            available_bytes=_whole(raw_ram.get("available_bytes")),
            used_percent=_number(raw_ram.get("used_percent"), 0, 100),
        )

    gpu_backend = None
    gpus: list[GpuDevice] = []
    raw_gpu = data.get("gpu")
    if isinstance(raw_gpu, Mapping):
        gpu_backend = _text(raw_gpu.get("backend"), 40)
        devices = raw_gpu.get("devices")
        for item in devices if isinstance(devices, list) else []:
            if not isinstance(item, Mapping):
                continue
            index = _whole(item.get("index"))
            name = _text(item.get("name"))
            if index is None or name is None:
                continue
            total = _number(item.get("memory_total_mib"), 1)
            used = _number(item.get("memory_used_mib"), 0)
            if total is not None and used is not None and used > total:
                used = None
            gpus.append(GpuDevice(
                index=index,
                name=name,
                utilization_percent=_number(item.get("utilization_percent"), 0, 100),
                memory_total_mib=total,
                memory_used_mib=used,
                memory_free_mib=_number(item.get("memory_free_mib"), 0),
                temperature_c=_number(item.get("temperature_c"), -50, 200),
            ))
            if len(gpus) >= 16:
                break

    return Telemetry(
        cpu_percent=_number(data.get("cpu_percent"), 0, 100),
        ram=ram,
        gpu_backend=gpu_backend,
        gpus=tuple(gpus),
    )


# ----------------------------------------------------------------------------- GPU memory

@dataclass(frozen=True)
class GpuMemory:
    """Morphorum's own CUDA allocator view (not whole-machine VRAM; see telemetry for that)."""

    cuda_available: bool
    device_name: str | None = None
    total_gib: float | None = None
    free_gib: float | None = None
    allocated_gib: float | None = None
    reserved_gib: float | None = None
    model_loaded: bool = False
    model_name: str | None = None


def parse_gpu_memory(payload: Any) -> GpuMemory:
    data = _object(payload, "GPU memory")
    available = data.get("cuda_available")
    if not isinstance(available, bool):
        raise BackendError("INVALID_RESPONSE", "GPU memory response lacks cuda_available")
    cuda = data.get("cuda") if isinstance(data.get("cuda"), Mapping) else {}
    model = data.get("model") if isinstance(data.get("model"), Mapping) else {}
    return GpuMemory(
        cuda_available=available,
        device_name=_text(cuda.get("device_name")),
        total_gib=_number(cuda.get("total_gib"), 0),
        free_gib=_number(cuda.get("free_gib"), 0),
        allocated_gib=_number(cuda.get("allocated_gib"), 0),
        reserved_gib=_number(cuda.get("reserved_gib"), 0),
        model_loaded=model.get("loaded") is True,
        model_name=_text(model.get("model_name")),
    )


# ----------------------------------------------------------------------------- models

@dataclass(frozen=True)
class ModelFamily:
    id: str
    label: str
    supports_loras: bool = False
    source: str | None = None


def parse_families(payload: Any) -> tuple[ModelFamily, ...]:
    data = _object(payload, "Model families")
    items = data.get("families")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Model families response lacks a families list")
    result = []
    for item in items[:64]:
        if not isinstance(item, Mapping):
            continue
        family_id = item.get("id")
        if not isinstance(family_id, str) or not _ID.fullmatch(family_id):
            continue
        result.append(ModelFamily(
            id=family_id,
            label=_text(item.get("label"), 60) or family_id,
            supports_loras=item.get("supports_loras") is True,
            source=_text(item.get("source"), 20),
        ))
    return tuple(result)


@dataclass(frozen=True)
class ModelEntry:
    id: str
    family: str
    kind: str
    name: str
    filename: str | None = None
    size_bytes: int | None = None
    variant: str | None = None
    source: str | None = None


def parse_models(payload: Any) -> tuple[ModelEntry, ...]:
    """Server file-system paths in the response are intentionally dropped."""
    data = _object(payload, "Models")
    items = data.get("models")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Models response lacks a models list")
    result = []
    for item in items[:MAX_MODELS]:
        if not isinstance(item, Mapping):
            continue
        model_id = _text(item.get("id"), 200)
        family = item.get("family")
        kind = item.get("kind")
        name = _text(item.get("name"))
        if (model_id is None or name is None or not isinstance(family, str)
                or not _ID.fullmatch(family) or not isinstance(kind, str)
                or not _ID.fullmatch(kind)):
            continue
        result.append(ModelEntry(
            id=model_id, family=family, kind=kind, name=name,
            filename=_text(item.get("filename")),
            size_bytes=_whole(item.get("size_bytes")),
            variant=_text(item.get("variant"), 40),
            source=_text(item.get("source"), 20),
        ))
    return tuple(result)


@dataclass(frozen=True)
class ModelSummary:
    total: int
    counts: Mapping[str, Mapping[str, int]] = field(default_factory=dict)


def parse_model_summary(payload: Any) -> ModelSummary:
    data = _object(payload, "Model summary")
    total = _whole(data.get("total"))
    raw = data.get("counts")
    if total is None or not isinstance(raw, Mapping):
        raise BackendError("INVALID_RESPONSE", "Model summary is incomplete")
    counts: dict[str, dict[str, int]] = {}
    for family, kinds in raw.items():
        if not isinstance(family, str) or not _ID.fullmatch(family) or not isinstance(kinds, Mapping):
            continue
        counts[family] = {
            kind: count for kind, value in kinds.items()
            if isinstance(kind, str) and _ID.fullmatch(kind)
            and (count := _whole(value)) is not None
        }
    return ModelSummary(total=total, counts=counts)


# ----------------------------------------------------------------------------- generation defaults

@dataclass(frozen=True)
class FamilyDefaults:
    """Backend-validated generation limits and defaults for one family (or one variant of it)."""

    id: str
    label: str
    supported: bool
    steps_default: int | None = None
    steps_min: int | None = None
    steps_max: int | None = None
    guidance_label: str | None = None
    guidance_default: float | None = None
    guidance_min: float | None = None
    guidance_max: float | None = None
    width: int | None = None
    height: int | None = None
    sampler_default: str | None = None
    sampler_ids: tuple[str, ...] = ()
    negative_prompt: bool | None = None
    resolutions: tuple[tuple[str, int, int], ...] = ()
    variants: tuple[tuple[str, FamilyDefaults], ...] = ()

    def for_variant(self, variant: str | None) -> FamilyDefaults:
        """This family's limits with a variant's overrides (for example Flux Schnell)."""
        for name, item in self.variants:
            if name == variant:
                return item
        return self


def _capability(family_id: str, item: Mapping, base: FamilyDefaults | None = None) -> FamilyDefaults:
    """Parse one family or variant entry. A variant inherits what it does not state."""
    steps = item.get("steps") if isinstance(item.get("steps"), Mapping) else {}
    guidance = item.get("guidance") if isinstance(item.get("guidance"), Mapping) else {}
    resolution = (item.get("default_resolution")
                  if isinstance(item.get("default_resolution"), Mapping) else {})
    samplers = item.get("samplers") if isinstance(item.get("samplers"), Mapping) else {}
    options = samplers.get("options") if isinstance(samplers.get("options"), list) else []
    sampler_ids = tuple(
        text for option in options[:40]
        if isinstance(option, Mapping) and (text := _text(option.get("id"), 40))
    )
    presets = []
    for entry in (item.get("resolutions") if isinstance(item.get("resolutions"), list) else [])[:20]:
        if isinstance(entry, Mapping):
            w, h = _whole(entry.get("width"), 64), _whole(entry.get("height"), 64)
            label = _text(entry.get("label"), 40)
            if w and h and label and w <= 4096 and h <= 4096:
                presets.append((label, w, h))
    negative = item.get("negative_prompt")

    def pick(value, fallback):
        return value if value is not None else fallback

    b = base
    return FamilyDefaults(
        id=family_id,
        label=_text(item.get("label"), 60) or (b.label if b else family_id),
        supported=item.get("supported") is True if "supported" in item else (b.supported if b else False),
        steps_default=pick(_whole(steps.get("default"), 1), b.steps_default if b else None),
        steps_min=pick(_whole(steps.get("min"), 1), b.steps_min if b else None),
        steps_max=pick(_whole(steps.get("max"), 1), b.steps_max if b else None),
        guidance_label=pick(_text(guidance.get("label"), 30), b.guidance_label if b else None),
        guidance_default=pick(_number(guidance.get("default"), 0, 1000), b.guidance_default if b else None),
        guidance_min=pick(_number(guidance.get("min"), 0, 1000), b.guidance_min if b else None),
        guidance_max=pick(_number(guidance.get("max"), 0, 1000), b.guidance_max if b else None),
        width=pick(_whole(resolution.get("width"), 1), b.width if b else None),
        height=pick(_whole(resolution.get("height"), 1), b.height if b else None),
        sampler_default=pick(_text(samplers.get("default"), 40), b.sampler_default if b else None),
        sampler_ids=sampler_ids or (b.sampler_ids if b else ()),
        negative_prompt=negative if isinstance(negative, bool) else (b.negative_prompt if b else None),
        resolutions=tuple(presets) or (b.resolutions if b else ()),
    )


def parse_generation_defaults(payload: Any) -> dict[str, FamilyDefaults]:
    data = _object(payload, "Generation capabilities")
    families = data.get("families")
    if not isinstance(families, Mapping):
        raise BackendError("INVALID_RESPONSE", "Generation capabilities lack families")
    result: dict[str, FamilyDefaults] = {}
    for family_id, item in families.items():
        if not isinstance(family_id, str) or not _ID.fullmatch(family_id) or not isinstance(item, Mapping):
            continue
        parent = _capability(family_id, item)
        variants = []
        raw = item.get("variants")
        if isinstance(raw, Mapping):
            for name, entry in list(raw.items())[:10]:
                if isinstance(name, str) and _ID.fullmatch(name) and isinstance(entry, Mapping):
                    variants.append((name, _capability(family_id, entry, parent)))
        result[family_id] = replace(parent, variants=tuple(variants))
    return result
