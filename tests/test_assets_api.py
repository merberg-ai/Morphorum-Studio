"""Asset parsing, local file checks, uploads and verified downloads (no Qt, no network)."""
import hashlib
import json

import pytest
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.assets import (
    Asset, AssetsApi, check_offset, parse_assets, parse_soundtrack, read_local,
)
from morphorum_studio.backend.client import BackendClient, BackendError

DATA = b"RIFF\x00\x00\x00\x00WAVEdata" + b"x" * 100
SHA = hashlib.sha256(DATA).hexdigest()
ASSET = Asset("soundtrack", SHA, "song.wav", len(DATA), "audio/wav", SHA)
RECORD = {"soundtrack": {"sha256": SHA, "format": "wav", "filename": "song.wav",
                         "bytes": len(DATA), "offset_seconds": 1.5}}


def api(*responses):
    opener = FakeOpener(list(responses))
    return AssetsApi(BackendClient("http://localhost", "tok", opener=opener)), opener


def binary(data, sha=None):
    r = FakeResponse(data, content_type="audio/wav")
    if sha:
        r.headers["X-Content-SHA256"] = sha
    return r


def test_parse_assets_skips_bad_rows():
    out = parse_assets({"assets": [
        {"kind": "source_image", "id": "source-image", "filename": "source.png", "bytes": 5,
         "media_type": "image/png", "sha256": SHA},
        {"kind": "x", "bytes": 5, "sha256": "short"}, {"kind": "y", "bytes": 0, "sha256": SHA},
        "junk", {"kind": "z", "bytes": True, "sha256": SHA},
    ]})
    assert [a.kind for a in out] == ["source_image"]
    with pytest.raises(BackendError):
        parse_assets({"assets": 5})


def test_parse_soundtrack():
    s = parse_soundtrack(RECORD)
    assert s.offset_seconds == 1.5 and s.format == "wav" and s.size == len(DATA)
    assert parse_soundtrack({"soundtrack": None}) is None
    bad = parse_soundtrack({"soundtrack": {"sha256": SHA, "offset_seconds": float("nan")}})
    assert bad.offset_seconds == 0.0
    with pytest.raises(BackendError):
        parse_soundtrack({"soundtrack": {"sha256": "no"}})


def test_offset_limits():
    assert check_offset(-30) == -30.0
    for bad in (30.01, float("inf"), float("nan"), True, "1"):
        with pytest.raises(ValueError):
            check_offset(bad)


def test_read_local_checks(tmp_path):
    good = tmp_path / "a.wav"
    good.write_bytes(DATA)
    data, sha, name = read_local(good, (".wav",), 1000, "audio")
    assert data == DATA and sha == SHA and name == "a.wav"
    (tmp_path / "e.wav").write_bytes(b"")
    (tmp_path / "t.txt").write_bytes(b"x")
    for path, limit in ((tmp_path / "e.wav", 1000), (tmp_path / "t.txt", 1000),
                        (tmp_path / "missing.wav", 1000), (good, 10), (tmp_path, 1000)):
        with pytest.raises(ValueError):
            read_local(path, (".wav",), limit, "audio")


def test_upload_source_headers_and_body(tmp_path):
    img = tmp_path / "pic ü.png"
    img.write_bytes(b"\x89PNG" + b"1" * 50)
    a, opener = api(FakeResponse({"status": "uploaded"}))
    a.upload_source("demo", str(img))
    request = opener.requests[0][0]
    assert request.get_method() == "POST" and request.full_url.endswith("/projects/demo/source-image")
    assert request.data == img.read_bytes()
    assert request.get_header("Content-type") == "application/octet-stream"
    assert request.get_header("X-content-sha256") == hashlib.sha256(img.read_bytes()).hexdigest()
    assert request.get_header("X-filename") == "pic _.png"


def test_upload_error_detail_surfaces(tmp_path):
    from io import BytesIO
    from urllib.error import HTTPError
    img = tmp_path / "a.png"
    img.write_bytes(b"abc")
    err = HTTPError("http://x", 400, "bad", {}, BytesIO(b'{"detail":"Could not decode source image"}'))
    a, _ = api(err)
    with pytest.raises(BackendError) as exc:
        a.upload_source("demo", str(img))
    assert exc.value.code == "INVALID_REQUEST" and "Could not decode" in str(exc.value)


