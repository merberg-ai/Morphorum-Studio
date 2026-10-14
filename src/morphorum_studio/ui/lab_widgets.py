"""Small controls for the Lab: slider-and-spin pairs, aspect tiles and LoRA weight rows.

LoRA weights live in the prompt text as ``<lora:name:weight>`` tags (that is what the backend
reads), so the weight rows are a view of those tags: moving a slider rewrites the tag, and
editing the prompt updates the rows.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

LORA_TAG = re.compile(r"<lora:([^:<>]+):(-?\d+(?:\.\d+)?)>")
LORA_RANGE = (-2.0, 2.0)
LORA_STEP = 0.05


def parse_lora_tags(text: str) -> list[tuple[str, float]]:
    return [(m.group(1), float(m.group(2))) for m in LORA_TAG.finditer(text)]


def set_lora_weight(text: str, index: int, weight: float) -> str:
    """Rewrite the weight of the ``index``-th tag; other text is untouched."""
    matches = list(LORA_TAG.finditer(text))
    if not 0 <= index < len(matches):
        return text
    m = matches[index]
    return text[:m.start()] + f"<lora:{m.group(1)}:{weight:g}>" + text[m.end():]


def remove_lora_tag(text: str, index: int) -> str:
    matches = list(LORA_TAG.finditer(text))
    if not 0 <= index < len(matches):
        return text
    m = matches[index]
    before, after = text[:m.start()], text[m.end():]
    if before.endswith(" ") and after.startswith(" "):
        after = after[1:]
    elif not before.strip():
        after = after.lstrip(" ")
    return (before + after).rstrip()


class LinkedSlider(QSlider):
    """A horizontal slider kept in step with a spin box (integer or decimal).

    The spin box stays the source of truth (validation, tests and the backend limits all read
    it); the slider is another way to move it. Call ``sync_range`` after the spin's range changes."""

    def __init__(self, spin: QAbstractSpinBox, scale: int = 1) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self._spin, self._scale = spin, scale
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sync_range()
        spin.valueChanged.connect(self._from_spin)
        self.valueChanged.connect(self._to_spin)
        self._from_spin(spin.value())

    def _to_slider(self, value: float) -> int:
        return round(value * self._scale)

    def sync_range(self) -> None:
        self.blockSignals(True)
        self.setRange(self._to_slider(self._spin.minimum()), self._to_slider(self._spin.maximum()))
        self.blockSignals(False)
        self._from_spin(self._spin.value())
        self.setEnabled(self._spin.isEnabled())

    def _from_spin(self, value: float) -> None:
        self.blockSignals(True)
        self.setValue(self._to_slider(value))
        self.blockSignals(False)

    def _to_spin(self, value: int) -> None:
        self._spin.setValue(value / self._scale if self._scale != 1 else value)


class LoraWeights(QWidget):
    """One row per ``<lora:…>`` tag in the prompt: name, weight slider, value and remove."""

    weight_changed = Signal(int, float)  # tag index, new weight
    removed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._names: list[str] = []
        self._rows: list[QWidget] = []
        self._sliders: list[QSlider] = []
        self._values: list[QLabel] = []
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(4)

    @property
    def names(self) -> list[str]:
        return list(self._names)

    def weights(self) -> list[float]:
        return [s.value() * LORA_STEP for s in self._sliders]

    def set_tags(self, tags: list[tuple[str, float]]) -> None:
        names = [n for n, _ in tags]
        if names != self._names:
            self._rebuild(names)
        for slider, label, (_, weight) in zip(self._sliders, self._values, tags, strict=True):
            position = round(weight / LORA_STEP)
            slider.blockSignals(True)
            slider.setValue(position)
            slider.blockSignals(False)
            label.setText(f"{weight:g}")

    def _rebuild(self, names: list[str]) -> None:
        for row in self._rows:
            self._box.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        self._names, self._sliders, self._values = list(names), [], []
        for index, name in enumerate(names):
            row = QWidget(self)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            title = QLabel(name)
            title.setObjectName("fieldLabel")
            title.setMinimumWidth(90)
            title.setMaximumWidth(140)
            title.setToolTip(name)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(round(LORA_RANGE[0] / LORA_STEP), round(LORA_RANGE[1] / LORA_STEP))
            slider.setAccessibleName(f"{name} weight")
            value = QLabel("")
            value.setObjectName("metricValue")
            value.setMinimumWidth(34)
            remove = QPushButton("✕")
            remove.setToolTip(f"Remove {name} from the prompt")
            remove.setAccessibleName(f"Remove {name}")
            remove.setFixedWidth(30)
            remove.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            slider.valueChanged.connect(
                lambda v, i=index: self.weight_changed.emit(i, round(v * LORA_STEP, 2)))
            remove.clicked.connect(lambda _c=False, i=index: self.removed.emit(i))
            for widget in (title, slider, value, remove):
                layout.addWidget(widget, 1 if widget is slider else 0)
            self._box.addWidget(row)
            row.show()
            self._rows.append(row)
            self._sliders.append(slider)
            self._values.append(value)
