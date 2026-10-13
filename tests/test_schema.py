"""Typed parsing of backend system/model responses (pure; no Qt, no network)."""

import copy

import pytest
from fakes import CAPABILITIES, FAMILIES, GPU_MEMORY, MODELS, SUMMARY, TELEMETRY

from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.schema import (
    parse_families,
    parse_generation_defaults,
    parse_gpu_memory,
    parse_model_summary,
    parse_models,
    parse_telemetry,
)


def test_telemetry_reads_real_backend_shape():
    t = parse_telemetry(TELEMETRY)
    assert t.cpu_percent == 12.5
    assert t.ram.total_bytes == 32 * 1024**3 and t.ram.used_percent == 37.5
    assert t.gpu_backend == "nvidia"
    gpu = t.gpus[0]
    assert gpu.name == "NVIDIA GeForce RTX 4080" and gpu.temperature_c == 64.0
    assert gpu.memory_used_fraction == 0.5


def test_telemetry_without_a_gpu_has_no_devices_and_no_invented_values():
    t = parse_telemetry({"cpu_percent": 3.0, "gpu": {"backend": None, "devices": []}})
    assert t.gpus == () and t.gpu_backend is None
    assert t.ram is None  # not reported, so unknown rather than zero


def test_missing_fields_become_none_not_zero():
    t = parse_telemetry({"gpu": {"devices": [{"index": 0, "name": "GPU"}]}})
    assert t.cpu_percent is None
    gpu = t.gpus[0]
    assert gpu.utilization_percent is None and gpu.memory_total_mib is None
    assert gpu.memory_used_fraction is None and gpu.temperature_c is None


@pytest.mark.parametrize("bad", [True, "50", float("nan"), float("inf"), -1, 101, None, [], {}])
def test_wrong_or_out_of_range_numbers_are_treated_as_unknown(bad):
    payload = copy.deepcopy(TELEMETRY)
    payload["cpu_percent"] = bad
    payload["gpu"]["devices"][0]["utilization_percent"] = bad
    t = parse_telemetry(payload)
    assert t.cpu_percent is None
    assert t.gpus[0].utilization_percent is None


def test_inconsistent_memory_is_unknown_rather_than_impossible():
    payload = copy.deepcopy(TELEMETRY)
    payload["gpu"]["devices"][0]["memory_used_mib"] = 99999.0  # more than total
    payload["ram"]["used_bytes"] = 64 * 1024**3  # more than total
    t = parse_telemetry(payload)
    assert t.gpus[0].memory_used_mib is None and t.gpus[0].memory_used_fraction is None
    assert t.ram.used_bytes is None


def test_malformed_devices_are_skipped_and_names_are_cleaned():
    payload = {"gpu": {"backend": "nvidia", "devices": [
        "junk", {"index": "0", "name": "x"}, {"index": 1, "name": ""},
        {"index": 2, "name": "RTX\x1b[31m 4080\n"},
    ]}}
    t = parse_telemetry(payload)
    assert [g.index for g in t.gpus] == [2]
    assert "\x1b" not in t.gpus[0].name and "\n" not in t.gpus[0].name


@pytest.mark.parametrize("parser", [
    parse_telemetry, parse_families, parse_models, parse_model_summary,
    parse_gpu_memory, parse_generation_defaults,
])
@pytest.mark.parametrize("payload", [None, [], "text", 5])
def test_non_object_responses_are_rejected(parser, payload):
    with pytest.raises(BackendError) as caught:
        parser(payload)
    assert caught.value.code == "INVALID_RESPONSE"


def test_families():
    families = parse_families(FAMILIES)
    assert [(f.id, f.label, f.supports_loras, f.source) for f in families] == [
        ("sdxl", "SDXL", True, "external"), ("zimage", "Z-Image", True, "managed")]
    with pytest.raises(BackendError):
        parse_families({"families": "nope"})
    assert parse_families({"families": [{"id": "../x"}, {"id": "ok", "label": "Ok"}, 5]})[0].id == "ok"


def test_models_drop_server_paths_and_skip_bad_rows():
    models = parse_models(MODELS)
    assert [m.name for m in models] == ["Juggernaut XL", "Ink Style", "Z-Image Turbo"]
    assert not any(hasattr(m, "path") for m in models)
    assert models[2].variant == "turbo" and models[0].size_bytes == 6_938_000_000
    messy = {"models": [{"id": "1", "family": "sdxl", "kind": "loras", "name": "ok", "size_bytes": "big"},
                        {"id": "2", "family": "bad family", "kind": "loras", "name": "x"}, 7]}
    parsed = parse_models(messy)
    assert len(parsed) == 1 and parsed[0].size_bytes is None
    with pytest.raises(BackendError):
        parse_models({"models": None})


def test_model_summary():
    summary = parse_model_summary(SUMMARY)
    assert summary.total == 3 and summary.counts["sdxl"] == {"checkpoints": 1, "loras": 1}
    with pytest.raises(BackendError):
        parse_model_summary({"total": 3})
    with pytest.raises(BackendError):
        parse_model_summary({"total": True, "counts": {}})


def test_gpu_memory():
    memory = parse_gpu_memory(GPU_MEMORY)
    assert memory.cuda_available and memory.total_gib == 16.0 and memory.model_name == "Juggernaut XL"
    none = parse_gpu_memory({"cuda_available": False, "cuda": None, "model": {"loaded": False}})
    assert not none.cuda_available and none.total_gib is None and not none.model_loaded
    with pytest.raises(BackendError):
        parse_gpu_memory({"cuda": {}})


def test_generation_defaults():
    defaults = parse_generation_defaults(CAPABILITIES)["sdxl"]
    assert (defaults.steps_default, defaults.guidance_label, defaults.guidance_default) == (25, "CFG", 6.0)
    assert (defaults.width, defaults.height, defaults.sampler_default) == (1024, 1024, "euler")
    assert defaults.sampler_ids == ("euler",) and defaults.supported
