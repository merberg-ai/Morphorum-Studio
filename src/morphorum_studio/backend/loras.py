"""LoRA library and inspection (S4.4): read-only views of what the backend has indexed.

Server file-system paths are never kept. Inspection is by indexed model id only; Studio does not
ask the backend to look up Civitai or write usage records, so browsing changes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .api import ReadApi
from .client import BackendClient, BackendError
from .schema import ModelEntry, _object, _text, _whole

FAMILIES = ("sdxl", "flux", "zimage")
MAX_LIST = 12
MAX_WORDS = 40
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")  # the backend indexes by a hex digest


@dataclass(frozen=True)
class LoraDetail:
    id: str
    name: str
    family: str | None = None
    adapter_format: str | None = None
    tensor_count: int | None = None
    base_model: str | None = None
    trigger_words: tuple[str, ...] = ()
    trigger_source: str | None = None
    ranks: tuple[str, ...] = ()  # e.g. "16 x 480"
    components: tuple[tuple[str, int], ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _texts(value: Any, limit: int, width: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out = []
    for item in value[:limit]:
        text = _text(item, width)
        if text:
            out.append(text)
    return tuple(out)


def parse_lora_detail(model_id: str, payload: Any) -> LoraDetail:
    data = _object(payload, "LoRA detail")
    ranks = []
    raw_ranks = data.get("ranks")
    for item in (raw_ranks if isinstance(raw_ranks, list) else [])[:MAX_LIST]:
        if isinstance(item, Mapping):
            rank, modules = _whole(item.get("rank"), 0), _whole(item.get("modules"), 0)
            if rank is not None and modules is not None:
                ranks.append(f"{rank} × {modules}")
    components = []
    raw = data.get("components")
    if isinstance(raw, Mapping):
        for key in sorted(raw)[:MAX_LIST]:
            count = _whole(raw[key], 0)
            if count:
                components.append((_text(key, 40) or "?", count))
    return LoraDetail(
        id=model_id,
        name=_text(data.get("name"), 200) or model_id,
        family=_text(data.get("family"), 40),
        adapter_format=_text(data.get("adapter_format"), 60),
        tensor_count=_whole(data.get("tensor_count"), 0),
        base_model=_text(data.get("metadata_base_model"), 200),
        trigger_words=_texts(data.get("trigger_words"), MAX_WORDS, 120),
        trigger_source=_text(data.get("trigger_source"), 60),
        ranks=tuple(ranks),
        components=tuple(components),
        warnings=_texts(data.get("warnings"), MAX_LIST, 300),
        errors=_texts(data.get("errors"), MAX_LIST, 300),
    )


@dataclass(frozen=True)
class CivitaiMatch:
    found: bool
    message: str = ""
    confidence: str | None = None
    url: str | None = None
    model_name: str | None = None
    version_name: str | None = None
    creator: str | None = None
    base_model: str | None = None
    kind: str | None = None
    trained_words: tuple[str, ...] = ()
    description: str | None = None
    sha256: str | None = None


CIVITAI_PREFIX = "https://civitai.com/"


def parse_civitai(payload: Any) -> CivitaiMatch:
    data = _object(payload, "Civitai lookup")
    sha = _text(data.get("sha256"), 64)
    if data.get("found") is not True:
        return CivitaiMatch(False, message=_text(data.get("message"), 300)
                            or "No matching Civitai version was found.", sha256=sha)
    url = _text(data.get("url"), 300)
    return CivitaiMatch(
        True, confidence=_text(data.get("confidence"), 80),
        url=url if url and url.startswith(CIVITAI_PREFIX) else None,  # only ever link to Civitai
        model_name=_text(data.get("model_name"), 200), version_name=_text(data.get("version_name"), 200),
        creator=_text(data.get("creator"), 120), base_model=_text(data.get("base_model"), 200),
        kind=_text(data.get("type"), 100), trained_words=_texts(data.get("trained_words"), MAX_WORDS, 120),
        description=_text(data.get("description_text"), 2000), sha256=sha)


class LoraApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def library(self, family: str | None = None) -> tuple[ModelEntry, ...]:
        return ReadApi(self._client).models(family=family, kind="loras")

    def inspect(self, model_id: str) -> LoraDetail:
        if not isinstance(model_id, str) or MODEL_ID.fullmatch(model_id) is None:
            raise BackendError("INVALID_REQUEST", "Not a valid model id")
        payload = self._client.get_json(f"/api/loras/{model_id}/inspect")
        return parse_lora_detail(model_id, payload)

    def civitai(self, model_id: str) -> CivitaiMatch:
        """Explicit, opt-in lookup: the backend sends the file's SHA-256 (nothing else) to Civitai."""
        if not isinstance(model_id, str) or MODEL_ID.fullmatch(model_id) is None:
            raise BackendError("INVALID_REQUEST", "Not a valid model id")
        payload, _ = self._client.send_json("POST", f"/api/loras/{model_id}/civitai-lookup")
        return parse_civitai(payload)
