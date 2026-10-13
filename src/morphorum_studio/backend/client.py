"""S1.1 typed, dependency-free backend capability discovery transport.

No Qt imports: callers must run network operations off the UI thread.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, HTTPHandler, ProxyHandler, Request, build_opener,
)


class BackendError(Exception):
    """Safe, predictable discovery failure without leaking credentials."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class BackendDiscovery:
    base_url: str
    version: str
    mode: str
    instance_id: str
    boot_id: str
    features: dict[str, bool]
    health: dict[str, Any]
    capabilities: dict[str, Any]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_ERROR_CODES = {
    400: "INVALID_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    412: "PRECONDITION_FAILED",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def normalize_base_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackendError("INVALID_URL", "Backend URL is required")
    raw = value.strip()
    try:
        parts = urlsplit(raw)
        hostname = parts.hostname
        _ = parts.port  # Accessing the port validates it; ValueError if out of range.
    except ValueError as exc:
        raise BackendError("INVALID_URL", "Invalid backend URL or port") from exc
    if (parts.scheme not in ("http", "https") or not hostname or
            parts.username is not None or parts.password is not None or
            parts.query or parts.fragment or
            parts.path not in ("", "/") or any(c.isspace() for c in raw)):
        raise BackendError("INVALID_URL", "Use a root http(s) URL without credentials, path or query")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), "", "", ""))


# Fixed API paths only: /api/ followed by plain segments. Dot segments, percent-escapes,
# query strings and fragments are all rejected.
_API_PATH = re.compile(r"/api(?:/[A-Za-z0-9][A-Za-z0-9_.\-]*)+")


class BackendClient:
    """GET-only native discovery client. Does not follow redirects or retry.

    Requests ignore HTTP(S) proxy settings from the environment or the OS by default,
    so a bearer token is only ever sent to the backend host the profile names. Pass
    ``use_system_proxy=True`` to opt in for a backend that is only reachable via a proxy.
    """

    def __init__(self, base_url: str, token: str | None = None,
                 timeout: float = 8.0, opener: Any = None, use_system_proxy: bool = False):
        self.base_url = normalize_base_url(base_url)
        if not 0 < timeout <= 60:
            raise ValueError("timeout must be in (0, 60] seconds")
        if token is not None and (not token.strip() or "\r" in token or "\n" in token):
            raise ValueError("invalid bearer token")
        self._token = token
        self.timeout = timeout
        self._opener = opener if opener is not None else build_opener(
            ProxyHandler(None if use_system_proxy else {}),
            _NoRedirect, HTTPHandler, HTTPSHandler,
        )

    def get_json(self, path: str) -> dict[str, Any]:
        if not _API_PATH.fullmatch(path):
            raise ValueError("only fixed backend API paths are allowed")
        headers = {"Accept": "application/json", "User-Agent": "Morphorum-Studio/0.1"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        request = Request(self.base_url + path, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = response.status
                if not 200 <= status < 300:
                    raise BackendError(_ERROR_CODES.get(status, "HTTP_ERROR"),
                                       f"Backend returned HTTP {status}", status)
                if response.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    raise BackendError("INVALID_RESPONSE", "Expected JSON response")
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise BackendError("INVALID_RESPONSE", "Discovery response too large")
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                raise BackendError("REDIRECT_REJECTED", "Backend redirected a discovery request", exc.code) from exc
            raise BackendError(_ERROR_CODES.get(exc.code, "HTTP_ERROR"),
                               f"Backend returned HTTP {exc.code}", exc.code) from exc
        except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            raise BackendError("NETWORK_ERROR", "Unable to reach backend") from exc
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BackendError("INVALID_RESPONSE", "Backend returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise BackendError("INVALID_RESPONSE", "Expected JSON object")
        return payload

    def discover(self) -> BackendDiscovery:
        health = self.get_json("/api/health")
        capabilities = self.get_json("/api/client/capabilities")
        if (type(health.get("api_contract_version")) is not int or
                health["api_contract_version"] != 1 or
                type(capabilities.get("api_contract_version")) is not int or
                capabilities["api_contract_version"] != 1 or
                type(capabilities.get("schema_version")) is not int or
                capabilities["schema_version"] != 1 or
                type(capabilities.get("client_protocol_version")) is not int or
                capabilities["client_protocol_version"] != 1):
            raise BackendError("INCOMPATIBLE_API", "Unsupported backend API or discovery schema")
        mode = capabilities.get("mode")
        instance_id = capabilities.get("instance_id")
        boot_id = capabilities.get("boot_id")
        features = capabilities.get("features")
        if (mode not in ("standard", "backend-only") or
                not isinstance(instance_id, str) or not re.fullmatch(r"[0-9a-f]{32}", instance_id) or
                not isinstance(boot_id, str) or not re.fullmatch(r"[0-9a-f]{32}", boot_id) or
                not isinstance(features, dict) or
                any(not isinstance(k, str) or type(v) is not bool for k, v in features.items()) or
                not isinstance(health.get("version"), str)):
            raise BackendError("INVALID_RESPONSE", "Invalid backend discovery fields")
        if health.get("mode") != mode:
            raise BackendError("INVALID_RESPONSE", "Health and capabilities disagree on mode")
        return BackendDiscovery(
            self.base_url, health["version"], mode, instance_id, boot_id,
            features, health, capabilities
        )
