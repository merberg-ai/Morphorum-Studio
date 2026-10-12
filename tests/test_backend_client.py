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
