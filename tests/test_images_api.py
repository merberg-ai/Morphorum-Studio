"""Generation request validation, job parsing, the submission journal and the calls."""
import json
import os
import stat
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from fakes import CAPABILITIES
from test_backend_client import FakeOpener, FakeResponse

from morphorum_studio.backend.client import BackendClient, BackendError
from morphorum_studio.backend.images import (
    DEFINITIVE, GenerationSpec, ImagesApi, SubmissionJournal, eta_text, model_variant,
    parse_job, parse_jobs, validate_spec,
)
from morphorum_studio.backend.schema import parse_generation_defaults

PNG = b"\x89PNG\r\n\x1a\n" + b"data" * 10
SDXL = parse_generation_defaults(CAPABILITIES)["sdxl"]
JOB = {
    "id": "img-20261013-080000-abc123", "status": "generating", "message": "Generating",
    "progress": 0.25, "current_image": 1, "current_step": 10, "total_steps": 25, "eta_seconds": 75.4,
    "seeds": [5, 6], "error": None, "cancel_requested": False,
    "request": {"images": 2, "prompt": "a cat"}, "model": {"name": "Juggernaut XL"},
    "results": [{"index": 1, "seed": 5, "filename": "img-1.png", "path": "D:\\secret\\img-1.png",
                 "url": "/x"}],
}


def spec(**changes):
    base = dict(model_id="m", prompt="a cat", width=1024, height=1024, steps=25,
                guidance_scale=6.0, sampler="euler")
    base.update(changes)
    return GenerationSpec(**base)


def api(*responses):
    opener = FakeOpener(list(responses))
    return ImagesApi(BackendClient("http://localhost", "tok", opener=opener)), opener


# ----------------------------------------------------------------------------- spec

def test_payload_is_exact_and_trimmed():
    body = spec(prompt="  a cat ", negative_prompt=" bad ").payload()
    assert body == {"model_id": "m", "prompt": "a cat", "negative_prompt": "bad", "width": 1024,
                    "height": 1024, "steps": 25, "guidance_scale": 6.0, "sampler": "euler",
                    "seed": -1, "seed_mode": "fixed", "seed_increment": 1, "images": 1}
    assert spec(negative_prompt="bad").payload(negative_allowed=False)["negative_prompt"] == ""


@pytest.mark.parametrize("changes,fragment", [
    ({"model_id": ""}, "model"), ({"prompt": "  "}, "prompt"), ({"prompt": "x" * 4001}, "limited"),
    ({"width": 1020}, "multiple of 8"), ({"height": 32}, "Height"), ({"steps": 0}, "Steps"),
    ({"steps": 101}, "Steps"), ({"guidance_scale": 31.0}, "CFG"), ({"sampler": "nope"}, "sampler"),
    ({"images": 0}, "count"), ({"images": 33}, "count"), ({"seed": -5}, "Seed"),
    ({"seed": 2**32}, "Seed"), ({"seed_mode": "x"}, "seed mode"), ({"seed_increment": 10**7}, "increment"),
])
def test_validate_rejects(changes, fragment):
    problem = validate_spec(spec(**changes), SDXL, "sdxl")
    assert problem and fragment.lower() in problem.lower()


def test_validate_accepts_and_family_step():
    assert validate_spec(spec(seed=2**32 - 1), SDXL, "sdxl") is None
    assert "multiple of 16" in validate_spec(spec(width=1032), SDXL, "flux")


def test_variant_mirrors_backend():
    assert model_variant("Flux Schnell", "f.safetensors", None, "flux") == "schnell"
    assert model_variant("Flux", "dev.safetensors", None, "flux") == "dev"
    assert model_variant("Z", "z", "Turbo", "zimage") == "turbo"
    assert model_variant("X", "x", None, "sdxl") == "sdxl"


# ----------------------------------------------------------------------------- jobs

def test_parse_job_drops_paths_and_bad_files():
    job = parse_job({**JOB, "results": JOB["results"] + [{"filename": "../evil.png"}, {"filename": 3}]})
    assert job.active and not job.final and job.images == 2 and job.model_name == "Juggernaut XL"
    assert [r.filename for r in job.results] == ["img-1.png"] and job.results[0].seed == 5
    assert "secret" not in repr(job)
    assert job.progress == 0.25 and job.eta_seconds == 75.4


