"""Shared fakes for dashboard tests: canned backend payloads and a scriptable client."""

from morphorum_studio.backend.client import BackendError

TELEMETRY = {
    "cpu_percent": 12.5,
    "ram": {
        "total_bytes": 32 * 1024**3, "available_bytes": 20 * 1024**3,
        "used_bytes": 12 * 1024**3, "used_percent": 37.5, "free_percent": 62.5,
    },
    "gpu": {"backend": "nvidia", "devices": [{
        "index": 0, "name": "NVIDIA GeForce RTX 4080", "utilization_percent": 71.0,
        "memory_total_mib": 16384.0, "memory_used_mib": 8192.0, "memory_free_mib": 8192.0,
        "memory_free_percent": 50.0, "temperature_c": 64.0,
    }]},
}
FAMILIES = {"families": [
    {"id": "sdxl", "label": "SDXL", "supports_loras": True, "source": "external", "lora_source": "external"},
    {"id": "zimage", "label": "Z-Image", "supports_loras": True, "source": "managed", "lora_source": "external"},
]}
MODELS = {"models": [
    {"id": "sdxl-aaa", "family": "sdxl", "kind": "checkpoints", "name": "Juggernaut XL",
     "filename": "jugg.safetensors", "path": "D:\\models\\jugg.safetensors",
     "size_bytes": 6_938_000_000, "mtime_ns": 1, "extension": ".safetensors", "variant": None,
     "source": "external", "preview_path": None, "indexed_at": "2026-10-01T00:00:00Z"},
    {"id": "sdxl-bbb", "family": "sdxl", "kind": "loras", "name": "Ink Style",
     "filename": "ink.safetensors", "path": "D:\\loras\\ink.safetensors", "size_bytes": 150_000_000,
     "mtime_ns": 1, "extension": ".safetensors", "variant": None, "source": "external",
     "preview_path": None, "indexed_at": "2026-10-01T00:00:00Z"},
    {"id": "zimage-ccc", "family": "zimage", "kind": "checkpoints", "name": "Z-Image Turbo",
     "filename": "zimage", "path": "D:\\ckpts\\z-image", "size_bytes": 12_000_000_000, "mtime_ns": 1,
     "extension": "", "variant": "turbo", "source": "managed", "preview_path": None,
     "indexed_at": "2026-10-01T00:00:00Z"},
]}
SUMMARY = {"total": 3, "counts": {"sdxl": {"checkpoints": 1, "loras": 1}, "zimage": {"checkpoints": 1}}}
CAPABILITIES = {"families": {
    "sdxl": {"supported": True, "label": "SDXL", "steps": {"default": 25, "min": 1, "max": 100},
             "guidance": {"key": "cfg_scale", "label": "CFG", "default": 6.0, "min": 1.0, "max": 30.0},
             "negative_prompt": True, "default_resolution": {"width": 1024, "height": 1024},
             "samplers": {"default": "euler", "options": [{"id": "euler", "label": "Euler"}]}},
}}
GPU_MEMORY = {
    "schema_version": 1, "cuda_available": True,
    "cuda": {"device_index": 0, "device_name": "NVIDIA GeForce RTX 4080", "total_gib": 16.0,
             "free_gib": 9.5, "allocated_gib": 5.0, "reserved_gib": 6.0},
    "model": {"loaded": True, "model_name": "Juggernaut XL"},
    "windows_wddm": {"available": False},
}

FEATURES = {"model_discovery": True, "gpu_telemetry": True, "sdxl_generation": True}


def info(boot="b", instance="a", features=None, profile="p1"):
    from morphorum_studio.backend.session import SessionInfo

    return SessionInfo(profile, "Workshop GPU", "http://127.0.0.1:7866", "0.1.0a1", "backend-only",
                       instance * 32, boot * 32, dict(FEATURES if features is None else features))


class FakeClient:
    """Answers ``get_json`` from a table; ``log`` records (path, params)."""

    def __init__(self, routes, log):
        self.routes, self.log = routes, log

    def get_json(self, path, params=None):
        self.log.append((path, dict(params or {})))
        value = self.routes.get(path)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(params or {})
        if value is None:
            raise BackendError("NOT_FOUND", "no route", 404)
        return value


def default_routes():
    return {
        "/api/system/telemetry": TELEMETRY,
        "/api/models/families": FAMILIES,
        "/api/models/summary": SUMMARY,
        "/api/models": lambda params: {"models": [
            m for m in MODELS["models"] if not params.get("family") or m["family"] == params["family"]
        ]},
        "/api/generation/capabilities": CAPABILITIES,
        "/api/system/gpu-memory": GPU_MEMORY,
    }
