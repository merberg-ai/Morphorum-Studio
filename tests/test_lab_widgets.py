"""Lab controls: LoRA tag editing, linked sliders (offscreen Qt, CI only)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSpinBox, QWidget

from morphorum_studio.ui.lab_widgets import (
    LinkedSlider,
    LoraWeights,
    parse_lora_tags,
    remove_lora_tag,
    set_lora_weight,
)

app = QApplication.instance() or QApplication([])


def test_parse_and_rewrite_tags():
    text = "a cat <lora:Ink Style:0.65> in <lora:Glow:-0.5> rain"
    assert parse_lora_tags(text) == [("Ink Style", 0.65), ("Glow", -0.5)]
    assert set_lora_weight(text, 1, 1.25) == "a cat <lora:Ink Style:0.65> in <lora:Glow:1.25> rain"
    assert set_lora_weight(text, 5, 1.0) == text and parse_lora_tags("no tags") == []


def test_remove_tag_tidies_spaces():
    assert remove_lora_tag("a cat <lora:A:1> in rain", 0) == "a cat in rain"
    assert remove_lora_tag("<lora:A:1> a cat", 0) == "a cat"
    assert remove_lora_tag("a cat <lora:A:1>", 0) == "a cat"
    assert remove_lora_tag("a cat", 0) == "a cat"


def test_linked_slider_follows_spin_both_ways():
    host = QWidget()
    spin = QSpinBox(host)
    spin.setRange(1, 100)
    spin.setValue(25)
    slider = LinkedSlider(spin)
    slider.setParent(host)
    assert (slider.minimum(), slider.maximum(), slider.value()) == (1, 100, 25)
    slider.setValue(40)
    assert spin.value() == 40
    spin.setValue(10)
    assert slider.value() == 10
    spin.setRange(1, 50)
    slider.sync_range()
    assert slider.maximum() == 50


def test_linked_slider_scaled_decimals():
    host = QWidget()
    spin = QDoubleSpinBox(host)
    spin.setRange(0.0, 10.0)
    spin.setValue(6.0)
    slider = LinkedSlider(spin, scale=20)
    slider.setParent(host)
    assert slider.value() == 120
    slider.setValue(130)
    assert spin.value() == 6.5
    spin.setEnabled(False)
    slider.sync_range()
    assert not slider.isEnabled()


def test_lora_rows_follow_tags_and_emit():
    host = QWidget()
    rows = LoraWeights()
    rows.setParent(host)
    got = []
    rows.weight_changed.connect(lambda i, w: got.append((i, w)))
    removed = []
    rows.removed.connect(removed.append)
    rows.set_tags([("A", 0.5), ("B", 1.0)])
    assert rows.names == ["A", "B"] and rows.weights() == [0.5, 1.0]
    rows.set_tags([("A", 0.75), ("B", 1.0)])  # same names: values move, no rebuild signals
    assert rows.weights()[0] == 0.75 and got == []
    rows._sliders[1].setValue(30)  # 1.5
    assert got == [(1, 1.5)]
    rows.set_tags([])
    assert rows.names == []
