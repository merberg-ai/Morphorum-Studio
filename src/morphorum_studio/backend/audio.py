"""Audio Director (S5.2a): analysis of a project's audio and the audio layers built from it.

Studio sends a PCM WAV to the backend, which measures a per-frame envelope (full mix plus four
frequency bands) at the project's frame rate. An *audio layer* then carries one band's envelope
for its frame range, plus the pulse settings; the backend turns that into balanced camera pulses
that always return to where they started. The detection ideas (frequency-band channels, level
and transient detection, threshold, attack/return, minimum gap, timing offset) follow Deforum
Motion Studio by chicodog530, used with permission; this is an independent implementation.
"""

from __future__ import annotations

import io
import re
import wave
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .client import BackendClient, BackendError
from .motion import AXES
from .projects import valid_project_id

BANDS = ("fullband", "kick", "bass", "snare", "highs")
BAND_LABELS = {
    "fullband": "Full mix", "kick": "Kick (35–140 Hz)", "bass": "Bass (40–250 Hz)",
    "snare": "Snare (150–2400 Hz)", "highs": "Highs (2.5–10 kHz)",
}
DETECTIONS = ("level", "transient")
DETECTION_LABELS = {"level": "Level (when it gets loud)", "transient": "Transient (sudden hits)"}
MAX_WAV_BYTES = 20 * 1024 * 1024
MAX_WAV_SECONDS = 180
DECODE_RATE = 22050  # Hz; mono 16-bit keeps three minutes near 8 MiB and covers the highs band
SHA = re.compile(r"[0-9a-f]{64}")

# Starter channels: (button label, layer name, band, camera axis, pulse distance, detection)
STARTERS = (
    ("Kick → Move forward", "Kick pulse", "kick", "translation_z", 0.04, "level"),
    ("Snare → Pan", "Snare pan", "snare", "rotation_y", 0.8, "transient"),
    ("Highs → Roll", "Highs roll", "highs", "rotation_z", 0.5, "transient"),
    ("Full mix → Move forward", "Full-mix pulse", "fullband", "translation_z", 0.03, "level"),
)


@dataclass(frozen=True)
class AudioAnalysis:
    sha256: str  # of the exact WAV the backend analysed
    filename: str
    fps: float
    frames: int
    duration: float
    channels: int
    bands: dict[str, tuple[float, ...]] = field(default_factory=dict)  # each 0..1, one per frame

    def envelope(self, band: str, start: int, end: int) -> list[float]:
        values = self.bands.get(band)
        if values is None:
            raise ValueError("unknown band")
        if not 0 <= start < end <= len(values):
            raise ValueError("range is outside the analysed audio")
        return list(values[start:end])