def test_parse_job_rejects_bad_ids_and_tolerates_missing_numbers():
    for bad in ({**JOB, "id": "../x"}, {**JOB, "status": None}, [], {}):
        with pytest.raises(BackendError):
            parse_job(bad)
    job = parse_job({"id": "j1", "status": "queued", "progress": "x", "eta_seconds": -3})
    assert job.progress == 0.0 and job.eta_seconds is None and job.images == 1


def test_parse_jobs_skips_bad():
    jobs = parse_jobs({"jobs": [JOB, {"id": "../no", "status": "x"}, "junk"]})
    assert len(jobs) == 1
    with pytest.raises(BackendError):
        parse_jobs({"jobs": "no"})


def test_eta_text():
    assert eta_text(parse_job(JOB)) == "image 2 of 2, step 10 of 25, about 1 min 15 s left"
    assert eta_text(parse_job({**JOB, "status": "queued"})) == "Waiting in the queue"
    assert eta_text(parse_job({**JOB, "status": "completed"})) == "Done, 1 image"
    assert eta_text(parse_job({**JOB, "status": "failed", "error": "out of memory"})) == "Failed: out of memory"
    assert eta_text(parse_job({**JOB, "status": "mystery_state"})) == "Mystery state"


# ----------------------------------------------------------------------------- journal

def test_journal_roundtrip_and_profile_filter(tmp_path):
    j = SubmissionJournal(tmp_path / "sub")
    a = j.begin("p1", spec().payload())
    b = j.begin("p2", spec(prompt="dog").payload())
    assert a.key != b.key and a.key.startswith("studio-")
    assert [e.key for e in j.entries("p1")] == [a.key] and len(j.entries()) == 2
    sub = j.submitted(a, "img-1")
    got = j.entries("p1")[0]
    assert got.state == "submitted" and got.job_id == "img-1" and got.payload == a.payload and sub.key == a.key
    j.finish(a.key)
    assert j.entries("p1") == []
    j.finish(a.key)  # idempotent


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_journal_files_are_private(tmp_path):
    j = SubmissionJournal(tmp_path)
    e = j.begin("p", {"a": 1})
    assert stat.S_IMODE((tmp_path / (e.key + ".json")).stat().st_mode) == 0o600


def test_journal_ignores_damaged_and_foreign_files(tmp_path):
    j = SubmissionJournal(tmp_path)
    good = j.begin("p", {"a": 1})
    (tmp_path / ("studio-" + "0" * 32 + ".json")).write_text("{broken")
    (tmp_path / ("studio-" + "1" * 32 + ".json")).write_text(json.dumps(
        {"key": "studio-" + "2" * 32, "profile": "p", "payload": {}, "state": "pending"}))  # name mismatch
    (tmp_path / ("studio-" + "3" * 32 + ".json")).write_text("x" * 70_000)
    (tmp_path / "notes.txt").write_text("hi")
    assert [e.key for e in j.entries("p")] == [good.key]


def test_journal_limits_and_bad_keys(tmp_path):
    j = SubmissionJournal(tmp_path)
    j.MAX_ENTRIES = 2
    j.begin("p", {})
    j.begin("p", {})
    with pytest.raises(ValueError):
        j.begin("p", {})
    with pytest.raises(ValueError):
        j.finish("../escape")


# ----------------------------------------------------------------------------- calls

def test_submit_sends_key_and_exact_body(tmp_path):
    j = SubmissionJournal(tmp_path)
    entry = j.begin("p", spec().payload())
    a, opener = api(FakeResponse(JOB))
    job = a.submit(entry)
    request = opener.requests[0][0]
    assert request.get_method() == "POST" and request.full_url.endswith("/api/generation/jobs")
    assert request.get_header("Idempotency-key") == entry.key
    assert json.loads(request.data) == entry.payload and job.id == JOB["id"]


