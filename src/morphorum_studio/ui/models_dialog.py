"""Model and LoRA browser (S4.4): what the backend has indexed, and what a LoRA contains.

Read-only. LoRAs are inspected by indexed id; nothing is looked up online or written back.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.loras import LoraDetail
from morphorum_studio.ui.assets_card import format_bytes
from morphorum_studio.ui.setup_service import ModelsService


def describe_lora(detail: LoraDetail) -> str:
    lines = [detail.name, ""]
    rows = (("Family", detail.family), ("Format", detail.adapter_format),
            ("Base model", detail.base_model),
            ("Tensors", None if detail.tensor_count is None else str(detail.tensor_count)),
            ("Ranks", ", ".join(detail.ranks) or None),
            ("Parts", ", ".join(f"{k} {n}" for k, n in detail.components) or None))
    lines += [f"{label}: {value}" for label, value in rows if value]
    if detail.trigger_words:
        source = f" (from {detail.trigger_source})" if detail.trigger_source else ""
        lines += ["", f"Trigger words{source}:", ", ".join(detail.trigger_words)]
    else:
        lines += ["", "No trigger words recorded."]
    lines += ["", *(f"⚠ {w}" for w in detail.warnings), *(f"✖ {e}" for e in detail.errors)]
    return "\n".join(lines).strip()


class ModelsDialog(QDialog):
    def __init__(self, service: ModelsService, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Models and LoRAs")
        self.resize(820, 560)
        self._service = service
        self._checkpoints: tuple = ()
        self._loras: tuple = ()
        box = QVBoxLayout(self)
        self.note = QLabel("Loading what the backend has indexed…")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        self.tabs = QTabWidget()
        box.addWidget(self.tabs, 1)

        self.checkpoint_list = QListWidget()
        self.tabs.addTab(self.checkpoint_list, "Checkpoints")

        lora_tab = QWidget()
        lbox = QVBoxLayout(lora_tab)
        filters = QHBoxLayout()
        self.family = QComboBox()
        self.family.addItem("All families", None)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search LoRAs")
        filters.addWidget(self.family)
        filters.addWidget(self.search, 1)
        lbox.addLayout(filters)
        split = QHBoxLayout()
        self.lora_list = QListWidget()
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a LoRA to inspect it.")
        split.addWidget(self.lora_list, 1)
        split.addWidget(self.detail, 1)
        lbox.addLayout(split, 1)
        self.tabs.addTab(lora_tab, "LoRAs")

        row = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.close_button = QPushButton("Close")
        row.addWidget(self.refresh_button)
        row.addStretch(1)
        row.addWidget(self.close_button)
        box.addLayout(row)

        self.family.currentIndexChanged.connect(lambda _i: self._fill_loras())
        self.search.textChanged.connect(lambda _t: self._fill_loras())
        self.lora_list.currentItemChanged.connect(self._selected)
        self.refresh_button.clicked.connect(service.load)
        self.close_button.clicked.connect(self.close)
        service.library_ready.connect(self._ready)
        service.inspected.connect(self._inspected)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(self._cleared)
        service.load()
        self._update()

    def _update(self) -> None:
        self.refresh_button.setEnabled(self._service.available and not self._service.busy)

    def _ready(self, checkpoints, loras) -> None:
        self._checkpoints, self._loras = checkpoints, loras
        self.checkpoint_list.clear()
        for entry in checkpoints:
            size = f" · {format_bytes(entry.size_bytes)}" if entry.size_bytes else ""
            self.checkpoint_list.addItem(f"{entry.name}  ({entry.family}{size})")
        families = sorted({e.family for e in loras if e.family})
        current = self.family.currentData()
        self.family.blockSignals(True)
        self.family.clear()
        self.family.addItem("All families", None)
        for family in families:
            self.family.addItem(family, family)
        self.family.setCurrentIndex(max(0, self.family.findData(current)))
        self.family.blockSignals(False)
        self.note.setText(f"{len(checkpoints)} checkpoint(s) and {len(loras)} LoRA(s) indexed. "
                          "Add files in the backend's model folders, then Refresh.")
        self._fill_loras()
        self._update()

    def _fill_loras(self) -> None:
        family, text = self.family.currentData(), self.search.text().strip().lower()
        self.lora_list.clear()
        for entry in self._loras:
            if (family and entry.family != family) or (text and text not in entry.name.lower()):
                continue
            item = QListWidgetItem(f"{entry.name}  ({entry.family})")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self.lora_list.addItem(item)

    def _selected(self, item, _previous=None) -> None:
        if item is not None:
            self.detail.setPlainText("Inspecting…")
            self._service.inspect(item.data(Qt.ItemDataRole.UserRole))

    def _inspected(self, detail: LoraDetail) -> None:
        item = self.lora_list.currentItem()
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == detail.id:
            self.detail.setPlainText(describe_lora(detail))

    def _failed(self, operation: str, code: str, message: str) -> None:
        text = f"{operation.capitalize()} failed: {message}"
        if operation == "inspect":
            self.detail.setPlainText(text)
        else:
            self.note.setText(text)
        self._update()

    def _cleared(self) -> None:
        self.note.setText("The connection changed. Use Refresh to reload the model list.")
        self.checkpoint_list.clear()
        self.lora_list.clear()
        self.detail.clear()
        self._update()
