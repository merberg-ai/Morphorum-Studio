"""Small, non-blocking startup splash with real initialization-stage labels."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen


def splash_logo_path() -> Path:
    # Source checkouts can supply the original logo here; packaged builds use importlib.resources later.
    return Path(__file__).resolve().parents[3] / "assets" / "morphorum-studio-logo.png"


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
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def stage(self, label: str) -> None:
        self.showMessage(
            label, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            QColor("#bbdef7")
        )
