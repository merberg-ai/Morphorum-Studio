"""Painted timeline lanes and a small curve plot (S4.1, read-only)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from morphorum_studio.backend.timeline import Series, Timeline, Track
from morphorum_studio.ui.tokens import DARK

LABEL_W = 176
RULER_H = 26
ROW_H = 28
HEAD_H = 22
MARGIN = 14


def _color(hex_value: str, alpha: int = 255) -> QColor:
    color = QColor(hex_value)
    color.setAlpha(alpha)
    return color


def _ticks(max_frames: int, width: float) -> list[int]:
    """Frame numbers for ruler labels, roughly 80 px apart on a 1-2-5 progression."""
    target = max(1.0, max_frames * 80.0 / max(width, 1.0))
    step = 1
    for base in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000):
        step = base
        if base >= target:
            break
    return list(range(0, max_frames, step))


class TimelineView(QWidget):
    frame_changed = Signal(int)
    track_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._timeline: Timeline | None = None
        self._rows: list[tuple[str, object]] = []  # ("head", Group) | ("track", Track)
        self._frame = 0
        self._selected: str | None = None
        self._dragging = False
        self.setMouseTracking(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(RULER_H + 40)

    # -- model --------------------------------------------------------------------------

    def set_timeline(self, timeline: Timeline | None) -> None:
        self._timeline = timeline
        self._rows = []
        self._frame = 0
        self._selected = None
        if timeline:
            for group in timeline.groups:
                tracks = timeline.in_group(group.id)
                if not tracks:
                    continue
                self._rows.append(("head", group))
                self._rows.extend(("track", t) for t in tracks)
        height = RULER_H + sum(HEAD_H if kind == "head" else ROW_H for kind, _ in self._rows) + 8
        self.setFixedHeight(max(height, RULER_H + 40))
        self.update()

    def set_timeline_keep_frame(self, timeline: Timeline) -> None:
        """Replace the lanes after an edit, keeping the playhead and the selected track."""
        frame, selected = self._frame, self._selected
        self.set_timeline(timeline)
        self._frame = min(frame, timeline.max_frames - 1)
        self._selected = selected if selected and timeline.track(selected) else None
        self.update()

    def set_frame(self, frame: int) -> None:
        if self._timeline:
            frame = max(0, min(frame, self._timeline.max_frames - 1))
        if frame != self._frame:
            self._frame = frame
            self.update()

    @property
    def frame(self) -> int:
        return self._frame

    def select(self, track_id: str | None) -> None:
        if track_id != self._selected:
            self._selected = track_id
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, self.height())

    # -- geometry -----------------------------------------------------------------------

    def _x(self, frame: float) -> float:
        timeline = self._timeline
        span = max(1, (timeline.max_frames - 1) if timeline else 1)
        return LABEL_W + (self.width() - LABEL_W - MARGIN) * frame / span

    def _frame_at(self, x: float) -> int:
        timeline = self._timeline
        if not timeline:
            return 0
        span = max(1, timeline.max_frames - 1)
        return round(max(0.0, min(1.0, (x - LABEL_W) / max(1, self.width() - LABEL_W - MARGIN))) * span)

    def _row_at(self, y: float):
        top = RULER_H
        for kind, item in self._rows:
            height = HEAD_H if kind == "head" else ROW_H
            if top <= y < top + height:
                return kind, item
            top += height
        return None

    # -- painting -----------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _color(DARK.base))
        timeline = self._timeline
        font = QFont(DARK.font_ui)
        font.setPixelSize(12)
        painter.setFont(font)
        if timeline is None:
            painter.setPen(_color(DARK.faint))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No project loaded")
            return
        mono = QFont(DARK.font_mono)
        mono.setPixelSize(10)
        line, grid = _color(DARK.line2), _color(DARK.line)
        # ruler
        painter.setPen(_color(DARK.faint))
        painter.setFont(mono)
        for frame in _ticks(timeline.max_frames, self.width() - LABEL_W - MARGIN):
            x = self._x(frame)
            painter.setPen(grid)
            painter.drawLine(QPointF(x, RULER_H - 6), QPointF(x, self.height()))
            painter.setPen(_color(DARK.faint))
            painter.drawText(QPointF(x + 3, RULER_H - 10), str(frame))
        painter.setPen(line)
        painter.drawLine(0, RULER_H, self.width(), RULER_H)
        top = RULER_H
        for kind, item in self._rows:
            if kind == "head":
                rect = QRectF(0, top, self.width(), HEAD_H)
                painter.fillRect(rect, _color(DARK.panel))
                painter.setFont(font)
                painter.setPen(_color(DARK.dim))
                painter.drawText(QRectF(10, top, LABEL_W - 10, HEAD_H),
                                 Qt.AlignmentFlag.AlignVCenter, item.label.upper())
                top += HEAD_H
                continue
            track: Track = item  # type: ignore[assignment]
            rect = QRectF(0, top, self.width(), ROW_H)
            if track.id == self._selected:
                painter.fillRect(rect, _color(DARK.cyan, 28))
            painter.setFont(font)
            painter.setPen(_color(DARK.text if track.keyframes else DARK.faint))
            unit = f" ({track.unit})" if track.unit else ""
            painter.drawText(QRectF(18, top, LABEL_W - 22, ROW_H), Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(track.label + unit, Qt.TextElideMode.ElideRight,
                                                              LABEL_W - 24))
            painter.setPen(grid)
            painter.drawLine(LABEL_W, int(top + ROW_H / 2), self.width() - MARGIN, int(top + ROW_H / 2))
            for key in track.keyframes:
                if key.frame >= timeline.max_frames:
                    continue
                self._diamond(painter, self._x(key.frame), top + ROW_H / 2,
                              DARK.cyan if key.number is not None or track.kind == "prompt" else DARK.violet)
            top += ROW_H
        # playhead
        x = self._x(self._frame)
        painter.setPen(QPen(_color(DARK.warn), 1.5))
        painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        painter.setBrush(_color(DARK.warn))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, 8)]))

    @staticmethod
    def _diamond(painter: QPainter, x: float, y: float, color: str) -> None:
        painter.setPen(QPen(_color(DARK.void), 1))
        painter.setBrush(_color(color))
        painter.drawPolygon(QPolygonF([QPointF(x, y - 6), QPointF(x + 5, y), QPointF(x, y + 6),
                                       QPointF(x - 5, y)]))

    # -- input --------------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._timeline is None:
            return
        pos = event.position()
        row = self._row_at(pos.y())
        if row and row[0] == "track":
            self.select(row[1].id)
            self.track_selected.emit(row[1].id)
        if pos.x() >= LABEL_W or pos.y() < RULER_H:
            self._dragging = True
            self._scrub(pos.x())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._scrub(event.position().x())

    def mouseReleaseEvent(self, _event) -> None:
        self._dragging = False

    def keyPressEvent(self, event) -> None:
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(Qt.Key(event.key()))
        if step is None or self._timeline is None:
            super().keyPressEvent(event)
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step *= 10
        self._set_and_emit(self._frame + step)

    def _scrub(self, x: float) -> None:
        self._set_and_emit(self._frame_at(x))

    def _set_and_emit(self, frame: int) -> None:
        before = self._frame
        self.set_frame(frame)
        if self._frame != before:
            self.frame_changed.emit(self._frame)


class CurveView(QWidget):
    """The backend's sampled curve for one numeric track, with keyframes and the playhead."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(140)
        self._series: Series | None = None
        self._keys: tuple = ()
        self._max_frames = 1
        self._frame = 0
        self._message = "Select a numeric track"

    def show_message(self, text: str) -> None:
        self._series, self._keys, self._message = None, (), text
        self.update()

    def show_series(self, series: Series, keys, max_frames: int) -> None:
        self._series, self._keys, self._max_frames, self._message = series, tuple(keys), max_frames, ""
        self.update()

    def set_frame(self, frame: int) -> None:
        self._frame = frame
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _color(DARK.void))
        painter.setPen(_color(DARK.faint))
        series = self._series
        if series is None or len(series.samples) < 2:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message or "No data")
            return
        pad_l, pad_r, pad_t, pad_b = 46, 12, 10, 18
        w, h = self.width() - pad_l - pad_r, self.height() - pad_t - pad_b
        values = [v for _, v in series.samples]
        low, high = min(values), max(values)
        if high - low < 1e-9:
            low, high = low - 1, high + 1
        span = max(1, self._max_frames - 1)

        def px(frame: float) -> float:
            return pad_l + w * frame / span

        def py(value: float) -> float:
            return pad_t + h * (1 - (value - low) / (high - low))

        painter.setPen(_color(DARK.line))
        for value in (low, (low + high) / 2, high):
            painter.drawLine(QPointF(pad_l, py(value)), QPointF(pad_l + w, py(value)))
            painter.setPen(_color(DARK.faint))
            painter.drawText(QRectF(0, py(value) - 8, pad_l - 6, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{value:.3g}")
            painter.setPen(_color(DARK.line))
        painter.setPen(QPen(_color(DARK.cyan), 1.6))
        painter.drawPolyline(QPolygonF([QPointF(px(f), py(v)) for f, v in series.samples]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(DARK.violet))
        for key in self._keys:
            if key.number is not None:
                painter.drawEllipse(QPointF(px(key.frame), py(key.number)), 3.5, 3.5)
        painter.setPen(QPen(_color(DARK.warn), 1.2))
        painter.drawLine(QPointF(px(self._frame), pad_t), QPointF(px(self._frame), pad_t + h))
