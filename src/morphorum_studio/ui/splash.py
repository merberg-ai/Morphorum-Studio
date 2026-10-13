"""Small, non-blocking startup splash with real initialization-stage labels."""
from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen


def splash_logo_path():
    return files("morphorum_studio").joinpath("assets", "splash-logo.jpg")


class StudioSplash(QSplashScreen):
    def __init__(self):
        image = QPixmap(560, 430)
        image.fill(QColor("#10131d"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        logo = QPixmap(str(splash_logo_path()))
        if not logo.isNull():
            scaled = logo.scaled(
                410, 308, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            painter.drawPixmap((560 - scaled.width()) // 2, 18, scaled)
        else:
            painter.setPen(QColor("#75d9ff"))
            painter.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
            painter.drawText(30, 130, 500, 80, Qt.AlignmentFlag.AlignCenter,
                             "MORPHORUM STUDIO")
        painter.setPen(QColor("#63748f"))
        painter.drawLine(44, 344, 516, 344)
        painter.end()
        super().__init__(image)
        self._background = image
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def stage(self, label: str, step: int = 1, total: int = 3) -> None:
        canvas = self._background.copy()
        painter = QPainter(canvas)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#263246"))
        painter.drawRoundedRect(44, 359, 472, 6, 3, 3)
        painter.setBrush(QColor("#68c8ff"))
        painter.drawRoundedRect(44, 359, round(472 * min(max(step, 0), total) / total), 6, 3, 3)
        painter.end()
        self.setPixmap(canvas)
        self.showMessage(
            label, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            QColor("#bbdef7")
        )
