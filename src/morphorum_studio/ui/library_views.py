"""Library workspace views: a responsive project grid and read-only model / LoRA grids."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.schema import ModelEntry
from morphorum_studio.ui.home_page import NA, ProjectTile, format_bytes
from morphorum_studio.ui.recent_service import RecentProject
from morphorum_studio.ui.tokens import DARK, Tokens

MIN_TILE_WIDTH = 270
MAX_COLUMNS = 5


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def columns_for(width: int, min_tile: int = MIN_TILE_WIDTH, spacing: int = 14) -> int:
    """How many tiles of at least ``min_tile`` fit across ``width``."""
    return max(1, min(MAX_COLUMNS, (max(width, 0) + spacing) // (min_tile + spacing)))


class FlowGrid(QScrollArea):
    """Scrolling grid that re-flows its widgets to the available width."""

    def __init__(self, min_tile: int = MIN_TILE_WIDTH) -> None:
        super().__init__()
        self.setObjectName("connectionsScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._min_tile = min_tile
        self._widgets: list[QWidget] = []
        content = QWidget()
        content.setObjectName("connectionsContent")
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 8, 0)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addLayout(self._grid)
        outer.addStretch(1)
        self.setWidget(content)
        self._columns = 0

    @property
    def widgets(self) -> list[QWidget]:
        return list(self._widgets)

    def set_widgets(self, widgets: list[QWidget]) -> None:
        for widget in self._widgets:
            self._grid.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._widgets = list(widgets)
        self._columns = 0
        self._reflow()

    def columns(self) -> int:
        return self._columns

    def _reflow(self) -> None:
        columns = columns_for(self.viewport().width(), self._min_tile)
        if columns == self._columns and self._grid.count() == len(self._widgets):
            return
        self._columns = columns
        for widget in self._widgets:
            self._grid.removeWidget(widget)
        for column in range(MAX_COLUMNS):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, widget in enumerate(self._widgets):
            self._grid.addWidget(widget, index // columns, index % columns)
            widget.show()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reflow()


class ProjectGrid(QWidget):
    """Every project as a tile: thumbnail from its latest frame, size line and status chip."""

    opened = Signal(str)  # project id

    def __init__(self, tokens: Tokens = DARK) -> None:
        super().__init__()
        self._tokens = tokens
        self._items: tuple[RecentProject, ...] = ()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        self.note = _label("", "hint", wrap=True)
        box.addWidget(self.note)
        self.flow = FlowGrid()
        box.addWidget(self.flow, 1)

    @property
    def tiles(self) -> list[ProjectTile]:
        return [w for w in self.flow.widgets if isinstance(w, ProjectTile)]

    def set_items(self, items: tuple[RecentProject, ...], needle: str = "") -> None:
        self._items = items
        self.apply_filter(needle)

    def apply_filter(self, needle: str) -> None:
        text = needle.strip().lower()
        shown = [i for i in self._items
                 if not text or text in i.summary.name.lower() or text in i.summary.id]
        tiles = []
        for item in shown:
            tile = ProjectTile(item, self._tokens)
            tile.clicked.connect(self.opened)
            tiles.append(tile)
        self.flow.set_widgets(tiles)
        if not self._items:
            self.note.setText("No projects on this backend yet. Use New project to create one.")
        elif not shown:
            self.note.setText("No project matches the search.")
        else:
            self.note.setText("")
        self.note.setVisible(bool(self.note.text()))

    def show_message(self, text: str) -> None:
        self._items = ()
        self.flow.set_widgets([])
        self.note.setText(text)
        self.note.setVisible(bool(text))


class ModelCard(QFrame):
    clicked = Signal(str)  # model id

    def __init__(self, entry: ModelEntry, clickable: bool) -> None:
        super().__init__()
        self.setObjectName("tile")
        self.model_id = entry.id
        self._clickable = clickable
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 14)
        box.setSpacing(6)
        self.name = _label(entry.name, "cardTitle", wrap=True)
        box.addWidget(self.name)
        row = QHBoxLayout()
        row.setSpacing(8)
        chip = _label(entry.family, "chip")
        chip.setProperty("state", "idle")
        row.addWidget(chip)
        if entry.variant:
            variant = _label(entry.variant, "chip")
            variant.setProperty("state", "idle")
            row.addWidget(variant)
        row.addStretch(1)
        box.addLayout(row)
        self.meta = _label(NA if entry.size_bytes is None else format_bytes(entry.size_bytes), "hint")
        box.addWidget(self.meta)
        self.setToolTip(entry.filename or entry.name)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setAccessibleName(f"Inspect {entry.name}")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.model_id)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._clickable and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.model_id)
            return
        super().keyPressEvent(event)


class ModelGrid(QWidget):
    """Read-only grid of indexed checkpoints or LoRAs with a family filter and search."""

    inspect_requested = Signal(str)  # model id (LoRAs only)

    def __init__(self, kind_label: str, inspectable: bool) -> None:
        super().__init__()
        self._entries: tuple[ModelEntry, ...] = ()
        self._inspectable = inspectable
        self._kind_label = kind_label
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.family = QComboBox()
        self.family.setAccessibleName(f"{kind_label} family")
        self.family.setMinimumWidth(170)
        self.family.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.family.addItem("All families", None)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {kind_label.lower()}")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(f"Search {kind_label.lower()}")
        bar.addWidget(self.family)
        bar.addWidget(self.search, 1)
        box.addLayout(bar)
        self.note = _label("", "hint", wrap=True)
        box.addWidget(self.note)
        self.flow = FlowGrid(min_tile=240)
        box.addWidget(self.flow, 1)
        self.family.currentIndexChanged.connect(lambda _i: self._fill())
        self.search.textChanged.connect(lambda _t: self._fill())

    @property
    def cards(self) -> list[ModelCard]:
        return [w for w in self.flow.widgets if isinstance(w, ModelCard)]

    def set_entries(self, entries: tuple[ModelEntry, ...]) -> None:
        self._entries = entries
        families = sorted({e.family for e in entries if e.family})
        current = self.family.currentData()
        self.family.blockSignals(True)
        self.family.clear()
        self.family.addItem("All families", None)
        for family in families:
            self.family.addItem(family, family)
        self.family.setCurrentIndex(max(0, self.family.findData(current)))
        self.family.blockSignals(False)
        self._fill()

    def show_message(self, text: str) -> None:
        self._entries = ()
        self.flow.set_widgets([])
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _fill(self) -> None:
        family, text = self.family.currentData(), self.search.text().strip().lower()
        cards = []
        for entry in self._entries:
            if (family and entry.family != family) or (text and text not in entry.name.lower()):
                continue
            card = ModelCard(entry, self._inspectable)
            card.clicked.connect(self.inspect_requested)
            cards.append(card)
        self.flow.set_widgets(cards)
        if not self._entries:
            self.note.setText(f"No {self._kind_label.lower()} are indexed on this backend. Add files to "
                              "its model folders, then Refresh.")
        elif not cards:
            self.note.setText(f"No {self._kind_label.lower()} match.")
        else:
            suffix = " Select one to inspect it." if self._inspectable else ""
            self.note.setText(f"{len(cards)} of {len(self._entries)} shown.{suffix}")
        self.note.setVisible(True)