def _normalised(values: Any, frames: int) -> tuple[float, ...]:
    if not isinstance(values, list) or len(values) != frames:
        raise BackendError("INVALID_RESPONSE", "Audio analysis is incomplete")
    numbers = [float(v) for v in values
               if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(numbers) != frames:
        raise BackendError("INVALID_RESPONSE", "Audio analysis has non-numeric values")
    peak = max(numbers, default=0.0)
    if peak <= 1e-12:
        return tuple(0.0 for _ in numbers)
    return tuple(round(min(1.0, max(0.0, v / peak)), 7) for v in numbers)


def parse_analysis(payload: Any) -> AudioAnalysis:
    data = payload.get("analysis") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        raise BackendError("INVALID_RESPONSE", "Audio analysis response is incomplete")
    sha = data.get("source_sha256")
    frames, fps = data.get("frames"), data.get("fps")
    if (not isinstance(sha, str) or not SHA.fullmatch(sha) or type(frames) is not int
            or not 1 <= frames <= 3000 or not isinstance(fps, (int, float)) or fps <= 0):
        raise BackendError("INVALID_RESPONSE", "Audio analysis response is incomplete")
    bands = {"fullband": _normalised(data.get("values"), frames)}
    raw = data.get("bands") if isinstance(data.get("bands"), Mapping) else {}
    for name in BANDS[1:]:
        if name in raw:
            bands[name] = _normalised(raw[name], frames)
    duration = data.get("duration_seconds")
    channels = data.get("channels")
    return AudioAnalysis(
        sha256=sha, filename=str(data.get("filename") or "")[:100], fps=float(fps), frames=frames,
        duration=float(duration) if isinstance(duration, (int, float)) else 0.0,
        channels=channels if type(channels) is int else 1, bands=bands)


# ----------------------------------------------------------------------------- WAV helpers

def pcm_to_wav(pcm: bytes, rate: int = DECODE_RATE, channels: int = 1) -> bytes:
    """Wrap 16-bit little-endian PCM in a WAV container."""
    if not pcm or len(pcm) % (2 * channels):
        raise ValueError("PCM data must be whole 16-bit frames")
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return out.getvalue()


def usable_wav(data: bytes) -> bool:
    """True when the backend will accept these bytes as they are (PCM WAV within its limits)."""
    if not data or len(data) > MAX_WAV_BYTES or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            rate = wav.getframerate()
            return (wav.getnchannels() in (1, 2) and wav.getsampwidth() in (1, 2, 3, 4)
                    and 8000 <= rate <= 192000 and wav.getnframes() <= rate * MAX_WAV_SECONDS)
    except (wave.Error, EOFError):
        return False


def max_decode_seconds(duration: float) -> float:
    """How much audio to decode: the project's length plus a little, never beyond the backend's cap."""
    return float(min(MAX_WAV_SECONDS, max(1.0, duration + 1.0)))


# ----------------------------------------------------------------------------- layers

def seconds_to_frames(seconds: float, fps: float, minimum: int = 0) -> int:
    return max(minimum, round(seconds * fps))


def frames_to_seconds(frames: int, fps: float) -> float:
    return frames / fps if fps > 0 else 0.0


def is_starter_axis(axis: str) -> bool:
    return axis in AXES


def new_audio_layer(layers, analysis: AudioAnalysis, frames: int, *, name: str, band: str,
                    axis: str, distance: float, detection: str) -> dict[str, Any]:
    """A new audio layer over the whole video. The envelope is the chosen band's values."""
    from .motion import unique_id
    if band not in analysis.bands or axis not in AXES or detection not in DETECTIONS:
        raise ValueError("unknown band, axis or detection")
    end = min(frames, analysis.frames)
    return {
        "id": unique_id(layers), "type": "audio", "name": name[:96], "enabled": True,
        "blend": "add", "start_frame": 0, "end_frame": end, "axis": axis, "fps": analysis.fps,
        "sha256": analysis.sha256, "band": band, "detection": detection, "sensitivity": 0.35,
        "threshold": 0.25, "distance": distance, "attack_frames": 1, "release_frames": 3,
        "cooldown_frames": 3, "offset_frames": 0,
        "envelope": analysis.envelope(band, 0, end),
    }


def refit_envelope(layer: dict[str, Any], analysis: AudioAnalysis) -> None:
    """Re-slice a layer's envelope after its band or frame range changed."""
    layer["envelope"] = analysis.envelope(
        str(layer.get("band", "fullband")), int(layer["start_frame"]), int(layer["end_frame"]))
    layer["sha256"], layer["fps"] = analysis.sha256, analysis.fps


# ----------------------------------------------------------------------------- calls

class AudioApi:
    def __init__(self, client: BackendClient) -> None:
        self._client = client

    @staticmethod
    def _path(project_id: str) -> str:
        if not valid_project_id(project_id):
            raise ValueError("invalid project id")
        return f"/api/animation/projects/{project_id}/motion-lab/"

    def analyze(self, project_id: str, wav: bytes) -> AudioAnalysis:
        if not usable_wav(wav):
            raise BackendError("INVALID_AUDIO", "That audio is not a WAV the backend can analyse")
        payload = self._client.upload_bytes(self._path(project_id) + "audio-analyze", wav, {})
        return parse_analysis(payload)

    def fetch_wav(self, project_id: str, sha256: str) -> bytes:
        if not SHA.fullmatch(sha256):
            raise ValueError("invalid audio hash")
        chunks: list[bytes] = []
        self._client.download(self._path(project_id) + f"audio/{sha256}", chunks.append, MAX_WAV_BYTES)
        return b"".join(chunks)
