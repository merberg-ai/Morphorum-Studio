"""Graph: the project's pipeline as a read-only diagram with an inspector.

The diagram is generated from the project (see ``backend/graph.py``); nothing here edits it.
The inspector lists a stage's parameters and opens the workspace that edits them.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.graph import Graph, GraphNode
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.graph_service import GraphService
from morphorum_studio.ui.tokens import DARK

NODE_W, NODE_H = 196, 76
STATE_COLOR = {"on": DARK.cyan, "off": DARK.faint, "warn": DARK.warn}


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def layout(graph: Graph, width: float, height: float) -> dict[str, QRectF]:
    """Node rectangles for a canvas of the given size: columns left to right, lanes top to bottom."""
    columns = max((n.column for n in graph.nodes), default=0) + 1
    lanes = max((n.lane for n in graph.nodes), default=0) + 1
    cell_w, cell_h = width / columns, height / lanes
    rects = {}
    for node in graph.nodes:
        cx, cy = (node.column + 0.5) * cell_w, (node.lane + 0.5) * cell_h
        w = min(NODE_W, cell_w - 24)
        rects[node.id] = QRectF(cx - w / 2, cy - NODE_H / 2, w, NODE_H)
    return rects


class GraphCanvas(QWidget):
    """Paints the nodes and arrows; click or use the arrow keys to select a stage."""

    selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.graph: Graph | None = None
        self.current: str | None = None
        self.setMinimumSize(560, 280)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Pipeline graph")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_graph(self, graph: Graph | None) -> None:
        self.graph = graph
        self.current = graph.nodes[0].id if graph and graph.nodes else None
        self._announce()
        self.update()

    def select(self, node_id: str) -> None:
        if self.graph and self.graph.node(node_id) and node_id != self.current:
            self.current = node_id
            self._announce()
            self.selected.emit(node_id)
            self.update()

    def _announce(self) -> None:
        node = self.graph.node(self.current) if self.graph and self.current else None
        self.setAccessibleDescription(f"{node.title}: {node.summary}" if node else "No project")

    def rects(self) -> dict[str, QRectF]:
        if not self.graph:
            return {}
        return layout(self.graph, max(1.0, self.width() - 20), max(1.0, self.height() - 20))

    def node_at(self, point: QPointF) -> str | None:
        shifted = point - QPointF(10, 10)
        for node_id, rect in self.rects().items():
            if rect.contains(shifted):
                return node_id
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        hit = self.node_at(event.position())
        if hit:
            self.select(hit)
        self.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self.graph or not self.current:
            return super().keyPressEvent(event)
        here = self.graph.node(self.current)
        step = {Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Left: (-1, 0),
                Qt.Key.Key_Down: (0, 1), Qt.Key.Key_Up: (0, -1)}.get(event.key())
        if step is None:
            return super().keyPressEvent(event)
        candidates = [n for n in self.graph.nodes if n is not here and (
            (step[0] and (n.column - here.column) * step[0] > 0)
            or (step[1] and n.column == here.column and (n.lane - here.lane) * step[1] > 0))]
        if candidates:
            best = min(candidates, key=lambda n: (abs(n.column - here.column),
                                                  abs(n.lane - here.lane)))
            self.select(best.id)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(DARK.base))
        if not self.graph:
            painter.setPen(QColor(DARK.dim))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Choose a project")
            return
        painter.translate(10, 10)
        rects = self.rects()
        line = QPen(QColor(DARK.faint), 1.6)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for source, target in self.graph.edges:
            a, b = rects.get(source), rects.get(target)
            if a is None or b is None:
                continue
            start, end = QPointF(a.right(), a.center().y()), QPointF(b.left(), b.center().y())
            reach = max(24.0, (end.x() - start.x()) / 2)
            path = QPainterPath(start)
            path.cubicTo(start + QPointF(reach, 0), end - QPointF(reach, 0), end)
            painter.setPen(line)
            painter.drawPath(path)
            painter.setBrush(QColor(DARK.faint))
            painter.drawPolygon([end, end + QPointF(-8, -4), end + QPointF(-8, 4)])
            painter.setBrush(Qt.BrushStyle.NoBrush)
        title_font, body_font = QFont(self.font()), QFont(self.font())
        title_font.setBold(True)
        body_font.setPointSizeF(max(7.0, body_font.pointSizeF() - 1))
        for node in self.graph.nodes:
            rect = rects[node.id]
            chosen = node.id == self.current
            accent = QColor(STATE_COLOR.get(node.state, DARK.faint))
            painter.setPen(QPen(QColor(DARK.cyan) if chosen else QColor(DARK.line2), 2 if chosen else 1))
            painter.setBrush(QColor(DARK.raised if chosen else DARK.panel))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(rect.left() + 10, rect.top() + 12, 8, 8), 4, 4)
            inner = rect.adjusted(26, 6, -8, -6)
            painter.setFont(title_font)
            painter.setPen(QColor(DARK.text if node.state != "off" else DARK.dim))
            painter.drawText(QRectF(inner.left(), rect.top() + 6, inner.width(), 20),
                             Qt.AlignmentFlag.AlignVCenter, node.title)
            painter.setFont(body_font)
            painter.setPen(QColor(DARK.dim))
            text = painter.fontMetrics().elidedText(
                node.summary, Qt.TextElideMode.ElideRight, int(rect.width() - 20))
            painter.drawText(QRectF(rect.left() + 10, rect.top() + 30, rect.width() - 20, 38),
                             Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)
        if self.hasFocus() and self.current in rects:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(DARK.cyan), 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(rects[self.current].adjusted(-4, -4, 4, 4), 12, 12)


class GraphPage(QFrame):
    open_connections = Signal()
    open_target = Signal(str, str)  # page key, project id

    def __init__(self, session: BackendSession, service: GraphService) -> None:
        super().__init__()
        self.setObjectName("pageSurface")
        self._session = session
        self._service = service
        self._graph: Graph | None = None
        self._wanted: str | None = None
        self._active = False
        self._node: GraphNode | None = None
        self._build()
        service.projects.connect(self._projects)
        service.busy_changed.connect(lambda _b: self._update())
        service.loaded.connect(self._loaded)
        service.failed.connect(self._failed)
        service.cleared.connect(self._cleared)
        session.changed.connect(self._session_changed)
        self._session_changed()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.width() < 950
        self.graph_layout.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        self.inspector.setMaximumWidth(16777215 if compact else 300)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(38, 34, 38, 24)
        outer.setSpacing(12)
        outer.addWidget(_label("GRAPH / STUDIO", "sectionCaption"))
        outer.addWidget(_label("Pipeline graph", "pageHeading"))
        self.status_line = _label("", "pageDescription", wrap=True)
        outer.addWidget(self.status_line)
        self.connect_button = QPushButton("Open connection settings")
        self.connect_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.connect_button.clicked.connect(self.open_connections)
        outer.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignLeft)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(_label("Project", "fieldLabel"))
        self.project = QComboBox()
        self.project.setMinimumWidth(240)
        self.project.setAccessibleName("Project")
        self.project.activated.connect(self._chosen)
        bar.addWidget(self.project)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.reload)
        bar.addWidget(self.refresh_button)
        bar.addStretch(1)
        self.bar = QWidget()
        self.bar.setLayout(bar)
        outer.addWidget(self.bar)

        body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.graph_layout = body
        body.setSpacing(14)
        self.canvas = GraphCanvas()
        self.canvas.selected.connect(self._show_node)
        body.addWidget(self.canvas, 1)

        self.inspector = QFrame()
        self.inspector.setObjectName("infoPanel")
        self.inspector.setMinimumWidth(220)
        self.inspector.setMaximumWidth(300)
        box = QVBoxLayout(self.inspector)
        box.setContentsMargins(18, 18, 18, 18)
        box.setSpacing(8)
        box.addWidget(_label("INSPECTOR", "sectionCaption"))
        self.node_title = _label("", "metricValue", wrap=True)
        self.node_summary = _label("", "hint", wrap=True)
        box.addWidget(self.node_title)
        box.addWidget(self.node_summary)
        self.rows_holder = QWidget()
        self.rows_box = QVBoxLayout(self.rows_holder)
        self.rows_box.setContentsMargins(0, 4, 0, 0)
        self.rows_box.setSpacing(6)
        box.addWidget(self.rows_holder)
        box.addStretch(1)
        self.open_button = QPushButton("")
        self.open_button.clicked.connect(self._open_clicked)
        box.addWidget(self.open_button)
        body.addWidget(self.inspector)
        self.body = QWidget()
        self.body.setLayout(body)
        outer.addWidget(self.body, 1)
        self._update()

    # -- public ---------------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and self._service.available and self.project.count() == 0:
            self._service.load_projects()

    def show_project(self, project_id: str) -> None:
        """Show ``project_id`` (used when a project is opened elsewhere)."""
        index = self.project.findData(project_id)
        if index >= 0:
            self.project.setCurrentIndex(index)
            self._service.load(project_id)
        else:
            self._wanted = project_id
            self._service.load_projects()

    def reload(self) -> None:
        pid = self.project.currentData()
        if pid:
            self._service.load(pid)
        self._service.load_projects()

    # -- data -----------------------------------------------------------------------------

    def _projects(self, projects) -> None:
        keep = self._wanted or self.project.currentData()
        self._wanted = None
        self.project.blockSignals(True)
        self.project.clear()
        for item in sorted(projects, key=lambda p: p.updated_at or "", reverse=True):
            self.project.addItem(item.name, item.id)
        index = self.project.findData(keep) if keep else -1
        self.project.setCurrentIndex(index if index >= 0 else (0 if self.project.count() else -1))
        self.project.blockSignals(False)
        self._update()
        pid = self.project.currentData()
        if pid and (self._graph is None or self._graph.project_id != pid):
            self._service.load(pid)

    def _chosen(self, _index: int) -> None:
        pid = self.project.currentData()
        if pid:
            self._service.load(pid)

    def _loaded(self, graph: Graph) -> None:
        if graph.project_id != self.project.currentData():
            return  # the person already picked another project
        self._graph = graph
        self.canvas.set_graph(graph)
        self._show_node(self.canvas.current)
        self._update()

    def _failed(self, _operation: str, _code: str, message: str) -> None:
        self.status_line.setText(f"Could not load: {message}")
        self.status_line.show()

    def _cleared(self) -> None:
        self._graph = None
        self.project.clear()
        self.canvas.set_graph(None)
        self._show_node(None)
        self._update()

    def _session_changed(self) -> None:
        self._update()
        if self._active and self._service.available and self.project.count() == 0:
            self._service.load_projects()

    # -- inspector ------------------------------------------------------------------------

    def _show_node(self, node_id: str | None) -> None:
        node = self._graph.node(node_id) if self._graph and node_id else None
        self._node = node
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if node is None:
            self.node_title.setText("")
            self.node_summary.setText("Select a stage to see its settings.")
            self.open_button.hide()
            return
        self.node_title.setText(node.title)
        self.node_summary.setText(node.summary)
        for name, value in node.rows:
            row = QWidget(self.rows_holder)
            layout_ = QVBoxLayout(row)
            layout_.setContentsMargins(0, 0, 0, 0)
            layout_.setSpacing(0)
            layout_.addWidget(_label(name.upper(), "sectionCaption"))
            layout_.addWidget(_label(value, "panelDescription", wrap=True))
            self.rows_box.addWidget(row)
            row.show()
        self.open_button.setVisible(bool(node.target))
        self.open_button.setText(node.target_label)

    def _open_clicked(self) -> None:
        node = self._node
        pid = self.project.currentData()
        if node and node.target and pid:
            self.open_target.emit(node.target, pid)

    # -- state ----------------------------------------------------------------------------

    def _update(self) -> None:
        connected = self._service.available
        self.connect_button.setVisible(self._session.state != "connected")
        self.bar.setVisible(connected)
        self.body.setVisible(connected)
        if self._session.state != "connected":
            self.status_line.setText("Connect to a Morphorum backend to see a project's pipeline.")
        elif not connected:
            self.status_line.setText("This backend does not offer animation projects.")
        elif self.project.count() == 0:
            self.status_line.setText("No projects yet. Create one in the Library.")
        else:
            self.status_line.setText(
                "Read-only. The diagram shows how this project is put together; "
                "use the buttons in the inspector to change a stage.")
        self.status_line.show()
        self.refresh_button.setEnabled(connected and not self._service.busy)
