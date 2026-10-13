"""Typed, read-only backend calls used by the dashboard (S2.1).

Every method is one authenticated GET with bounded size and timeout, performed by the
``BackendClient`` it wraps. Run these off the UI thread (see ``worker.ApiWorker``).
Nothing here changes backend state.
"""

from __future__ import annotations

import re

from .client import BackendClient
from .schema import (
    FamilyDefaults,
    GpuMemory,
    ModelEntry,
    ModelFamily,
    ModelSummary,
    Telemetry,
    parse_families,
    parse_generation_defaults,
    parse_gpu_memory,
    parse_model_summary,
    parse_models,
    parse_telemetry,
)

_FILTER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}")
MODEL_LIMIT = 1000


class ReadApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def telemetry(self) -> Telemetry:
        return parse_telemetry(self._client.get_json("/api/system/telemetry"))

    def gpu_memory(self) -> GpuMemory:
        """Backend-side CUDA allocator state. On Windows hosts the backend samples performance
        counters for this call, so it is meant for on-demand use, not for a polling loop."""
        return parse_gpu_memory(self._client.get_json("/api/system/gpu-memory"))

    def model_families(self) -> tuple[ModelFamily, ...]:
        return parse_families(self._client.get_json("/api/models/families"))

    def model_summary(self) -> ModelSummary:
        return parse_model_summary(self._client.get_json("/api/models/summary"))

    def models(self, family: str | None = None, kind: str | None = None,
               limit: int = MODEL_LIMIT) -> tuple[ModelEntry, ...]:
        for value in (family, kind):
            if value is not None and not _FILTER.fullmatch(value):
                raise ValueError("invalid model filter")
        payload = self._client.get_json(
            "/api/models", {"family": family, "kind": kind, "limit": limit}
        )
        return parse_models(payload)

    def generation_defaults(self) -> dict[str, FamilyDefaults]:
        return parse_generation_defaults(self._client.get_json("/api/generation/capabilities"))
