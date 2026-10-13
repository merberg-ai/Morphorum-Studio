"""Edge and corner resizing for a frameless top-level window.

A frameless window has no native border to grab. Instead of reimplementing
resizing, this asks the window system to do it (``startSystemResize``), which
keeps native cursors, snapping and multi-monitor behaviour. Dragging by the
title bar uses ``startSystemMove`` the same way (see ``TitleBar``).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QWidget

EDGE_MARGIN = 6

_CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
}


def edges_at(rect: QRect, point: QPoint, margin: int = EDGE_MARGIN) -> Qt.Edge:
    """Which window edges (possibly none) a point lies within ``margin`` of."""
    if not rect.contains(point):
        return Qt.Edge(0)
    edges = Qt.Edge(0)
    if point.x() - rect.left() < margin:
        edges |= Qt.Edge.LeftEdge
    elif rect.right() - point.x() < margin:
        edges |= Qt.Edge.RightEdge
    if point.y() - rect.top() < margin:
        edges |= Qt.Edge.TopEdge
    elif rect.bottom() - point.y() < margin:
        edges |= Qt.Edge.BottomEdge
    return edges


class EdgeResizer(QObject):
    """Application-wide event filter that resizes ``window`` from its edges."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._cursor_set = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _active(self) -> bool:
        w = self._window
        return w.isVisible() and not (w.isMaximized() or w.isFullScreen())

    def _clear_cursor(self) -> None:
        if self._cursor_set:
            self._window.unsetCursor()
            self._cursor_set = False

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        kind = event.type()
        if kind not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self._window:
            return False
        if not self._active():
            self._clear_cursor()
            return False
        edges = edges_at(self._window.frameGeometry(), event.globalPosition().toPoint())
        if kind == QEvent.Type.MouseMove:
            if edges:
                self._window.setCursor(_CURSORS.get(edges, Qt.CursorShape.ArrowCursor))
                self._cursor_set = True
            else:
                self._clear_cursor()
            return False
        # Left button pressed on an edge: hand the gesture to the window system.
        if edges and event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemResize(edges):
                return True
        return False


def enable_mouse_tracking(root: QWidget) -> None:
    """Child widgets only report hover moves (needed for edge cursors) when tracking is on."""
    root.setMouseTracking(True)
    for child in root.findChildren(QWidget):
        child.setMouseTracking(True)
