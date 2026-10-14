"""S5.2a Audio Director: analysis parsing, decoding, service, controls and audio layers
(offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import io
import wave

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from morphorum_studio.backend.audio import (
    DECODE_RATE,
    STARTERS,
    AudioAnalysis,
    max_decode_seconds,
    new_audio_layer,
    parse_analysis,
    pcm_to_wav,
    refit_envelope,
    seconds_to_frames,
    usable_wav,
)
from morphorum_studio.backend.client import BackendError
from morphorum_studio.backend.session import BackendSession, SessionInfo
from morphorum_studio.ui import audio_decode
from morphorum_studio.ui.audio_decode import AudioDecoder
from morphorum_studio.ui.audio_service import AudioService
from morphorum_studio.ui.audio_widgets import AudioControls, AudioLayerForm, Audition, EnvelopeView
from morphorum_studio.ui.motion_panel import MotionPanel
from morphorum_studio.ui.motion_service import MotionService

QApplication.instance() or QApplication(["morphorum-studio-tests"])

SHA = "c" * 64
FRAMES, FPS = 24, 12.0


def sync_runner(client, fn, callback):
    try:
        result, error = fn(client), None
    except BackendError as exc:
        result, error = None, (exc.code, str(exc))
    callback(result, error)


def wav_bytes(seconds=1.0, rate=22050, channels=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x10" * int(rate * seconds) * channels)
    return out.getvalue()


def analysis_payload(sha=SHA, frames=FRAMES, fps=FPS):
    ramp = [(i % 6) / 5 * 0.3 for i in range(frames)]  # raw RMS: peak well below 1
    return {"status": "analyzed", "analysis": {
        "source_sha256": sha, "filename": sha + ".wav", "fps": fps, "frames": frames,
        "duration_seconds": frames / fps, "channels": 1, "values": ramp,
        "bands": {name: [(i % 4) / 3 for i in range(frames)]
                  for name in ("kick", "bass", "snare", "highs")}}}


# ----------------------------------------------------------------------------- pure helpers

def test_parse_analysis_normalises_every_band_to_its_own_peak():
    analysis = parse_analysis(analysis_payload())
    assert analysis.sha256 == SHA and analysis.frames == FRAMES and analysis.duration == 2.0
    assert set(analysis.bands) == {"fullband", "kick", "bass", "snare", "highs"}
    assert max(analysis.bands["fullband"]) == 1.0  # raw RMS 0.3 rescaled so thresholds mean something
    assert analysis.envelope("kick", 2, 6) == list(analysis.bands["kick"][2:6])


@pytest.mark.parametrize("mutate", [
    lambda p: p.pop("analysis"),
    lambda p: p["analysis"].update(source_sha256="nope"),
    lambda p: p["analysis"].update(frames=0),
    lambda p: p["analysis"].update(values=[0.1]),
    lambda p: p["analysis"].update(fps=0),
])
def test_parse_analysis_rejects_incomplete_answers(mutate):
    payload = analysis_payload()
    mutate(payload)
    with pytest.raises(BackendError):
        parse_analysis(payload)


def test_silent_audio_gives_flat_envelopes_and_range_errors_are_reported():
    payload = analysis_payload()
    payload["analysis"]["values"] = [0.0] * FRAMES
    analysis = parse_analysis(payload)
    assert set(analysis.bands["fullband"]) == {0.0}
    with pytest.raises(ValueError):
        analysis.envelope("kick", 0, FRAMES + 1)
    with pytest.raises(ValueError):
        analysis.envelope("bogus", 0, 2)


def test_wav_helpers():
    assert usable_wav(wav_bytes()) and not usable_wav(b"") and not usable_wav(b"ID3" + b"\0" * 40)
    assert not usable_wav(wav_bytes(seconds=1, rate=4000))  # below the backend's 8 kHz floor
    assert not usable_wav(b"RIFF" + b"\0" * 4 + b"WAVE" + b"junk")
    pcm = b"\x01\x00" * 100
    assert usable_wav(pcm_to_wav(pcm)) and pcm_to_wav(pcm)[:4] == b"RIFF"
    with pytest.raises(ValueError):
        pcm_to_wav(b"\x01")
    assert max_decode_seconds(10) == 11.0 and max_decode_seconds(0.0) == 1.0
    assert max_decode_seconds(10_000) == 180.0
    assert seconds_to_frames(0.26, 12.0, 1) == 3 and seconds_to_frames(0.0, 12.0, 1) == 1


def test_new_audio_layer_and_refit():
    analysis = parse_analysis(analysis_payload())
    layers = []
    for _label, name, band, axis, distance, detection in STARTERS:
        layers.append(new_audio_layer(layers, analysis, FRAMES, name=name, band=band, axis=axis,
                                      distance=distance, detection=detection))
    assert len({x["id"] for x in layers}) == len(STARTERS)
    kick = layers[0]
    assert kick["type"] == "audio" and len(kick["envelope"]) == FRAMES and kick["sha256"] == SHA
    assert kick["fps"] == FPS and kick["end_frame"] == FRAMES and kick["blend"] == "add"
    kick.update(start_frame=4, end_frame=10, band="snare")
    refit_envelope(kick, analysis)
    assert kick["envelope"] == list(analysis.bands["snare"][4:10])
    with pytest.raises(ValueError):
        new_audio_layer([], analysis, FRAMES, name="x", band="nope", axis="translation_z",
                        distance=0.1, detection="level")


# ----------------------------------------------------------------------------- decoding

class FakeBuffer:
    def __init__(self, data):
        self._data = data

    def isValid(self):
        return True

    def byteCount(self):
        return len(self._data)

    def constData(self):
        return self._data


class FakeDecoder(QObject):
    bufferReady = Signal()
    finished = Signal()
    errorOccurred = Signal(object, str)
    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buffers, self.stopped, self.started = [], False, False
        FakeDecoder.instances.append(self)

    def setAudioFormat(self, _fmt):
        pass

    def setSource(self, _url):
        pass

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def read(self):
        return FakeBuffer(self.buffers.pop(0))

    def errorString(self):
        return "no codec"


needs_multimedia = pytest.mark.skipif(audio_decode.QAudioFormat is None,
                                      reason="QtMultimedia is not available")


def test_wav_that_fits_is_passed_through_untouched(tmp_path):
    path = tmp_path / "song.wav"
    path.write_bytes(wav_bytes())
    decoder = AudioDecoder(factory=None)
    got = []
    decoder.finished.connect(lambda data, seconds: got.append(data))
    decoder.load(str(path), 10.0)
    assert got == [path.read_bytes()]


def test_unsupported_missing_and_undecodable_files(tmp_path):
    decoder = AudioDecoder(factory=None)
    errors = []
    decoder.failed.connect(errors.append)
    decoder.load(str(tmp_path / "x.txt"), 5.0)
    decoder.load(str(tmp_path / "missing.mp3"), 5.0)
    (tmp_path / "song.mp3").write_bytes(b"ID3" + b"\0" * 100)
    decoder.load(str(tmp_path / "song.mp3"), 5.0)  # no decoder in this build
    assert "WAV, MP3" in errors[0] and "Could not read" in errors[1] and "cannot decode" in errors[2]


@needs_multimedia
def test_decoded_audio_becomes_a_wav_cut_to_the_project_length(tmp_path):
    (tmp_path / "song.mp3").write_bytes(b"ID3" + b"\0" * 100)
    FakeDecoder.instances.clear()
    decoder = AudioDecoder(factory=FakeDecoder)
    got, errors = [], []
    decoder.finished.connect(lambda data, seconds: got.append((data, seconds)))
    decoder.failed.connect(errors.append)
    decoder.load(str(tmp_path / "song.mp3"), 1.0)  # project of 1 s -> decode 2 s at most
    fake = FakeDecoder.instances[0]
    assert fake.started and decoder.busy
    chunk = b"\x01\x00" * DECODE_RATE  # 1 s of samples
    fake.buffers = [chunk, chunk, chunk]
    for _ in range(3):
        fake.bufferReady.emit()
        if not decoder.busy:
            break
    assert errors == [] and len(got) == 1 and not decoder.busy and fake.stopped
    wav, seconds = got[0]
    assert usable_wav(wav) and seconds == pytest.approx(2.0)


@needs_multimedia
def test_decoder_errors_and_empty_audio_are_reported(tmp_path):
    (tmp_path / "song.ogg").write_bytes(b"OggS" + b"\0" * 100)
    FakeDecoder.instances.clear()
    decoder = AudioDecoder(factory=FakeDecoder)
    errors = []
    decoder.failed.connect(errors.append)
    decoder.load(str(tmp_path / "song.ogg"), 5.0)
    FakeDecoder.instances[0].errorOccurred.emit(1, "x")
    assert "no codec" in errors[0] and not decoder.busy
    decoder.load(str(tmp_path / "song.ogg"), 5.0)
    FakeDecoder.instances[1].finished.emit()  # finished with nothing decoded
    assert "empty or too short" in errors[1]


# ----------------------------------------------------------------------------- service + panel

class Fake:
    def __init__(self):
        self.calls, self.fail = [], {}
        self.project = {"id": "demo", "animation": {"mode": "3d", "max_frames": FRAMES, "fps": FPS},
                        "motion_lab": {"layers": []}}
        self.soundtrack = None

    def get_json(self, path, params=None):
        self.calls.append(("GET", path))
        if path == "/api/animation/motion-lab/presets":
            return {"presets": ["still", "wave"]}
        if path.endswith("/motion-import/soundtrack"):
            if "soundtrack" in self.fail:
                raise self.fail["soundtrack"]
            return {"soundtrack": self.soundtrack} if self.soundtrack else {"soundtrack": None}
        raise BackendError("NOT_FOUND", path)

    def get_json_etag(self, path, params=None):
        return {"project": {**self.project, "id": path.rsplit("/", 1)[-1]}}, '"' + "a" * 64 + '"'

    def upload_bytes(self, path, data, headers):
        self.calls.append(("UPLOAD", path, len(data)))
        if "analyze" in self.fail:
            raise self.fail["analyze"]
        return analysis_payload()

    def download(self, path, sink, max_bytes):
        self.calls.append(("DOWNLOAD", path))
        sink(wav_bytes())
        return 1, SHA, SHA

    def send_json(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        step = path.rsplit("/", 1)[-1]
        if step == "preview":
            layers = [{**x, "pulses": [0.0, 0.02, -0.02] + [0.0] * (x["end_frame"] - x["start_frame"] - 3)}
                      for x in body["layers"]]
            return {"status": "preview", "layers": layers, "diagnostics": {
                "series": {a: [0.0] * FRAMES for a in
                           ("translation_x", "translation_y", "translation_z",
                            "rotation_x", "rotation_y", "rotation_z")},
                "limited": {}, "frames": FRAMES, "fps": FPS}}, None
        return {"status": "applied", "project": self.project, "diagnostics": {}}, None


class FakePlayer(QObject):
    class MediaStatus:
        EndOfMedia = object()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pos, self.playing, self.source = 0, False, None

    def setSource(self, url):
        self.source = url.toLocalFile()

    def setPosition(self, ms):
        self.pos = ms

    def position(self):
        return self.pos

    def play(self):
        self.playing = True

    def pause(self):
        self.playing = False

    def mediaStatus(self):
        return None


def info(features=None):
    return SessionInfo("p1", "Workshop", "http://10.0.0.5:7866", "0.1.0", "backend-only", "i1", "b1",
                       {"timeline": True} if features is None else features)


class StubDecoder(QObject):
    finished = Signal(bytes, float)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.busy = False
        self.requests = []

    def load(self, path, seconds):
        self.requests.append((path, seconds))
        self.finished.emit(wav_bytes(), 1.0)


def rig(tmp_path, project=None):
    client = Fake()
    if project:
        client.project = project
    session = BackendSession(client_factory=lambda base, token, timeout=6.0: client)
    motion = MotionService(session, runner=sync_runner)
    audio = AudioService(session, tmp_path / "cache", runner=sync_runner)
    decoder, audition = StubDecoder(), Audition(player_factory=FakePlayer)
    panel = MotionPanel(motion, audio, decoder, audition)
    session.connected(info(), "t")
    panel.set_project("demo")
    return client, session, audio, decoder, audition, panel


def test_load_audio_analyses_and_enables_audio_layers(tmp_path):
    client, session, audio, decoder, audition, panel = rig(tmp_path)
    assert not panel.add_audio_button.isEnabled()
    panel.audio.load_file(str(tmp_path / "song.mp3"))
    assert decoder.requests[0][1] == pytest.approx(2.0)  # 24 frames at 12 fps
    assert [c[0] for c in client.calls if c[0] == "UPLOAD"] == ["UPLOAD"]
    assert panel.audio.analysis.sha256 == SHA and "Analysed" in panel.audio.status.text()
    assert panel.add_audio_button.isEnabled()
    assert panel.audio.audition_button.isEnabled()


def test_starter_layer_edit_preview_and_envelope(tmp_path):
    client, session, audio, decoder, audition, panel = rig(tmp_path)
    panel.audio.load_file(str(tmp_path / "song.mp3"))
    panel.audio_menu.actions()[1].trigger()  # Snare -> Pan
    layer = panel.layers[0]
    assert layer["type"] == "audio" and layer["band"] == "snare" and layer["axis"] == "rotation_y"
    assert panel.forms.currentIndex() == 3 and panel.envelope.isVisibleTo(panel)
    # edits go through the form: seconds are converted to whole frames
    panel.audio_form.attack_spin.setValue(0.25)
    panel.audio_form.gap_spin.setValue(0.5)
    panel.audio_form.threshold_spin.setValue(0.4)
    panel.audio_form.distance_spin.setValue(0.9)
    panel.audio_form.offset_spin.setValue(-0.25)
    edited = panel.layers[0]
    assert edited["attack_frames"] == 3 and edited["cooldown_frames"] == 6 and edited["offset_frames"] == -3
    assert edited["threshold"] == 0.4 and edited["distance"] == 0.9
    # band change re-slices the envelope; range change too
    panel.audio_form.band_combo.setCurrentIndex(panel.audio_form.band_combo.findData("highs"))
    panel.audio_form.band_combo.activated.emit(0)
    assert panel.layers[0]["band"] == "highs"
    assert panel.layers[0]["envelope"] == list(audio.analysis(SHA).bands["highs"])
    panel.end_spin.setValue(12)
    assert len(panel.layers[0]["envelope"]) == 12 and panel.layers[0]["end_frame"] == 12
    panel.preview_button.click()
    assert panel._pulses[edited["id"]][1] == 0.02 and panel._pulses_stale is False
    panel.audio_form.threshold_spin.setValue(0.5)
    assert panel._pulses_stale is True  # markers are dimmed until the next preview


def test_selecting_a_saved_audio_layer_recovers_its_audio(tmp_path):
    saved = new_audio_layer([], parse_analysis(analysis_payload()), FRAMES, name="Kick", band="kick",
                            axis="translation_z", distance=0.04, detection="level")
    project = {"id": "demo", "animation": {"mode": "3d", "max_frames": FRAMES, "fps": FPS},
               "motion_lab": {"layers": [saved]}}
    client, session, audio, decoder, audition, panel = rig(tmp_path, project)
    assert ("DOWNLOAD", f"/api/animation/projects/demo/motion-lab/audio/{SHA}") in client.calls
    assert audio.analysis(SHA) is not None and audio.playable(SHA).endswith(SHA + ".wav")
    assert panel.audio_form.band_combo.isEnabled() and panel.start_spin.isEnabled()
    assert panel.audio.audition_button.isEnabled()


def test_without_the_audio_band_and_range_stay_locked(tmp_path):
    saved = new_audio_layer([], parse_analysis(analysis_payload()), FRAMES, name="Kick", band="kick",
                            axis="translation_z", distance=0.04, detection="level")
    project = {"id": "demo", "animation": {"mode": "3d", "max_frames": FRAMES, "fps": FPS},
               "motion_lab": {"layers": [saved]}}
    client = Fake()
    client.project = project
    client.download = lambda *a, **k: (_ for _ in ()).throw(BackendError("NOT_FOUND", "audio file missing"))
    session = BackendSession(client_factory=lambda base, token, timeout=6.0: client)
    motion = MotionService(session, runner=sync_runner)
    audio = AudioService(session, tmp_path / "cache", runner=sync_runner)
    panel = MotionPanel(motion, audio, StubDecoder(), Audition(player_factory=FakePlayer))
    session.connected(info(), "t")
    panel.set_project("demo")
    assert not panel.audio_form.band_combo.isEnabled() and not panel.start_spin.isEnabled()
    assert "audio file missing" in panel.status.text()
    panel.audio_form.threshold_spin.setValue(0.6)  # pulse settings still work
    assert panel.layers[0]["threshold"] == 0.6


def test_failed_analysis_is_reported(tmp_path):
    client, session, audio, decoder, audition, panel = rig(tmp_path)
    client.fail["analyze"] = BackendError("INVALID_REQUEST", "Audio file exceeds 20 MiB.")
    panel.audio.load_file(str(tmp_path / "song.mp3"))
    assert "20 MiB" in panel.audio.status.text() and panel.audio.analysis is None


def test_mismatched_project_timing_is_flagged(tmp_path):
    client, session, audio, decoder, audition, panel = rig(tmp_path)
    original = client.upload_bytes
    client.upload_bytes = lambda p, d, h: analysis_payload(fps=24.0, frames=48) if original else None
    panel.audio.load_file(str(tmp_path / "song.mp3"))
    assert "differs" in panel.audio.status.text()


def test_soundtrack_note(tmp_path):
    client, session, audio, decoder, audition, panel = rig(tmp_path)
    panel.audio.load_file(str(tmp_path / "song.mp3"))
    assert "No soundtrack is attached" in panel.soundtrack_note.text()
    assert panel.soundtrack_note.isVisibleTo(panel)


def test_audition_follows_the_sound_and_stops(tmp_path):
    client, session, audio, decoder, audition, panel = rig(tmp_path)
    panel.audio.load_file(str(tmp_path / "song.mp3"))
    panel.audio.set_playhead(6)
    frames = []
    panel.playhead_requested.connect(frames.append)
    panel.audio.audition_button.click()
    assert audition.playing and audition._player.pos == 500  # frame 6 at 12 fps
    audition._player.pos = 1000
    audition._tick()
    assert frames == [12]
    panel.audio.audition_button.click()
    assert not audition.playing and not audition._player.playing


def test_audition_unsupported_build_explains():
    audition = Audition(player_factory=None)
    audition._factory = None
    seen = []
    audition.failed.connect(seen.append)
    audition.play("x.wav", 0, 12.0)
    assert "cannot play" in seen[0] and not audition.supported


def test_envelope_view_paints_with_and_without_a_layer():
    view = EnvelopeView()
    view.resize(300, 104)
    view.grab()
    layer = {"start_frame": 2, "envelope": [0.1, 0.9, 0.4, 0.0], "threshold": 0.5}
    view.set_layer(layer, 24, pulses=[0.0, 0.02, -0.02, 0.0])
    view.set_frame(3)
    assert view.grab().width() == 300
    view.set_layer(layer, 24, pulses=[0.02], stale=True)
    view.grab()


def test_audio_layer_form_shows_sensitivity_only_for_transients():
    form = AudioLayerForm()
    layer = {"name": "Snare", "axis": "rotation_y", "band": "snare", "detection": "transient",
             "threshold": 0.3, "sensitivity": 0.5, "distance": 0.8, "attack_frames": 3,
             "release_frames": 6, "cooldown_frames": 6, "offset_frames": -3}
    form.load(layer, 12.0, True)
    assert form.attack_spin.value() == 0.25 and form.offset_spin.value() == -0.25
    assert not form.sensitivity_spin.isHidden()
    form.load({**layer, "detection": "level"}, 12.0, False)
    assert form.sensitivity_spin.isHidden() and form.lock_note.text()
    assert not form.band_combo.isEnabled()


def test_controls_ignore_files_until_motion_lab_is_usable():
    class Svc(QObject):
        analyzed = Signal(object, str)
        failed = Signal(str, str, str)
        busy_changed = Signal(bool)
        cleared = Signal()
        busy = False

        def playable(self, _sha):
            return ""

        def analyze(self, *_a):
            raise AssertionError("should not analyse")

    decoder = StubDecoder()
    controls = AudioControls(Svc(), decoder, Audition(player_factory=FakePlayer))
    controls.configure("demo", 24, 12.0, usable=False)
    controls.load_file("song.wav")
    assert decoder.requests == [] and not controls.load_button.isEnabled()


def test_analysis_dataclass_is_frozen():
    analysis = AudioAnalysis(SHA, "x.wav", 12.0, 2, 1.0, 1, {"fullband": (0.0, 1.0)})
    with pytest.raises(AttributeError):
        analysis.fps = 5.0
