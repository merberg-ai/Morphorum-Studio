"""Small, non-blocking startup splash with real initialization-stage labels."""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QSplashScreen

from morphorum_studio import __version__
from morphorum_studio.ui.tokens import DARK

WIDTH, HEIGHT = 560, 430


def splash_logo_path():
    """Legacy artwork, still shipped for compatibility; the splash now paints the transparent mark."""
    return files("morphorum_studio").joinpath("assets", "splash-logo.jpg")


def mark_path():
    return files("morphorum_studio").joinpath("assets", "logo-mark.png")


def _font(family: str, size: int, weight: QFont.Weight) -> QFont:
    font = QFont(family)
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


class StudioSplash(QSplashScreen):
    def __init__(self):
        t = DARK
        image = QPixmap(WIDTH, HEIGHT)
        image.fill(QColor(t.void))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        glow = QRadialGradient(QPointF(WIDTH / 2, 150), 260)
        glow.setColorAt(0, QColor(79, 125, 255, 70))
        glow.setColorAt(1, QColor(79, 125, 255, 0))
        painter.fillRect(0, 0, WIDTH, HEIGHT, glow)
        violet = QRadialGradient(QPointF(WIDTH * 0.85, HEIGHT), 220)
        violet.setColorAt(0, QColor(148, 104, 255, 46))
        violet.setColorAt(1, QColor(148, 104, 255, 0))
        painter.fillRect(0, 0, WIDTH, HEIGHT, violet)

        mark = QPixmap(str(mark_path()))
        if not mark.isNull():
            size = 132
            painter.drawPixmap(
                QRectF((WIDTH - size) / 2, 48, size, size), mark, QRectF(mark.rect())
            )
        else:
            painter.setPen(QColor(t.cyan))
            painter.setFont(_font(t.font_display, 22, QFont.Weight.DemiBold))
            painter.drawText(0, 90, WIDTH, 60, Qt.AlignmentFlag.AlignCenter, "MORPHORUM")

        painter.setPen(QColor(t.text))
        painter.setFont(_font(t.font_display, 30, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(0, 196, WIDTH, 44), Qt.AlignmentFlag.AlignCenter, "Morphorum  STUDIO"
        )
        painter.setPen(QColor(t.faint))
        painter.setFont(_font(t.font_mono, 11, QFont.Weight.Normal))
        painter.drawText(
            QRectF(20, HEIGHT - 32, WIDTH - 40, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"v{__version__}",
        )
        painter.drawText(
            QRectF(20, HEIGHT - 32, WIDTH - 40, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "Audio-driven video, rendered on your GPU backend",
        )
        painter.end()
        super().__init__(image)
        self._background = image
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def stage(self, label: str, step: int = 1, total: int = 3) -> None:
        t = DARK
        canvas = self._background.copy()
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(_font(t.font_mono, 12, QFont.Weight.Normal))
        painter.setPen(QColor(t.dim))
        painter.drawText(
            QRectF(0, 266, WIDTH, 22), Qt.AlignmentFlag.AlignCenter, label
        )
        left, width, top = 60, WIDTH - 120, 306
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.raised))
        painter.drawRoundedRect(QRectF(left, top, width, 4), 2, 2)
        filled = round(width * min(max(step, 0), total) / total)
        if filled:
            gradient = QLinearGradient(QPointF(left, 0), QPointF(left + width, 0))
            gradient.setColorAt(0, QColor(t.grad_a))
            gradient.setColorAt(0.55, QColor(t.grad_b))
            gradient.setColorAt(1, QColor(t.grad_c))
            painter.setBrush(gradient)
            painter.drawRoundedRect(QRectF(left, top, filled, 4), 2, 2)
        painter.end()
        self.setPixmap(canvas)
