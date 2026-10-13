"""Backend console (live log) client: snapshot, server-sent events, bounded history.

No Qt. The backend keeps a ring of 1500 entries with increasing ids and a ``boot_id``; a stream
resumes from ``after_id`` and says so explicitly when the history was cut (``console_gap``) or the
backend restarted (``console_reset``). Studio never invents entries: a gap is shown as a gap.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from .client import BackendClient, BackendError
from .schema import _object, _text, _whole

LEVELS = ("debug", "info", "warning", "error", "critical")
_LEVEL_ALIASES = {"warn": "warning", "fatal": "critical", "err": "error"}
_CATEGORY = re.compile(r"[a-z0-9_.\-]{1,32}")
_BOOT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}")
MAX_MESSAGE = 4000
MAX_DATA = 16_384


@dataclass(frozen=True)
class ConsoleEntry:
    id: int
    timestamp: str
    level: str
    category: str
    message: str


def parse_entry(payload: Any) -> ConsoleEntry:
    data = _object(payload, "Console entry")
    entry_id = _whole(data.get("id"), 0)
    if entry_id is None:
        raise BackendError("INVALID_RESPONSE", "Console entry has no id")
    level = (_text(data.get("level"), 16) or "info").lower()
    level = _LEVEL_ALIASES.get(level, level)
    category = (_text(data.get("category"), 32) or "runtime").lower()
    message = data.get("message")
    return ConsoleEntry(
        id=entry_id, timestamp=_text(data.get("timestamp"), 40) or "",
        level=level if level in LEVELS else "info",
        category=category if _CATEGORY.fullmatch(category) else "runtime",
        message=(message if isinstance(message, str) else "")[:MAX_MESSAGE])


def parse_snapshot(payload: Any) -> tuple[tuple[ConsoleEntry, ...], str | None]:
    data = _object(payload, "Console")
    items = data.get("events")
    if not isinstance(items, list):
        raise BackendError("INVALID_RESPONSE", "Console response lacks events")
    entries = []
    for item in items[:2000]:
        try:
            entries.append(parse_entry(item))
        except BackendError:
            continue
    boot = data.get("boot_id")
    return tuple(entries), boot if isinstance(boot, str) and _BOOT.fullmatch(boot) else None


def iter_sse(lines: Iterator[str]) -> Iterator[tuple[str, str]]:
    """Group SSE lines into (event name, data) pairs; comments (heartbeats) are skipped."""
    event, data = "message", []
    size = 0
    for line in lines:
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data, size = "message", [], 0
        elif line.startswith(":"):
            continue
        else:
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "event":
                event = value[:40]
            elif name == "data":
                size += len(value)
                if size <= MAX_DATA:
                    data.append(value)


@dataclass(frozen=True)
class Gap:
    first_available: int | None


@dataclass(frozen=True)
class Reset:
    """The backend restarted (or its numbering went backwards): drop the old cursor."""


class ConsoleApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def snapshot(self, after_id: int = 0, limit: int = 500) -> tuple[tuple[ConsoleEntry, ...], str | None]:
        return parse_snapshot(self._client.get_json(
            "/api/console", {"after_id": max(0, after_id), "limit": max(1, min(limit, 1500))}))

    def stream(self, after_id: int, boot_id: str | None,
               stop: Callable[[], bool]) -> Iterator[ConsoleEntry | Gap | Reset]:
        """Entries, gaps and resets until the stream ends, errors (BackendError) or ``stop()``."""
        params: dict[str, str | int | None] = {"after_id": max(0, after_id)}
        if boot_id and _BOOT.fullmatch(boot_id):
            params["boot_id"] = boot_id
        for name, raw in iter_sse(self._client.stream_lines("/api/console/stream", params, stop=stop)):
            if stop():
                return
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if name == "console":
                try:
                    yield parse_entry(data)
                except BackendError:
                    continue
            elif name == "console_gap":
                first = _whole(data.get("first_available"), 0) if isinstance(data, dict) else None
                yield Gap(first)
            elif name == "console_reset":
                yield Reset()
            if stop():
                return
