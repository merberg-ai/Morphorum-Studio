"""Pure mocked S1.1 discovery tests: never connect to a real server."""
from email.message import Message
from io import BytesIO
import json

import pytest

from morphorum_studio.backend.client import BackendClient, BackendError, normalize_base_url


class FakeResponse:
    def __init__(self, payload, status=200, content_type="application/json"):
        self.data = BytesIO(json.dumps(payload).encode() if not isinstance(payload, bytes) else payload)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, n):
        return self.data.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeOpener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


HEALTH = {"api_contract_version": 1, "version": "0.1.0a1", "mode": "backend-only"}
CAPS = {
    "api_contract_version": 1, "schema_version": 1, "client_protocol_version": 1,
    "mode": "backend-only", "instance_id": "a" * 32, "boot_id": "b" * 32,
    "features": {"video_export": False, "job_events": True}
}


def test_discovery_authorization_and_identity():
    opener = FakeOpener([FakeResponse(HEALTH), FakeResponse(CAPS)])
    info = BackendClient("http://localhost:7866/", "test-secret", opener=opener).discover()
    assert info.instance_id == "a" * 32
    assert info.features["video_export"] is False
    assert [r.full_url for r, _ in opener.requests] == [
        "http://localhost:7866/api/health",
        "http://localhost:7866/api/client/capabilities"
    ]
    assert all(r.get_header("Authorization") == "Bearer test-secret" for r, _ in opener.requests)
    assert all(r.get_header("Origin") is None for r, _ in opener.requests)


@pytest.mark.parametrize("url", [
    "", "ftp://example.com", "http://user:pass@example.com",
    "https://example.com/api", "http://example.com/?token=secret",
    "http://example.com/#x", "http://example.com:99999", "http://example.com bad",
])
def test_invalid_urls(url):
    with pytest.raises(BackendError) as exc:
        normalize_base_url(url)
    assert exc.value.code == "INVALID_URL"


@pytest.mark.parametrize("status,expected", [
    (401, "AUTH_REQUIRED"), (403, "FORBIDDEN"), (409, "CONFLICT"),
    (412, "PRECONDITION_FAILED"), (302, "REDIRECT_REJECTED"),
])
def test_http_errors(status, expected):
    from urllib.error import HTTPError
    opener = FakeOpener([HTTPError("http://localhost/api/health", status, "fail", {}, None)])
    with pytest.raises(BackendError) as exc:
        BackendClient("http://localhost", opener=opener).discover()
    assert exc.value.code == expected


def test_timeout_and_network_failure():
    from urllib.error import URLError
    for error in (TimeoutError(), URLError("down")):
        with pytest.raises(BackendError) as exc:
            BackendClient("http://localhost", opener=FakeOpener([error])).discover()
        assert exc.value.code == "NETWORK_ERROR"


def test_malformed_response():
    for bad in (b"{broken", b"[]"):
        with pytest.raises(BackendError) as exc:
            BackendClient("http://localhost", opener=FakeOpener([FakeResponse(bad)])).discover()
        assert exc.value.code == "INVALID_RESPONSE"


def test_mismatched_contract_and_invalid_fields():
    cases = [
        ({**HEALTH, "api_contract_version": 2}, CAPS, "INCOMPATIBLE_API"),
        (HEALTH, {**CAPS, "api_contract_version": 2}, "INCOMPATIBLE_API"),
        (HEALTH, {**CAPS, "schema_version": 2}, "INCOMPATIBLE_API"),
        (HEALTH, {**CAPS, "instance_id": "wrong"}, "INVALID_RESPONSE"),
        (HEALTH, {**CAPS, "features": {"yes": 1}}, "INVALID_RESPONSE"),
        (HEALTH, {**CAPS, "mode": "standard"}, "INVALID_RESPONSE"),
    ]
    for health, caps, code in cases:
        opener = FakeOpener([FakeResponse(health), FakeResponse(caps)])
        with pytest.raises(BackendError) as exc:
            BackendClient("https://example.com", opener=opener).discover()
        assert exc.value.code == code


def test_invalid_content_type_and_oversized_payload():
    for response in (
        FakeResponse(HEALTH, content_type="text/html"),
        FakeResponse(b'{"pad":"' + b'a' * 1_048_580 + b'"}'),
    ):
        with pytest.raises(BackendError) as exc:
            BackendClient("http://localhost", opener=FakeOpener([response])).discover()
        assert exc.value.code == "INVALID_RESPONSE"


def test_default_opener_ignores_system_proxies(monkeypatch):
    from urllib.request import ProxyHandler
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    client = BackendClient("http://192.0.2.10:7866", "token")
    handlers = [h for h in client._opener.handlers if isinstance(h, ProxyHandler)]
    # An empty ProxyHandler registers nothing, so no proxy handler is active at all.
    assert not [h for h in handlers if h.proxies]
    opted_in = BackendClient("http://192.0.2.10:7866", "token", use_system_proxy=True)
    handler = next(h for h in opted_in._opener.handlers if isinstance(h, ProxyHandler))
    assert handler.proxies.get("http") == "http://127.0.0.1:9"


def test_bearer_token_never_reaches_an_environment_proxy(monkeypatch):
    """Regression: a configured proxy used to receive the Authorization header."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Spy(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Spy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{server.server_address[1]}")
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("NO_PROXY", raising=False)
        with pytest.raises(BackendError):
            # 192.0.2.0/24 is reserved for documentation and is never routable.
            BackendClient("http://192.0.2.10:7866", "SECRET-TEST-TOKEN", timeout=1).get_json("/api/health")
    finally:
        server.shutdown()
        server.server_close()
    assert seen == []


@pytest.mark.parametrize("path", [
    "/api/../admin", "/api/%2e%2e/x", "/api/./x", "/api/health?x=1", "/api/a#b",
    "/api//x", "/api", "/api/", "/other/api/x", "api/health", "/api/ok/", "/api/a b",
])
def test_get_json_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        BackendClient("http://localhost", opener=FakeOpener([])).get_json(path)


@pytest.mark.parametrize("path", [
    "/api/health", "/api/system/gpu-memory", "/api/models/families", "/api/client/capabilities",
])
def test_get_json_accepts_plain_api_paths(path):
    opener = FakeOpener([FakeResponse({"ok": True})])
    assert BackendClient("http://localhost", opener=opener).get_json(path) == {"ok": True}