def test_submit_refusal_is_definitive_and_carries_reason(tmp_path):
    entry = SubmissionJournal(tmp_path).begin("p", spec().payload())
    err = HTTPError("http://x", 400, "bad", {}, BytesIO(b'{"detail":"Prompt cannot be empty."}'))
    a, _ = api(err)
    with pytest.raises(BackendError) as exc:
        a.submit(entry)
    assert exc.value.code in DEFINITIVE and "Prompt cannot be empty" in str(exc.value)


def test_submit_network_failure_is_ambiguous(tmp_path):
    entry = SubmissionJournal(tmp_path).begin("p", spec().payload())
    a, opener = api(URLError("reset"), FakeResponse(JOB))
    with pytest.raises(BackendError) as exc:
        a.submit(entry)
    assert exc.value.code == "NETWORK_ERROR" and exc.value.code not in DEFINITIVE
    assert len(opener.requests) == 1  # no hidden retry


def test_job_cancel_recent_paths():
    a, opener = api(FakeResponse(JOB), FakeResponse({**JOB, "status": "cancelled"}), FakeResponse({"jobs": [JOB]}))
    assert a.job(JOB["id"]).id == JOB["id"]
    assert a.cancel(JOB["id"]).status == "cancelled"
    assert len(a.recent(5)) == 1
    urls = [r.full_url for r, _ in opener.requests]
    assert urls[1].endswith("/cancel") and urls[2].endswith("jobs?limit=5")
    with pytest.raises(ValueError):
        a.job("../x")


def test_image_bytes_requires_png():
    a, opener = api(FakeResponse(PNG, content_type="image/png"), FakeResponse(b"<html>", content_type="text/html"))
    assert a.image_bytes("j1", "img-1.png") == PNG
    assert opener.requests[0][0].full_url.endswith("/jobs/j1/images/img-1.png")
    with pytest.raises(BackendError):
        a.image_bytes("j1", "img-1.png")
    with pytest.raises(ValueError):
        a.image_bytes("j1", "a/b.png")


def test_save_copy_checks_png_and_cleans_up(tmp_path):
    a, _ = api(FakeResponse(PNG, content_type="image/png"))
    dest = tmp_path / "out.png"
    assert a.save_copy("j1", "img-1.png", dest) == str(dest) and dest.read_bytes() == PNG
    a, _ = api(FakeResponse(b"not a png at all", content_type="text/plain"))
    dest2 = tmp_path / "bad.png"
    with pytest.raises(BackendError):
        a.save_copy("j1", "img-1.png", dest2)
    assert not dest2.exists() and not (tmp_path / "bad.png.part").exists()
    with pytest.raises(ValueError):
        a.save_copy("j1", "img-1.png", tmp_path)


def test_idempotency_key_guard():
    c = BackendClient("http://localhost", "t", opener=FakeOpener([]))
    for kwargs in ({"idempotency_key": "short"}, {"idempotency_key": "has space here"}):
        with pytest.raises(ValueError):
            c.send_json("POST", "/api/x", {}, **kwargs)
    with pytest.raises(ValueError):
        c.send_json("PUT", "/api/x", {}, idempotency_key="studio-" + "a" * 32)


def test_family_variants_parse():
    caps = {"families": {"flux": {
        "supported": True, "label": "Flux", "steps": {"default": 28, "min": 1, "max": 50},
        "guidance": {"label": "CFG", "default": 1.0, "min": 0.0, "max": 10.0},
        "samplers": {"default": "flowmatch_euler", "options": [{"id": "flowmatch_euler"}]},
        "resolutions": [{"label": "Square", "width": 1024, "height": 1024}, {"label": "bad", "width": 0, "height": 5}],
        "variants": {"schnell": {"label": "Flux Schnell", "steps": {"default": 4, "min": 1, "max": 8},
                                 "guidance": {"default": 0.0, "min": 0.0, "max": 0.0}}}}}}
    flux = parse_generation_defaults(caps)["flux"]
    assert flux.resolutions == (("Square", 1024, 1024),) and flux.guidance_max == 10.0
    schnell = flux.for_variant("schnell")
    assert (schnell.steps_default, schnell.steps_max, schnell.guidance_max) == (4, 8, 0.0)
    assert schnell.sampler_ids == ("flowmatch_euler",) and schnell.label == "Flux Schnell"
    assert flux.for_variant("dev") is flux and flux.for_variant(None) is flux