def test_attach_soundtrack_quotes_name_and_rereads(tmp_path):
    song = tmp_path / "my song & more.wav"
    song.write_bytes(DATA)
    a, opener = api(FakeResponse({"status": "attached"}), FakeResponse(RECORD))
    result = a.attach_soundtrack("demo", str(song), 2.0)
    first = opener.requests[0][0]
    assert first.get_header("X-audio-filename") == "my%20song%20%26%20more.wav"
    assert first.get_header("X-audio-offset-seconds") == "2.000"
    assert result.sha256 == SHA
    assert opener.requests[1][0].full_url.endswith("/motion-import/soundtrack")


def test_attach_soundtrack_rejects_before_network(tmp_path):
    song = tmp_path / "a.wav"
    song.write_bytes(DATA)
    a, opener = api()
    with pytest.raises(ValueError):
        a.attach_soundtrack("demo", str(song), 99)
    with pytest.raises(ValueError):
        a.attach_soundtrack("../x", str(song))
    assert opener.requests == []


def test_long_audio_name_stays_within_header_limit(tmp_path):
    song = tmp_path / (("é" * 100) + ".wav")
    song.write_bytes(DATA)
    a, opener = api(FakeResponse({}), FakeResponse(RECORD))
    a.attach_soundtrack("demo", str(song))
    assert len(opener.requests[0][0].get_header("X-audio-filename")) <= 300


def test_set_offset_and_clear_source():
    a, opener = api(FakeResponse({"soundtrack": {}}), FakeResponse(RECORD), FakeResponse({"status": "cleared"}))
    a.set_offset("demo", -4.25)
    put = opener.requests[0][0]
    assert put.get_method() == "PUT" and json.loads(put.data) == {"offset_seconds": -4.25}
    a.clear_source("demo")
    assert opener.requests[2][0].get_method() == "DELETE"


def test_save_copy_verifies_and_renames(tmp_path):
    a, opener = api(binary(DATA, SHA))
    dest = tmp_path / "copy.wav"
    assert a.save_copy("demo", ASSET, dest) == str(dest)
    assert dest.read_bytes() == DATA and not (tmp_path / "copy.wav.part").exists()
    assert opener.requests[0][0].full_url.endswith("/motion-import/soundtrack/file")


def test_save_copy_checksum_mismatch_leaves_nothing(tmp_path):
    a, _ = api(binary(DATA[:-1] + b"Z", SHA))
    dest = tmp_path / "copy.wav"
    with pytest.raises(BackendError) as exc:
        a.save_copy("demo", ASSET, dest)
    assert "checksum" in str(exc.value)
    assert list(tmp_path.iterdir()) == []


def test_save_copy_too_large_and_bad_destination(tmp_path):
    a, _ = api(binary(DATA + b"x" * (2 * 1024 * 1024)))
    with pytest.raises(BackendError):
        a.save_copy("demo", ASSET, tmp_path / "c.wav")
    assert list(tmp_path.iterdir()) == []
    a, opener = api()
    for dest in (tmp_path, tmp_path / "nofolder" / "c.wav"):
        with pytest.raises(ValueError):
            a.save_copy("demo", ASSET, dest)
    assert opener.requests == []


def test_save_copy_keeps_existing_file_on_failure(tmp_path):
    dest = tmp_path / "keep.wav"
    dest.write_bytes(b"original")
    a, _ = api(binary(b"corrupt"))
    with pytest.raises(BackendError):
        a.save_copy("demo", ASSET, dest)
    assert dest.read_bytes() == b"original"


def test_unsupported_asset_kind_and_preview_limits():
    a, _ = api()
    with pytest.raises(ValueError):
        a.save_copy("demo", Asset("motion_lab_wav", SHA, "x", 5, "audio/wav", SHA), "x")
    big = Asset("source_image", SHA, "s.png", 20 * 1024 * 1024, "image/png", SHA)
    assert a.preview_source("demo", big) is None


def test_preview_source_verified():
    img = b"\x89PNG" + b"q" * 30
    asset = Asset("source_image", hashlib.sha256(img).hexdigest(), "s.png", len(img), "image/png",
                  hashlib.sha256(img).hexdigest())
    a, _ = api(FakeResponse(img, content_type="image/png"))
    assert a.preview_source("demo", asset) == img
    a, _ = api(FakeResponse(img + b"!", content_type="image/png"))
    with pytest.raises(BackendError):
        a.preview_source("demo", asset)


def test_upload_header_whitelist():
    c = BackendClient("http://localhost", "t", opener=FakeOpener([]))
    for headers in ({"X-Evil": "1"}, {"X-Filename": "a\nb"}, {"X-Filename": "é"}):
        with pytest.raises(ValueError):
            c.upload_bytes("/api/x", b"data", headers)
    with pytest.raises(ValueError):
        c.upload_bytes("/api/x", b"", {})
