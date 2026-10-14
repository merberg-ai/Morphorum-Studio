"""Manual check: audio layers built by Studio are accepted by the real Morphorum backend's Motion Lab
compiler and produce pulses that return to zero. Needs numpy and a checkout of the backend repo.

    python scripts/verify_backend_audio_layers.py /path/to/Morphorum/backend
"""
import sys, types
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, 'src')
sys.modules.setdefault('PySide6', types.ModuleType('PySide6'))
import numpy as np
from morphorum.audio_motion import frame_envelope, spectral_band_envelopes
from morphorum.animation_projects import new_animation_project_template, normalize_animation_project
from morphorum.motion_lab import compile_motion_lab
from morphorum_studio.backend import audio as A

project = new_animation_project_template()
project = project.get("project", project)
project.setdefault("animation", {}).update(mode="3d", max_frames=48, fps=12)
project = normalize_animation_project(project, project_id="demo")
frames, fps, rate = 48, 12.0, 22050
t = np.arange(int(rate * frames / fps)) / rate
pcm = (np.sin(2*np.pi*60*t) * (np.sin(2*np.pi*2*t) > 0.8) * 0.6 + 0.3*np.sin(2*np.pi*3000*t)*(np.sin(2*np.pi*3*t) > 0.9)).tolist()
env = frame_envelope(pcm, sample_rate=rate, fps=fps, max_frames=frames)
env["bands"] = spectral_band_envelopes(pcm, sample_rate=rate, fps=fps, max_frames=frames)
env.update(source_sha256="b"*64, filename="x.wav", duration_seconds=frames/fps, channels=1)
analysis = A.parse_analysis({"analysis": env})
layers = []
for label, name, band, axis, dist, det in A.STARTERS:
    layers.append(A.new_audio_layer(layers, analysis, frames, name=name, band=band, axis=axis, distance=dist, detection=det))
compiled, diag = compile_motion_lab(project, layers=layers, conflict_policy="use-current", include_series=True)
norm = compiled["motion_lab"]["layers"]
print("layers accepted:", len(norm), "limited:", diag["limited"])
for layer in norm:
    pulses = layer["pulses"]
    print(layer["name"], layer["band"], layer["detection"], "pulses:", sum(1 for p in pulses if p), "net:", round(sum(pulses), 9))
# changing range and band the way the panel does
layer = layers[0]; layer.update(start_frame=10, end_frame=40, band="bass"); A.refit_envelope(layer, analysis)
compile_motion_lab(project, layers=[layer], conflict_policy="use-current")
print("refit ok, envelope len", len(layer["envelope"]))
