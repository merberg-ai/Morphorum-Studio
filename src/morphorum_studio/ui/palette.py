"""Ctrl+K command palette: type to filter, Up/Down to move, Enter to run, Esc to close."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class Command:
    title: str
    hint: str  # shortcut or group, shown dimmed on the right
    run: Callable[[], None]
    keywords: str = ""


def filter_commands(commands: Sequence[Command], query: str) -> list[Command]:
    """Every whitespace-separated word must appear in the title or keywords.

    Title-prefix matches rank first, then title matches, then keyword-only matches; ties keep
    the original order, so an empty query lists everything as declared."""
    words = query.lower().split()
    if not words:
        return list(commands)
    scored: list[tuple[int, int, Command]] = []
    for index, command in enumerate(commands):
        title = command.title.lower()
        haystack = f"{title} {command.keywords.lower()}"
        if not all(word in haystack for word in words):
            continue
        if title.startswith(words[0]):
            rank = 0
        elif all(word in title for word in words):
            rank = 1
        else:
            rank = 2
        scored.append((rank, index, command))
    scored.sort(key=lambda item: item[:2])
    return [command for _, _, command in scored]


class CommandPalette(QDialog):
    def __init__(self, commands: Sequence[Command], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("palette")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setFixedWidth(520)
        self._commands = list(commands)
        self._shown: list[Command] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command or workspace…")
        self.input.setAccessibleName("Command search")
        self.input.setClearButtonEnabled(True)
        layout.addWidget(self.input)
        self.results = QListWidget()
        self.results.setObjectName("paletteResults")
        self.results.setAccessibleName("Matching commands")
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results.setMinimumHeight(220)
        layout.addWidget(self.results)
        self.empty = QLabel("No matching command")
        self.empty.setObjectName("panelDescription")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)

        self.input.textChanged.connect(self._refilter)
        self.results.itemActivated.connect(lambda _item: self.run_selected())
        self.results.itemClicked.connect(lambda _item: self.run_selected())
        self.input.installEventFilter(self)
        self._refilter("")

    # -- behaviour -----------------------------------------------------------------------

    def _refilter(self, text: str) -> None:
        self._shown = filter_commands(self._commands, text)
        self.results.clear()
        for command in self._shown:
            item = QListWidgetItem(f"{command.title}      {command.hint}" if command.hint
                                   else command.title)
            self.results.addItem(item)
        self.empty.setVisible(not self._shown)
        self.results.setVisible(bool(self._shown))
        if self._shown:
            self.results.setCurrentRow(0)

    def visible_titles(self) -> list[str]:
        return [command.title for command in self._shown]

    def step_selection(self, step: int) -> None:
        if not self._shown:
            return
        row = (self.results.currentRow() + step) % len(self._shown)
        self.results.setCurrentRow(row)

    def run_selected(self) -> None:
        row = self.results.currentRow()
        if not 0 <= row < len(self._shown):
            return
        command = self._shown[row]
        self.accept()  # Close first so the command acts on the window, not on this dialog.
        command.run()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.input and event.type() == event.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                self.step_selection(1)
                return True
            if key == Qt.Key.Key_Up:
                self.step_selection(-1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.run_selected()
                return True
        return super().eventFilter(obj, event)

    def open_centered(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            top = parent.mapToGlobal(parent.rect().topLeft())
            self.move(top.x() + (parent.width() - self.width()) // 2, top.y() + 90)
        self.input.clear()
        self.input.setFocus()
        self.exec()
