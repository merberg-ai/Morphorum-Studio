"""Timeline preview player: the rendered frame at the playhead plus transport controls.

It only shows frames the backend has actually rendered; a frame that has not been rendered says
so instead of showing an approximation. Playing advances the playhead at the project's frame rate
(capped at 12 per second, since every frame is downloaded) and stops at the last frame.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.ui.tokens import DARK, Tokens

MAX_PLAY_FPS = 12.0


class FrameView(QWidget):
    """The picture area: fits the frame inside the box, or shows why there is none."""

    def __init__(self, tokens: Tokens = DARK) -> None:
        super().__init__()
        self._tokens = tokens
        self._pixmap: QPixmap | None = None
        self._message = "Open a project to preview its rendered frames"
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    @property
    def message(self) -> str:
        return self._message

    @property
    def has_image(self) -> bool:
        return self._pixmap is not None

    def show_png(self, data: bytes) -> bool:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return False
        self._pixmap, self._message = pixmap, ""
        self.update()
        return True

    def show_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap, self._message = pixmap, ""
        self.update()

    def show_message(self, text: str) -> None:
        self._pixmap, self._message = None, text
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.base))
        painter.drawRoundedRect(rect, 8, 8)
        if self._pixmap is None:
            painter.setPen(QColor(t.faint))
            painter.drawText(rect.adjusted(16, 8, -16, -8),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._message)
            return
        scale = min(rect.width() / self._pixmap.width(), rect.height() / self._pixmap.height())
        w, h = self._pixmap.width() * scale, self._pixmap.height() * scale
        painter.drawPixmap(QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h),
                           self._pixmap, QRectF(self._pixmap.rect()))


class PlayerPanel(QFrame):
    frame_requested = Signal(int)  # the user (or playback) wants the playhead here

    def __init__(self, tokens: Tokens = DARK) -> None:
        super().__init__()
        self.setObjectName("card")
        self._max_frames = 0
        self._fps = 0.0
        self._frame = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(10)
        self.view = FrameView(tokens)
        box.addWidget(self.view, 1)
        self.caption = QLabel("")
        self.caption.setObjectName("hint")
        self.caption.setWordWrap(True)
        box.addWidget(self.caption)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.first_button = QPushButton("|◀")
        self.prev_button = QPushButton("◀")
        self.play_button = QPushButton("Play")
        self.next_button = QPushButton("▶")
        self.last_button = QPushButton("▶|")
        tips = {
            self.first_button: "Go to the first frame",
            self.prev_button: "Step back one frame (Left)",
            self.play_button: "Play from the playhead at the project's frame rate (frames are downloaded as it plays)",
            self.next_button: "Step forward one frame (Right)",
            self.last_button: "Go to the last frame",
        }
        for button, tip in tips.items():
            button.setToolTip(tip)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            row.addWidget(button)
        self.play_button.setMinimumWidth(72)
        row.addStretch(1)
        self.position = QLabel("")
        self.position.setObjectName("metricValue")
        row.addWidget(self.position)
        box.addLayout(row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.first_button.clicked.connect(lambda: self._go(0))
        self.prev_button.clicked.connect(lambda: self._go(self._frame - 1))
        self.next_button.clicked.connect(lambda: self._go(self._frame + 1))
        self.last_button.clicked.connect(lambda: self._go(self._max_frames - 1))
        self.play_button.clicked.connect(self.toggle_play)
        self._refresh()

    # -- state ----------------------------------------------------------------------------

    @property
    def playing(self) -> bool:
        return self._timer.isActive()

    @property
    def frame(self) -> int:
        return self._frame

    def set_range(self, max_frames: int, fps: float) -> None:
        """Enable the transport for a timeline of ``max_frames`` at ``fps``; 0 disables it."""
        self.stop()
        self._max_frames = max(0, max_frames)
        self._fps = fps
        self._frame = 0
        self._refresh()

    def set_frame(self, frame: int) -> None:
        """Show ``frame`` as the playhead (no signal: the owner already knows)."""
        if self._max_frames:
            frame = max(0, min(frame, self._max_frames - 1))
        self._frame = frame
        self._refresh()

    def _refresh(self) -> None:
        have = self._max_frames > 0
        for button in (self.first_button, self.prev_button, self.play_button,
                       self.next_button, self.last_button):
            button.setEnabled(have)
        self.first_button.setEnabled(have and self._frame > 0)
        self.prev_button.setEnabled(have and self._frame > 0)
        self.next_button.setEnabled(have and self._frame < self._max_frames - 1)
        self.last_button.setEnabled(have and self._frame < self._max_frames - 1)
        self.play_button.setText("Pause" if self.playing else "Play")
        if have and self._fps:
            self.position.setText(
                f"Frame {self._frame + 1} / {self._max_frames} · {self._frame / self._fps:.2f} s")
        else:
            self.position.setText("")

    # -- picture ----------------------------------------------------------------------------

    def show_png(self, data: bytes, caption: str = "") -> None:
        if self.view.show_png(data):
            self.caption.setText(caption)
        else:
            self.show_message("This frame could not be read")

    def show_message(self, text: str, caption: str = "") -> None:
        self.view.show_message(text)
        self.caption.setText(caption)

    # -- transport --------------------------------------------------------------------------

    def _go(self, frame: int) -> None:
        if not self._max_frames:
            return
        frame = max(0, min(frame, self._max_frames - 1))
        if frame != self._frame:
            self._frame = frame
            self._refresh()
            self.frame_requested.emit(frame)

    def toggle_play(self) -> None:
        if self.playing:
            self.stop()
        elif self._max_frames and self._frame < self._max_frames - 1:
            self._timer.start(int(1000 / min(self._fps or MAX_PLAY_FPS, MAX_PLAY_FPS)))
        self._refresh()

    def stop(self) -> None:
        self._timer.stop()
        self._refresh()

    def _tick(self) -> None:
        if self._frame >= self._max_frames - 1:
            self.stop()
            return
        self._go(self._frame + 1)
        if self._frame >= self._max_frames - 1:
            self.stop()
