"""Turn an audio file into something the backend can analyse (S5.2a).

A PCM WAV that is within the backend's limits is sent untouched. Anything else (MP3, FLAC, OGG,
M4A, or an oversized WAV) is decoded on this PC with Qt Multimedia into mono 16-bit 22.05 kHz PCM,
cut to the project's length, and wrapped as a WAV. The file itself is never changed. Decoding by the
backend would be better (see docs/BACKEND_PROPOSALS.md); when it advertises that, Studio sends the
original file instead.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from morphorum_studio.backend.audio import (
    DECODE_RATE,
    MAX_WAV_BYTES,
    max_decode_seconds,
    pcm_to_wav,
    usable_wav,
)

try:  # QtMultimedia is optional in a build; without it only WAV files can be used.
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
except ImportError:  # pragma: no cover - depends on the PySide6 build
    QAudioDecoder = QAudioFormat = None

AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
SOURCE_LIMIT = 200 * 1024 * 1024  # never read more than this from disk
STALL_MS = 20000
_DEFAULT = object()


def decoding_available() -> bool:
    return QAudioDecoder is not None


def buffer_bytes(buffer) -> bytes:
    """Raw bytes of a QAudioBuffer, tolerant of how PySide6 exposes the pointer."""
    size = buffer.byteCount()
    try:
        return bytes(memoryview(buffer.constData())[:size])
    except (TypeError, ValueError):
        return bytes(buffer.data())[:size]


class AudioDecoder(QObject):
    """One decode at a time. ``finished(wav, seconds)`` or ``failed(message)``."""

    finished = Signal(bytes, float)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None, factory=_DEFAULT) -> None:
        super().__init__(parent)
        self._factory = QAudioDecoder if factory is _DEFAULT else factory
        self._decoder = None
        self._chunks: list[bytes] = []
        self._size = 0
        self._limit = 0
        self._busy = False
        self._stall = QTimer(self)
        self._stall.setSingleShot(True)
        self._stall.timeout.connect(lambda: self._fail("Decoding timed out. Try a WAV file."))

    @property
    def busy(self) -> bool:
        return self._busy

    def load(self, path: str, project_seconds: float) -> None:
        """Start preparing ``path``; WAV files that fit are passed through without decoding."""
        if self._busy:
            return
        file = Path(path)
        if file.suffix.lower() not in AUDIO_EXTENSIONS:
            self.failed.emit("Choose a WAV, MP3, FLAC, OGG or M4A file.")
            return
        try:
            size = file.stat().st_size
            if size > SOURCE_LIMIT:
                self.failed.emit("That file is larger than 200 MiB.")
                return
            if file.suffix.lower() == ".wav" and size <= MAX_WAV_BYTES:
                data = file.read_bytes()
                if usable_wav(data):
                    self.finished.emit(data, 0.0)
                    return
        except OSError as exc:
            self.failed.emit(f"Could not read the file: {exc.strerror or 'error'}")
            return
        if self._factory is None:
            self.failed.emit("This Studio build cannot decode that format. Use a WAV file.")
            return
        self._start(path, max_decode_seconds(project_seconds))

    # -- Qt decoding ----------------------------------------------------------------------

    def _start(self, path: str, seconds: float) -> None:
        self._busy = True
        self._chunks, self._size = [], 0
        self._limit = int(seconds * DECODE_RATE) * 2
        decoder = self._factory(self)
        self._decoder = decoder
        fmt = QAudioFormat()
        fmt.setSampleRate(DECODE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        decoder.setAudioFormat(fmt)
        decoder.setSource(QUrl.fromLocalFile(path))
        decoder.bufferReady.connect(self._ready)
        decoder.finished.connect(self._done)
        decoder.errorOccurred.connect(lambda *_a: self._fail(self._reason()))
        self._stall.start(STALL_MS)
        decoder.start()

    def _reason(self) -> str:
        text = ""
        try:
            text = self._decoder.errorString()
        except (AttributeError, RuntimeError):
            pass
        return "Could not decode that audio" + (f": {text}" if text else ".") + " Try a WAV file."

    def _ready(self) -> None:
        self._stall.start(STALL_MS)
        buffer = self._decoder.read()
        if not buffer.isValid():
            return
        data = buffer_bytes(buffer)
        room = self._limit - self._size
        if len(data) >= room:
            data = data[:room]
            self._chunks.append(data)
            self._size += len(data)
            self._decoder.stop()
            self._done()
            return
        self._chunks.append(data)
        self._size += len(data)

    def _done(self) -> None:
        if not self._busy:
            return
        self._release()
        pcm = b"".join(self._chunks)
        self._chunks = []
        pcm = pcm[:len(pcm) - len(pcm) % 2]
        if len(pcm) < DECODE_RATE // 5:
            self.failed.emit("That audio is empty or too short.")
            return
        wav = pcm_to_wav(pcm)
        if len(wav) > MAX_WAV_BYTES:
            self.failed.emit("The decoded audio is larger than the backend allows.")
            return
        self.finished.emit(wav, len(pcm) / 2 / DECODE_RATE)

    def _fail(self, message: str) -> None:
        if not self._busy:
            return
        self._release()
        self._chunks = []
        self.failed.emit(message)

    def _release(self) -> None:
        self._busy = False
        self._stall.stop()
        decoder, self._decoder = self._decoder, None
        if decoder is not None:
            try:
                decoder.stop()
            except RuntimeError:
                pass
            decoder.deleteLater()
