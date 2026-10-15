"""Reusable, non-modal status toast and indeterminate backend activity indicator."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


class FeedbackBanner(QFrame):
    """Compact inline toast. Errors persist until dismissed; success/info expire."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("feedbackBanner")
        self.setAccessibleName("Status notification")
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(4)
        row = QHBoxLayout()
        self.message = QLabel()
        self.message.setWordWrap(True)
        row.addWidget(self.message, 1)
        self.dismiss = QPushButton("Dismiss")
        self.dismiss.clicked.connect(self.hide)
        row.addWidget(self.dismiss)
        box.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        box.addWidget(self.progress)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def notify(self, message: str, *, kind: str = "info", busy: bool = False) -> None:
        if kind not in ("info", "success", "warning", "error"):
            raise ValueError("Unknown feedback kind")
        self._timer.stop()
        self.setProperty("feedbackKind", kind)
        self.setStyleSheet(
            "QFrame#feedbackBanner { border: 1px solid palette(mid); border-radius: 7px; }")
        self.message.setText(message)
        self.progress.setVisible(busy)
        self.show()
        if not busy and kind in ("info", "success"):
            self._timer.start(5000)
