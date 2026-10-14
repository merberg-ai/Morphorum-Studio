"""Home dashboard: live backend, GPU and system metrics plus the model inventory (S2.1).

Everything shown comes from the backend. A value the backend did not report is shown as
"—" with an explanation, never as zero, and no control claims to load or run a model.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.schema import GpuDevice, Telemetry
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.dashboard_service import DashboardService, ModelCatalog
from morphorum_studio.ui.recent_service import RecentProject, RecentProjectsService, status_chip
from morphorum_studio.ui.tokens import DARK, Tokens

NA = "—"
HISTORY = 60


# ----------------------------------------------------------------------------- formatting

def format_bytes(value: float | None) -> str:
    if value is None:
        return NA
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return NA  # pragma: no cover


def format_mib(value: float | None) -> str:
    return NA if value is None else format_bytes(value * 1024 * 1024)


def format_percent(value: float | None) -> str:
    return NA if value is None else f"{value:.0f}%"


def vram_text(device: GpuDevice) -> str:
    if device.memory_used_mib is None or device.memory_total_mib is None:
        return NA
    return f"{format_mib(device.memory_used_mib)} / {format_mib(device.memory_total_mib)}"


# ----------------------------------------------------------------------------- widgets

class MeterBar(QWidget):
    """A thin gradient meter. ``None`` draws an empty track, not a zero-length bar."""

    def __init__(self, tokens: Tokens = DARK) -> None:
        super().__init__()
        self._tokens = tokens
        self._fraction: float | None = None
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @property
    def fraction(self) -> float | None:
        return self._fraction

    def set_fraction(self, fraction: float | None) -> None:
        self._fraction = None if fraction is None else min(1.0, max(0.0, fraction))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.raised))
        painter.drawRoundedRect(rect, 4, 4)
        if self._fraction:
            fill = QRectF(rect.left(), rect.top(), max(8.0, rect.width() * self._fraction), rect.height())
            if self._fraction >= 0.9:
                painter.setBrush(QColor(t.warn if self._fraction < 0.97 else t.bad))
            else:
                gradient = QLinearGradient(rect.topLeft(), rect.topRight())
                gradient.setColorAt(0, QColor(t.grad_a))
                gradient.setColorAt(0.55, QColor(t.grad_b))
                gradient.setColorAt(1, QColor(t.grad_c))
                painter.setBrush(gradient)
            painter.drawRoundedRect(fill, 4, 4)


class Sparkline(QWidget):
    """Recent 0-100 values; draws nothing until there are at least two real samples."""

    def __init__(self, tokens: Tokens = DARK) -> None:
        super().__init__()
        self._tokens = tokens
        self._values: list[float] = []
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(40)

    def set_values(self, values) -> None:
        self._values = [float(v) for v in values]
        self.update()

    @property
    def values(self) -> list[float]:
        return list(self._values)

    def paintEvent(self, event) -> None:  # noqa: N802
        if len(self._values) < 2:
            return
        t = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width() - 2.0, self.height() - 4.0
        step = w / (HISTORY - 1)
        x0 = 1.0 + w - step * (len(self._values) - 1)
        points = [QPointF(x0 + i * step, 2.0 + h * (1 - min(100.0, max(0.0, v)) / 100.0))
                  for i, v in enumerate(self._values)]
        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)
        area = QPainterPath(line)
        area.lineTo(QPointF(points[-1].x(), self.height()))
        area.lineTo(QPointF(points[0].x(), self.height()))
        area.closeSubpath()
        fill = QColor(t.cyan)
        fill.setAlpha(36)
        painter.fillPath(area, fill)
        painter.setPen(QPen(QColor(t.cyan), 1.6))
        painter.drawPath(line)


class Thumb(QWidget):
    """A 16:9-ish preview that crops to fill; an empty one says why it is empty."""

    def __init__(self, tokens: Tokens = DARK) -> None:
        super().__init__()
        self._tokens = tokens
        self._pixmap: QPixmap | None = None
        self.setFixedHeight(132)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @property
    def has_image(self) -> bool:
        return self._pixmap is not None

    def set_png(self, data: bytes | None) -> None:
        pixmap = QPixmap()
        self._pixmap = pixmap if data and pixmap.loadFromData(data) else None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 8, 8)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(t.raised))
        if self._pixmap is None:
            painter.setPen(QColor(t.faint))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No render yet")
            return
        scale = max(rect.width() / self._pixmap.width(), rect.height() / self._pixmap.height())
        w, h = self._pixmap.width() * scale, self._pixmap.height() * scale
        painter.drawPixmap(QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h),
                           self._pixmap, QRectF(self._pixmap.rect()))


class ProjectTile(QFrame):
    """A recent project: preview, name, size line and a status chip. Click or Enter opens it."""

    clicked = Signal(str)  # project id

    def __init__(self, item: RecentProject, tokens: Tokens = DARK) -> None:
        super().__init__()
        self.setObjectName("tile")
        self.project_id = item.summary.id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"Open project {item.summary.name}")
        self.setToolTip("Open in Library")
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 10, 10, 12)
        box.setSpacing(8)
        self.thumb = Thumb(tokens)
        self.thumb.set_png(item.thumb)
        box.addWidget(self.thumb)
        self.name = _label(item.summary.name, "cardTitle")
        box.addWidget(self.name)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.meta = _label(project_meta(item.summary), "hint")
        row.addWidget(self.meta, 1)
        text, state = status_chip(item.status)
        self.chip = _label(text, "chip")
        self.chip.setProperty("state", state)
        row.addWidget(self.chip)
        box.addLayout(row)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.project_id)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.project_id)
            return
        super().keyPressEvent(event)


def project_meta(summary) -> str:
    """Only what the backend reported; nothing is guessed."""
    parts = []
    if summary.width and summary.height:
        parts.append(f"{summary.width}×{summary.height}")
    if summary.fps:
        parts.append(f"{summary.fps:g} fps")
    seconds = summary.duration_seconds
    if seconds is not None:
        parts.append(f"{seconds:.1f} s")
    return " · ".join(parts) or NA


# ----------------------------------------------------------------------------- page

def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class HomePage(QFrame):
    open_connections = Signal()
    new_project = Signal()
    open_library = Signal()
    open_lab = Signal()
    open_project = Signal(str)  # project id

    TILE_COLUMNS = 3

    def __init__(self, session: BackendSession, service: DashboardService,
                 tokens: Tokens = DARK, recent: RecentProjectsService | None = None) -> None:
        super().__init__()
        self._recent = recent
        self.setObjectName("pageSurface")
        self._session = session
        self._service = service
        self._tokens = tokens
        self._history: deque[float] = deque(maxlen=HISTORY)
        self._features_ok = True
        self._telemetry_error: str | None = None
        self._updated_at: datetime | None = None
        self._catalog: ModelCatalog | None = None
        self._build()
        session.changed.connect(self._session_changed)
        service.telemetry_updated.connect(self._telemetry_updated)
        service.telemetry_failed.connect(self._telemetry_failed)
        service.models_updated.connect(self._models_updated)
        service.models_failed.connect(self._models_failed)
        service.cleared.connect(self._cleared)
        if recent is not None:
            recent.updated.connect(self._recent_updated)
            recent.failed.connect(self._recent_failed)
            recent.cleared.connect(self._recent_cleared)
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(2000)
        self._stale_timer.timeout.connect(self._refresh_notice)
        self._stale_timer.start()
        self._session_changed()

    # -- construction -------------------------------------------------------------------

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(_label(title, "cardTitle"))
        return card, layout

    def _metric_row(self, caption: str) -> tuple[QVBoxLayout, QLabel, MeterBar]:
        box = QVBoxLayout()
        box.setSpacing(5)
        head = QHBoxLayout()
        head.addWidget(_label(caption, "fieldLabel"))
        head.addStretch(1)
        value = _label(NA, "metricValue")
        head.addWidget(value)
        box.addLayout(head)
        bar = MeterBar(self._tokens)
        box.addWidget(bar)
        return box, value, bar

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("connectionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("connectionsContent")
        scroll.setWidget(content)
        page = QVBoxLayout(content)
        page.setContentsMargins(38, 34, 38, 28)
        page.setSpacing(16)

        page.addWidget(_label("HOME / STUDIO", "sectionCaption"))
        page.addWidget(_label("Welcome to Morphorum Studio", "pageHeading"))
        self.status_line = _label("", "pageDescription", wrap=True)
        page.addWidget(self.status_line)
        self.notice = _label("", "notice", wrap=True)
        self.notice.setVisible(False)
        page.addWidget(self.notice)
        self._page_layout = page

        self.body = QStackedWidget()
        page.addWidget(self.body)
        page.addStretch(1)

        # -- offline state
        offline = QFrame()
        offline.setObjectName("card")
        obox = QVBoxLayout(offline)
        obox.setContentsMargins(24, 22, 24, 24)
        obox.setSpacing(10)
        obox.addWidget(_label("No backend connected", "cardTitle"))
        obox.addWidget(_label(
            "Studio shows live GPU, memory and model information from a Morphorum backend. "
            "Rendering and models stay on the backend; nothing here needs a local GPU.",
            "hint", wrap=True))
        self.connect_button = QPushButton("Open connection settings")
        self.connect_button.setObjectName("primaryAction")
        self.connect_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.connect_button.clicked.connect(self.open_connections)
        obox.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(offline)

        # -- connected state
        live = QWidget()
        lbox = QVBoxLayout(live)
        lbox.setContentsMargins(0, 0, 0, 0)
        lbox.setSpacing(16)
        lbox.addWidget(self._build_hero())
        self.recent_section = self._build_recent()
        lbox.addWidget(self.recent_section)
        row = QHBoxLayout()
        row.setSpacing(16)

        backend, bbox = self._card("Backend")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        self._backend_values: dict[str, QLabel] = {}
        for r, key in enumerate(("Profile", "Address", "Version", "Mode", "Instance", "Features")):
            grid.addWidget(_label(key, "fieldLabel"), r, 0)
            value = _label(NA, "metricValue", wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(value, r, 1)
            self._backend_values[key] = value
        grid.setColumnStretch(1, 1)
        bbox.addLayout(grid)
        bbox.addStretch(1)
        row.addWidget(backend, 1)

        gpu, gbox = self._card("GPU")
        self.gpu_name = _label(NA, "metricValue", wrap=True)
        gbox.addWidget(self.gpu_name)
        util_box, self.gpu_util_value, self.gpu_util_bar = self._metric_row("Utilization")
        gbox.addLayout(util_box)
        vram_box, self.gpu_vram_value, self.gpu_vram_bar = self._metric_row("VRAM")
        gbox.addLayout(vram_box)
        self.gpu_temp = _label("Temperature " + NA, "hint")
        gbox.addWidget(self.gpu_temp)
        self.sparkline = Sparkline(self._tokens)
        gbox.addWidget(self.sparkline)
        self.gpu_note = _label("", "hint", wrap=True)
        gbox.addWidget(self.gpu_note)
        row.addWidget(gpu, 1)

        system, sbox = self._card("System")
        cpu_box, self.cpu_value, self.cpu_bar = self._metric_row("CPU")
        sbox.addLayout(cpu_box)
        ram_box, self.ram_value, self.ram_bar = self._metric_row("Memory")
        sbox.addLayout(ram_box)
        self.updated_label = _label("Waiting for the first reading…", "hint", wrap=True)
        sbox.addWidget(self.updated_label)
        sbox.addStretch(1)
        row.addWidget(system, 1)
        lbox.addLayout(row)

        models, mbox = self._card("Models")
        head = QHBoxLayout()
        head.setSpacing(10)
        self.family_combo = QComboBox()
        self.family_combo.setMinimumWidth(190)
        self.family_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.family_combo.setAccessibleName("Model family")
        self.family_combo.addItem("All families", None)
        self.family_combo.currentIndexChanged.connect(self._family_chosen)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.refresh_button.setMinimumWidth(90)
        self.refresh_button.clicked.connect(self._service.refresh_now)
        self.model_summary = _label("Loading model inventory…", "hint", wrap=True)
        head.addWidget(self.model_summary, 1)
        head.addWidget(self.family_combo)
        head.addWidget(self.refresh_button)
        mbox.addLayout(head)
        self.family_defaults = _label("", "hint", wrap=True)
        mbox.addWidget(self.family_defaults)
        self.model_tree = QTreeWidget()
        self.model_tree.setObjectName("modelTree")
        self.model_tree.setColumnCount(4)
        self.model_tree.setHeaderLabels(["Name", "Type", "Size", "Variant"])
        self.model_tree.setRootIsDecorated(False)
        self.model_tree.setUniformRowHeights(True)
        self.model_tree.setAlternatingRowColors(False)
        self.model_tree.setMinimumHeight(220)
        self.model_tree.setAccessibleName("Installed models")
        self.model_tree.setColumnWidth(0, 360)
        self.model_tree.setColumnWidth(1, 110)
        self.model_tree.setColumnWidth(2, 100)
        mbox.addWidget(self.model_tree)
        self.model_footer = _label(
            "Read-only inventory from the backend. Loading and running models arrives with "
            "image generation (S3).", "hint", wrap=True)
        mbox.addWidget(self.model_footer)
        lbox.addWidget(models)
        self.body.addWidget(live)


    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("hero")
        box = QVBoxLayout(hero)
        box.setContentsMargins(26, 22, 26, 24)
        box.setSpacing(8)
        box.addWidget(_label("What are we making?", "heroTitle"))
        box.addWidget(_label(
            "Start an animation project, open one you have been working on, or generate a "
            "single image. Rendering runs on your Morphorum backend.", "hint", wrap=True))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.new_button = QPushButton("New project")
        self.new_button.setObjectName("primaryAction")
        self.open_button = QPushButton("Open project")
        self.generate_button = QPushButton("Generate image")
        for button in (self.new_button, self.open_button, self.generate_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            row.addWidget(button)
        row.addStretch(1)
        box.addSpacing(6)
        box.addLayout(row)
        self.new_button.setToolTip("Open the new-project wizard in Library")
        self.open_button.setToolTip("Browse projects in Library")
        self.generate_button.setToolTip("Open Lab to generate a single image")
        self.new_button.clicked.connect(self.new_project)
        self.open_button.clicked.connect(self.open_library)
        self.generate_button.clicked.connect(self.open_lab)
        return hero

    def _build_recent(self) -> QWidget:
        section = QWidget()
        box = QVBoxLayout(section)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(16)

        recent, rbox = self._card("Recent projects")
        self.recent_note = _label("Loading projects…", "hint", wrap=True)
        rbox.addWidget(self.recent_note)
        self.recent_grid = QGridLayout()
        self.recent_grid.setHorizontalSpacing(14)
        self.recent_grid.setVerticalSpacing(14)
        for column in range(self.TILE_COLUMNS):
            self.recent_grid.setColumnStretch(column, 1)
        rbox.addLayout(self.recent_grid)
        self.tiles: list[ProjectTile] = []
        box.addWidget(recent)

        queue, qbox = self._card("Render queue")
        self.queue_note = _label("", "hint", wrap=True)
        qbox.addWidget(self.queue_note)
        self.queue_rows = QVBoxLayout()
        self.queue_rows.setSpacing(6)
        qbox.addLayout(self.queue_rows)
        self.queue_card = queue
        box.addWidget(queue)
        return section

    # -- recent projects and queue ---------------------------------------------------------

    def _recent_updated(self, items) -> None:
        for tile in self.tiles:
            tile.setParent(None)
            tile.deleteLater()
        self.tiles = []
        for index, item in enumerate(items):
            tile = ProjectTile(item, self._tokens)
            tile.clicked.connect(self.open_project)
            self.recent_grid.addWidget(tile, index // self.TILE_COLUMNS, index % self.TILE_COLUMNS)
            tile.show()  # tiles may be added while this page is hidden; show with the parent
            self.tiles.append(tile)
        self.recent_note.setText("" if items else
                                 "No projects yet. Use New project to create your first one.")
        self.recent_note.setVisible(not items)
        self._fill_queue(items)

    def _fill_queue(self, items) -> None:
        while self.queue_rows.count():
            widget = self.queue_rows.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        shown = [i for i in items if i.status is not None]
        shown.sort(key=lambda i: 0 if status_chip(i.status)[1] == "busy" else 1)
        for item in shown[:5]:
            row = QWidget()
            hbox = QHBoxLayout(row)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.addWidget(_label(item.summary.name, "metricValue"), 1)
            text, state = status_chip(item.status)
            chip = _label(text, "chip")
            chip.setProperty("state", state)
            hbox.addWidget(chip)
            self.queue_rows.addWidget(row)
        self.queue_note.setText(
            "Latest render of each recent project." if shown
            else "No renders yet in your recent projects.")

    def _recent_failed(self, code: str) -> None:
        self.recent_note.setText(f"Could not load projects ({code}). Retrying.")
        self.recent_note.setVisible(True)

    def _recent_cleared(self) -> None:
        self._recent_updated(())
        self.recent_note.setText("Loading projects…")
        self.recent_note.setVisible(True)
        self.queue_note.setText("")

    def add_strip(self, widget: QWidget) -> None:
        """Show a status strip (the local backend) under the page's status line."""
        self._page_layout.insertWidget(4, widget)

    # -- session ------------------------------------------------------------------------

    def _session_changed(self) -> None:
        info = self._session.info
        if info is None:
            self.body.setCurrentIndex(0)
            self.status_line.setText("Connect to a Morphorum GPU backend to see live status here.")
            self._set_notice("")
            self._reset_values()
            return
        self.body.setCurrentIndex(1)
        enabled = sorted(name for name, on in info.features.items() if on)
        values = self._backend_values
        values["Profile"].setText(info.profile_name)
        values["Address"].setText(info.base_url)
        values["Version"].setText(info.version)
        values["Mode"].setText(info.mode)
        values["Instance"].setText(info.instance_id[:8] + "…")
        values["Instance"].setToolTip(f"Instance {info.instance_id}\nBoot {info.boot_id}")
        values["Features"].setText(f"{len(enabled)} enabled" if enabled else "none advertised")
        values["Features"].setToolTip(", ".join(enabled))
        self.recent_section.setVisible(self._recent is not None and info.features.get("project_crud") is True)
        self._features_ok = info.features.get("gpu_telemetry") is True
        self.status_line.setText(
            f"Connected to {info.profile_name}. Live readings update every few seconds "
            "while this page is open.")
        if not self._features_ok:
            self.gpu_note.setText("This backend does not advertise live telemetry.")
        self._refresh_notice()

    def _reset_values(self) -> None:
        self._history.clear()
        self.sparkline.set_values([])
        self._telemetry_error = None
        self._updated_at = None
        self._catalog = None
        self.gpu_name.setText(NA)
        for value, bar in ((self.gpu_util_value, self.gpu_util_bar),
                           (self.gpu_vram_value, self.gpu_vram_bar),
                           (self.cpu_value, self.cpu_bar), (self.ram_value, self.ram_bar)):
            value.setText(NA)
            bar.set_fraction(None)
        self.gpu_temp.setText("Temperature " + NA)
        self.gpu_note.setText("")
        self.updated_label.setText("Waiting for the first reading…")
        self.model_tree.clear()
        self.model_summary.setText("Loading model inventory…")
        self.family_defaults.setText("")
        self.family_combo.blockSignals(True)
        self.family_combo.clear()
        self.family_combo.addItem("All families", None)
        self.family_combo.blockSignals(False)

    def _cleared(self) -> None:
        self._reset_values()
        self._refresh_notice()

    # -- telemetry ----------------------------------------------------------------------

    def _telemetry_updated(self, telemetry: Telemetry) -> None:
        self._telemetry_error = None
        self._updated_at = datetime.now()
        self.updated_label.setText("Updated " + self._updated_at.strftime("%H:%M:%S"))
        self.cpu_value.setText(format_percent(telemetry.cpu_percent))
        self.cpu_bar.set_fraction(None if telemetry.cpu_percent is None else telemetry.cpu_percent / 100)
        ram = telemetry.ram
        if ram is None:
            self.ram_value.setText(NA)
            self.ram_bar.set_fraction(None)
        else:
            if ram.used_bytes is not None and ram.total_bytes:
                self.ram_value.setText(f"{format_bytes(ram.used_bytes)} / {format_bytes(ram.total_bytes)}")
                self.ram_bar.set_fraction(ram.used_bytes / ram.total_bytes)
            else:
                self.ram_value.setText(format_percent(ram.used_percent))
                self.ram_bar.set_fraction(None if ram.used_percent is None else ram.used_percent / 100)
        self.cpu_bar.setAccessibleName("CPU usage " + self.cpu_value.text())
        self.ram_bar.setAccessibleName("Memory usage " + self.ram_value.text())

        if not telemetry.gpus:
            self.gpu_name.setText("No NVIDIA GPU reported")
            self.gpu_note.setText(
                "The backend reported no GPU (no NVIDIA driver or nvidia-smi on the host).")
            for value, bar in ((self.gpu_util_value, self.gpu_util_bar),
                               (self.gpu_vram_value, self.gpu_vram_bar)):
                value.setText(NA)
                bar.set_fraction(None)
            self.gpu_temp.setText("Temperature " + NA)
            self._history.clear()
        else:
            device = telemetry.gpus[0]
            more = len(telemetry.gpus) - 1
            self.gpu_name.setText(device.name + (f"  (+{more} more)" if more else ""))
            self.gpu_note.setText("")
            self.gpu_util_value.setText(format_percent(device.utilization_percent))
            self.gpu_util_bar.set_fraction(
                None if device.utilization_percent is None else device.utilization_percent / 100)
            self.gpu_vram_value.setText(vram_text(device))
            self.gpu_vram_bar.set_fraction(device.memory_used_fraction)
            self.gpu_temp.setText(
                "Temperature " + (NA if device.temperature_c is None else f"{device.temperature_c:.0f} °C"))
            if device.utilization_percent is not None:
                self._history.append(device.utilization_percent)
            self.sparkline.set_values(self._history)
            self.gpu_util_bar.setAccessibleName("GPU utilization " + self.gpu_util_value.text())
            self.gpu_vram_bar.setAccessibleName("GPU memory " + self.gpu_vram_value.text())
        self._refresh_notice()

    def _telemetry_failed(self, code: str) -> None:
        self._telemetry_error = code
        self._refresh_notice()

    def _set_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _refresh_notice(self) -> None:
        stale = False
        if self._session.state == "reconnecting":
            self._set_notice("The backend is not responding. Studio is retrying; showing the "
                             "last readings.")
            stale = True
        elif self._session.state == "connected" and self._telemetry_error:
            self._set_notice(f"Live metrics are unavailable right now ({self._telemetry_error}). "
                             "Retrying; the values shown may be out of date.")
            stale = True
        elif self._session.state == "connected" and self._service.telemetry_is_stale():
            self._set_notice("Live metrics have not updated recently.")
            stale = True
        else:
            self._set_notice("")
        self.body.setProperty("stale", stale)
        for widget in self.body.findChildren(QLabel, "metricValue"):
            widget.setProperty("stale", stale)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    # -- models -------------------------------------------------------------------------

    def _family_chosen(self, _index: int) -> None:
        self._service.select_family(self.family_combo.currentData())

    def _models_updated(self, catalog: ModelCatalog, selection) -> None:
        family, models = selection
        self._catalog = catalog
        # Keep the combo in step with the backend's family list without re-triggering a fetch.
        wanted = [(f.label, f.id) for f in catalog.families]
        current = [(self.family_combo.itemText(i), self.family_combo.itemData(i))
                   for i in range(1, self.family_combo.count())]
        if wanted != current:
            self.family_combo.blockSignals(True)
            self.family_combo.clear()
            self.family_combo.addItem("All families", None)
            for label, family_id in wanted:
                self.family_combo.addItem(label, family_id)
            index = self.family_combo.findData(family)
            self.family_combo.setCurrentIndex(max(0, index))
            self.family_combo.blockSignals(False)

        labels = {f.id: f.label for f in catalog.families}
        parts = []
        for fam, kinds in catalog.summary.counts.items():
            total = sum(kinds.values())
            parts.append(f"{labels.get(fam, fam)} {total}")
        self.model_summary.setText(
            f"{catalog.summary.total} indexed on the backend"
            + (" · " + " · ".join(parts) if parts else ""))

        defaults = catalog.defaults.get(family) if (catalog.defaults and family) else None
        if defaults is not None:
            bits = []
            if defaults.steps_default is not None:
                bits.append(f"{defaults.steps_default} steps")
            if defaults.guidance_default is not None:
                bits.append(f"{defaults.guidance_label or 'Guidance'} {defaults.guidance_default:g}")
            if defaults.width and defaults.height:
                bits.append(f"{defaults.width}×{defaults.height}")
            if defaults.sampler_default:
                bits.append(f"sampler {defaults.sampler_default}")
            suffix = "" if defaults.supported else " (not yet supported for generation)"
            self.family_defaults.setText(
                f"{defaults.label} backend defaults: " + (" · ".join(bits) or NA) + suffix)
        elif family:
            self.family_defaults.setText("The backend did not provide generation defaults for this family.")
        else:
            self.family_defaults.setText("Choose a family to see its backend defaults.")

        self.model_tree.clear()
        for model in models:
            item = QTreeWidgetItem([
                model.name,
                model.kind,
                NA if model.size_bytes is None else format_bytes(model.size_bytes),
                model.variant or NA,
            ])
            item.setToolTip(0, model.filename or model.name)
            self.model_tree.addTopLevelItem(item)
        if not models:
            where = "this family" if family else "the backend"
            empty = QTreeWidgetItem([f"No models are indexed for {where}.", "", "", ""])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.model_tree.addTopLevelItem(empty)
        footer = ("Read-only inventory from the backend. Loading and running models arrives with "
                  "image generation (S3).")
        if len(models) >= 1000:
            footer = f"Showing the first {len(models)} models. " + footer
        self.model_footer.setText(footer)

    def _models_failed(self, code: str) -> None:
        self.model_summary.setText(f"Could not load the model inventory ({code}). Retrying.")
