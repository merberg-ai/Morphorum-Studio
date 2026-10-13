"""Native viewer for one generated image: fit or zoom, and a verified save-a-copy."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

ZOOM_STEPS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)


class ImageViewer(QDialog):
    save_requested = Signal()

    def __init__(self, title: str, pixmap: QPixmap | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 700)
        self._pixmap = pixmap if pixmap is not None else QPixmap()
        self._fit = True
        self._zoom = 1.0
        box = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.fit_button = QPushButton("Fit")
        self.actual_button = QPushButton("100%")
        self.out_button = QPushButton("−")
        self.in_button = QPushButton("+")
        self.zoom_label = QLabel("")
        self.save_button = QPushButton("Save copy…")
        for button in (self.fit_button, self.actual_button, self.out_button, self.in_button):
            button.setFixedWidth(64)
            bar.addWidget(button)
        bar.addWidget(self.zoom_label)
        bar.addStretch(1)
        bar.addWidget(self.save_button)
        box.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.image)
        box.addWidget(self.scroll, 1)
        self.fit_button.clicked.connect(self.show_fit)
        self.actual_button.clicked.connect(lambda: self.set_zoom(1.0))
        self.out_button.clicked.connect(lambda: self._step(-1))
        self.in_button.clicked.connect(lambda: self._step(1))
        self.save_button.clicked.connect(self.save_requested)
        self._render()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._render()

    def show_fit(self) -> None:
        self._fit = True
        self._render()

    def set_zoom(self, zoom: float) -> None:
        self._fit = False
        self._zoom = min(max(zoom, ZOOM_STEPS[0]), ZOOM_STEPS[-1])
        self._render()

    def _step(self, direction: int) -> None:
        current = self.current_zoom()
        steps = [z for z in ZOOM_STEPS if (z > current + 1e-6 if direction > 0 else z < current - 1e-6)]
        if steps:
            self.set_zoom(steps[0] if direction > 0 else steps[-1])

    def current_zoom(self) -> float:
        if self._pixmap.isNull():
            return 1.0
        if not self._fit:
            return self._zoom
        area = self.scroll.viewport().size()
        return min(1.0, max(0.05, min(area.width() / self._pixmap.width(),
                                       area.height() / self._pixmap.height())))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit:
            self._render()

    def _render(self) -> None:
        if self._pixmap.isNull():
            self.image.setText("Loading…")
            self.image.adjustSize()
            self.zoom_label.setText("")
            return
        zoom = self.current_zoom()
        scaled = self._pixmap.scaled(
            max(1, int(self._pixmap.width() * zoom)), max(1, int(self._pixmap.height() * zoom)),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image.setPixmap(scaled)
        self.image.resize(scaled.size())
        self.zoom_label.setText(f"{zoom * 100:.0f}%  ·  {self._pixmap.width()}×{self._pixmap.height()}")
