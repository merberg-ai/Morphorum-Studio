"""Window chrome: custom title bar, icon rail and the shared brand mark."""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.ui import icons
from morphorum_studio.ui.tokens import DARK, Tokens

TITLE_BAR_HEIGHT = 40
RAIL_WIDTH = 64


def asset_path(*parts: str):
    return files("morphorum_studio").joinpath("assets", *parts)


class BrandMark(QWidget):
    """The Morphorum monitor-and-skull mark (transparent PNG, drawn smoothly scaled)."""

    def __init__(self, width: int = 26, height: int = 28) -> None:
        super().__init__()
        self.setFixedSize(width, height)
        self._pixmap = QPixmap(str(asset_path("logo-mark.png")))

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        side = min(self.width(), self.height())
        target = QRectF(
            (self.width() - side) / 2, (self.height() - side) / 2, side, side
        )
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))


class ConnectionPill(QPushButton):
    """Backend connection status in the title bar; clicking opens Settings → Backend connection."""

    STATES = ("offline", "connected", "busy", "error")

    def __init__(self, tokens: Tokens = DARK) -> None:
        super().__init__("BACKEND OFFLINE")
        self.setObjectName("connectionPill")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Open backend connections")
        self.setFixedHeight(24)
        self._tokens = tokens
        self._dot = {
            "offline": tokens.faint,
            "connected": tokens.ok,
            "busy": tokens.warn,
            "error": tokens.bad,
        }
        self.set_status("BACKEND OFFLINE")

    @staticmethod
    def state_for(text: str) -> str:
        label = text.upper()
        if label.endswith("CONNECTED") and "DIS" not in label:
            return "connected"
        if "CONNECTING" in label or "RECONNECTING" in label:
            return "busy"
        if any(word in label for word in ("UNAUTHORIZED", "INCOMPATIBLE", "MISMATCH")):
            return "error"
        return "offline"

    def set_status(self, text: str) -> None:
        state = self.state_for(text)
        self.setText(text)
        self.setProperty("state", state)
        self.setIcon(_dot_icon(self._dot[state]))
        self.setIconSize(QSize(8, 8))
        self.style().unpolish(self)
        self.style().polish(self)


def _dot_icon(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(4, 4, 8, 8)
    painter.end()
    return QIcon(pixmap)


class TitleBar(QWidget):
    """Brand, menus, connection pill and window controls; drags and double-clicks like a native bar."""

    def __init__(self, window: QWidget, tokens: Tokens = DARK) -> None:
        super().__init__()
        self._window = window
        self._tokens = tokens
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TITLE_BAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(0)

        brand = QHBoxLayout()
        brand.setSpacing(9)
        brand.addWidget(BrandMark())
        name = QLabel("Morphorum")
        name.setObjectName("brandName")
        sub = QLabel("STUDIO")
        sub.setObjectName("brandSub")
        brand.addWidget(name)
        brand.addWidget(sub)
        layout.addLayout(brand)
        layout.addSpacing(22)

        self.menus_layout = QHBoxLayout()
        self.menus_layout.setSpacing(2)
        layout.addLayout(self.menus_layout)
        layout.addStretch(1)

        self.connection_pill = ConnectionPill(tokens)
        layout.addWidget(self.connection_pill)
        layout.addSpacing(10)

        self.minimize_button = self._window_button("win-min", "Minimize", "winButton")
        self.maximize_button = self._window_button("win-max", "Maximize", "winButton")
        self.close_button = self._window_button("win-close", "Close", "winClose")
        self.minimize_button.clicked.connect(self._window.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximized)
        self.close_button.clicked.connect(self._window.close)
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            layout.addWidget(button)

    def _window_button(self, name: str, tip: str, object_name: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName(object_name)
        button.setFixedSize(46, TITLE_BAR_HEIGHT)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t = self._tokens
        button.setIcon(
            icons.icon(name, t.dim, hover="#ffffff" if object_name == "winClose" else t.text, size=12)
        )
        button.setIconSize(QSize(12, 12))
        return button

    def add_menu(self, title: str, actions: list[QAction | None]) -> QMenu:
        """Add a menu button; ``None`` entries become separators."""
        button = QToolButton()
        button.setObjectName("menuButton")
        button.setText(title)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        menu = QMenu(title, button)
        for action in actions:
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)
        button.setMenu(menu)
        self.menus_layout.addWidget(button)
        return menu

    def toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def sync_window_state(self) -> None:
        maximized = self._window.isMaximized()
        t = self._tokens
        self.maximize_button.setIcon(
            icons.icon("win-restore" if maximized else "win-max", t.dim, hover=t.text, size=12)
        )
        tip = "Restore" if maximized else "Maximize"
        self.maximize_button.setToolTip(tip)
        self.maximize_button.setAccessibleName(tip)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class NavRail(QFrame):
    """Vertical icon rail. Mirrors the small slice of QListWidget the shell relies on."""

    currentRowChanged = Signal(int)  # noqa: N815 (Qt-style name kept for compatibility)

    def __init__(
        self,
        items: list[tuple[str, str, str]],
        footer_from: int | None = None,
        tokens: Tokens = DARK,
    ) -> None:
        """``items``: (full name, short label, icon name). Items from ``footer_from`` sit at the bottom."""
        super().__init__()
        self.setObjectName("rail")
        self.setFixedWidth(RAIL_WIDTH)
        self._tokens = tokens
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QToolButton] = []
        self._current = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 10, 6, 10)
        layout.setSpacing(4)

        for index, (full, short, icon_name) in enumerate(items):
            if footer_from is not None and index == footer_from:
                layout.addStretch(1)
            button = QToolButton()
            button.setObjectName("railItem")
            button.setCheckable(True)
            button.setText(short)
            button.setToolTip(full)
            button.setAccessibleName(full)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIcon(icons.icon(icon_name, tokens.faint, checked=tokens.cyan, hover=tokens.dim))
            button.setIconSize(QSize(20, 20))
            button.setFixedSize(52, 54)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._group.addButton(button, index)
            self._buttons.append(button)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        if footer_from is None:
            layout.addStretch(1)
        self._group.idToggled.connect(self._on_toggled)

    def count(self) -> int:
        return len(self._buttons)

    def currentRow(self) -> int:  # noqa: N802
        return self._current

    def setCurrentRow(self, row: int) -> None:  # noqa: N802
        if 0 <= row < len(self._buttons):
            self._buttons[row].setChecked(True)

    def _on_toggled(self, index: int, checked: bool) -> None:
        if checked:
            self._current = index
            self.update()
            self.currentRowChanged.emit(index)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not 0 <= self._current < len(self._buttons):
            return
        # Glowing accent bar on the active item's left edge.
        geometry = self._buttons[self._current].geometry()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = geometry.top() + 12
        bottom = geometry.bottom() - 12
        gradient = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
        gradient.setColorAt(0, QColor(self._tokens.grad_a))
        gradient.setColorAt(1, QColor(self._tokens.grad_c))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(0, top, 3, bottom - top), 1.5, 1.5)
