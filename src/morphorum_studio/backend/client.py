"""S1.1 typed, dependency-free backend capability discovery transport.

No Qt imports: callers must run network operations off the UI thread.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from collections.abc import Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit
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


_QUERY_KEY = re.compile(r"[a-z][a-z_]{0,23}")
_QUERY_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\- ]{0,63}")


def _encode_query(params: Mapping[str, str | int | None] | None) -> str:
    """Build a safe query string from simple, validated parameters.

    Keys are short lowercase names; values are small integers or short plain strings.
    ``None`` values are omitted. The bearer token is never part of a URL.
    """
    if not params:
        return ""
    pairs = []
    for key, value in params.items():
        if value is None:
            continue
        if not isinstance(key, str) or not _QUERY_KEY.fullmatch(key):
            raise ValueError("invalid query parameter name")
        if isinstance(value, bool):
            raise ValueError("invalid query parameter value")
        if isinstance(value, int):
            if not 0 <= value <= 100_000:
                raise ValueError("query integer out of range")
            text = str(value)
        elif isinstance(value, str) and _QUERY_VALUE.fullmatch(value):
            text = value
        else:
            raise ValueError("invalid query parameter value")
        pairs.append((key, text))
    return "?" + urlencode(pairs) if pairs else ""


_ETAG = re.compile(r'"[0-9a-f]{64}"')
MAX_REQUEST_BYTES = 262_144
_IDEMPOTENCY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}")
MAX_UPLOAD_BYTES = 48 * 1024 * 1024
_UPLOAD_HEADERS = frozenset({"X-Content-SHA256", "X-Filename", "X-Audio-Filename",
                             "X-Audio-Offset-Seconds"})


def _error_detail(exc: HTTPError) -> str:
    """The backend's short FastAPI ``detail`` string, if any. Control characters are removed."""
    try:
        body = json.loads(exc.read(4097))
    except Exception:
        return ""
    detail = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", " ", detail).strip()[:200]


class BackendClient:
    """Native client for the backend API. Does not follow redirects or retry.

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

    def get_json(self, path: str,
                 params: Mapping[str, str | int | None] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params)[0]

    def get_json_etag(self, path: str,
                      params: Mapping[str, str | int | None] | None = None
                      ) -> tuple[dict[str, Any], str | None]:
        """Like ``get_json`` but also returns the strong ETag header when the backend sends one."""
        return self._request("GET", path, params)

    def send_json(self, method: str, path: str, body: Mapping[str, Any] | None = None, *,
                  if_match: str | None = None, idempotency_key: str | None = None) -> tuple[dict[str, Any], str | None]:
        """One explicit state-changing call (POST, PUT or DELETE). Never retried.

        ``if_match`` (PUT only) must be a quoted 64-hex ETag from an earlier read. Error messages
        include the backend's short ``detail`` text so the user learns why a change was refused.
        """
        if method not in ("POST", "PUT", "DELETE"):
            raise ValueError("unsupported method")
        if if_match is not None and (method != "PUT" or not _ETAG.fullmatch(if_match)):
            raise ValueError("If-Match must be one quoted ETag on a PUT")
        if body is not None and method == "DELETE":
            raise ValueError("DELETE takes no body")
        if idempotency_key is not None and (method != "POST" or not _IDEMPOTENCY.fullmatch(idempotency_key)):
            raise ValueError("Idempotency-Key must be 8-128 safe characters on a POST")
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(data) > MAX_REQUEST_BYTES:
                raise ValueError("request body too large")
        extra = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._request(method, path, None, data, if_match, include_detail=True,
                             extra_headers=extra)

    def upload_bytes(self, path: str, data: bytes, headers: Mapping[str, str]) -> dict[str, Any]:
        """One raw-body POST (source image or soundtrack). Never retried.

        Only the backend's documented upload headers are allowed and their values must be plain
        printable ASCII; the caller supplies the SHA-256 so the backend can verify the transfer.
        """
        if not data or len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("upload must be between 1 byte and 48 MiB")
        clean: dict[str, str] = {}
        for name, value in headers.items():
            if name not in _UPLOAD_HEADERS or not isinstance(value, str) \
                    or not re.fullmatch(r"[\x20-\x7e]{1,300}", value):
                raise ValueError("upload header not allowed")
            clean[name] = value
        return self._request("POST", path, None, data, None, include_detail=True,
                             content_type="application/octet-stream", extra_headers=clean)[0]

    def download(self, path: str, sink, max_bytes: int) -> tuple[int, str, str | None]:
        """Stream a binary response into ``sink(chunk)``; returns (size, sha256, advertised sha256).

        Refuses redirects and anything over ``max_bytes``. The caller decides what to do with a
        digest mismatch, and removes whatever ``sink`` wrote when this raises.
        """
        if not _API_PATH.fullmatch(path):
            raise ValueError("only fixed backend API paths are allowed")
        headers = {"User-Agent": "Morphorum-Studio/0.1"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        request = Request(self.base_url + path, headers=headers, method="GET")
        digest = hashlib.sha256()
        total = 0
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if not 200 <= response.status < 300:
                    raise BackendError(_ERROR_CODES.get(response.status, "HTTP_ERROR"),
                                       f"Backend returned HTTP {response.status}", response.status)
                advertised = response.headers.get("X-Content-SHA256")
                if advertised is not None and not re.fullmatch(r"[0-9a-f]{64}", advertised):
                    advertised = None
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise BackendError("INVALID_RESPONSE", "Download is larger than expected")
                    digest.update(chunk)
                    sink(chunk)
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                raise BackendError("REDIRECT_REJECTED", "Backend redirected a download", exc.code) from exc
            detail = _error_detail(exc)
            raise BackendError(_ERROR_CODES.get(exc.code, "HTTP_ERROR"),
                               f"Backend returned HTTP {exc.code}" + (f": {detail}" if detail else ""),
                               exc.code) from exc
        except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            raise BackendError("NETWORK_ERROR", "Unable to reach backend") from exc
        return total, digest.hexdigest(), advertised

    def _request(self, method: str, path: str,
                 params: Mapping[str, str | int | None] | None = None,
                 data: bytes | None = None, if_match: str | None = None,
                 include_detail: bool = False, content_type: str = "application/json",
                 extra_headers: Mapping[str, str] | None = None
                 ) -> tuple[dict[str, Any], str | None]:
        if not _API_PATH.fullmatch(path):
            raise ValueError("only fixed backend API paths are allowed")
        query = _encode_query(params)
        headers = {"Accept": "application/json", "User-Agent": "Morphorum-Studio/0.1"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        if data is not None:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        if if_match is not None:
            headers["If-Match"] = if_match
        request = Request(self.base_url + path + query, data=data, headers=headers, method=method)
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
                etag = response.headers.get("ETag")
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                raise BackendError("REDIRECT_REJECTED", "Backend redirected a discovery request", exc.code) from exc
            message = f"Backend returned HTTP {exc.code}"
            if include_detail:
                detail = _error_detail(exc)
                if detail:
                    message += f": {detail}"
            raise BackendError(_ERROR_CODES.get(exc.code, "HTTP_ERROR"), message, exc.code) from exc
        except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            raise BackendError("NETWORK_ERROR", "Unable to reach backend") from exc
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BackendError("INVALID_RESPONSE", "Backend returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise BackendError("INVALID_RESPONSE", "Expected JSON object")
        if etag is not None and not _ETAG.fullmatch(etag):
            etag = None  # Weak or malformed validators are not usable for If-Match.
        return payload, etag

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
