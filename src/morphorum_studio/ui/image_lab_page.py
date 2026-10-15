"""Image Lab (S3.1): build a request, submit it durably, watch the job, view and save results."""

from __future__ import annotations

import re
import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap, QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.images import (
    GenerationSpec,
    ImageJob,
    JournalEntry,
    eta_text,
    model_variant,
    size_step,
    validate_spec,
)
from morphorum_studio.backend.schema import FamilyDefaults, ModelEntry
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.image_service import ImageLabService
from morphorum_studio.ui.lab_widgets import (
    LinkedSlider,
    LoraWeights,
    parse_lora_tags,
    remove_lora_tag,
    set_lora_weight,
)
from morphorum_studio.ui.player_panel import FrameView
from morphorum_studio.ui.image_viewer import ImageViewer
from morphorum_studio.ui.preferences import StudioPreferences

THUMB = QSize(104, 104)
CUSTOM = "Custom"
_SEED = re.compile(r"-1|\d{1,10}")


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    box = QVBoxLayout(frame)
    box.setContentsMargins(20, 16, 20, 18)
    box.setSpacing(10)
    box.addWidget(_label(title, "cardTitle"))
    return frame, box


class ImageLabPage(QFrame):
    open_connections = Signal()

    def __init__(self, session: BackendSession, service: ImageLabService,
                 preferences: StudioPreferences) -> None:
        super().__init__()
        self.setObjectName("pageSurface")
        self._session = session
        self._service = service
        self._prefs = preferences
        self._active = False
        self._checkpoints: tuple[ModelEntry, ...] = ()
        self._loras: tuple[ModelEntry, ...] = ()
        self._defaults: dict[str, FamilyDefaults] = {}
        self._limits: FamilyDefaults | None = None
        self._limits_key: tuple | None = None
        self._family = ""
        self._job: ImageJob | None = None
        self._pixmaps: dict[tuple[str, str], QPixmap] = {}
        self._requested: set[tuple[str, str]] = set()
        self._buttons: dict[tuple[str, str], QToolButton] = {}
        self._shown: tuple | None = None
        self._selected: tuple[str, str] | None = None  # (job id, file name) on the stage
        self._seeds: dict[tuple[str, str], int | None] = {}
        self._recent: tuple[ImageJob, ...] = ()
        self._pending: list[JournalEntry] = []
        self._viewer: tuple[ImageViewer, str, str] | None = None
        self._build()
        session.changed.connect(self._session_changed)
        service.setup_ready.connect(self._setup_ready)
        service.submitted.connect(self._submitted)
        service.job_updated.connect(self._job_updated)
        service.recent_ready.connect(self._recent_ready)
        service.pending_ready.connect(self._pending_ready)
        service.image_ready.connect(self._image_ready)
        service.copy_saved.connect(self._copied)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update_buttons())
        service.cleared.connect(self._cleared)
        self._session_changed()

    # -- construction -------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.width() < 1050
        self.lab_layout.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        self.parameter_scroll.setMaximumWidth(16777215 if compact else 430)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(38, 34, 38, 24)
        outer.setSpacing(12)
        outer.addWidget(_label("LAB / STUDIO", "sectionCaption"))
        outer.addWidget(_label("Lab", "pageHeading"))
        self.status_line = _label("", "pageDescription", wrap=True)
        outer.addWidget(self.status_line)
        self.connect_button = QPushButton("Open connection settings")
        self.connect_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.connect_button.clicked.connect(self.open_connections)
        outer.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignLeft)

        body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.lab_layout = body
        body.setSpacing(16)
        outer.addLayout(body, 1)

        # -- centre: job, image stage and batch strip
        centre = QVBoxLayout()
        centre.setSpacing(12)
        body.addLayout(centre, 1)

        self.pending_card = QFrame()
        self.pending_card.setObjectName("card")
        pending_box = QVBoxLayout(self.pending_card)
        pending_box.setContentsMargins(20, 14, 20, 14)
        pending_box.setSpacing(8)
        self.pending_label = _label("", "metricValue", wrap=True)
        pending_box.addWidget(self.pending_label)
        pending_row = QHBoxLayout()
        self.pending_retry = QPushButton("Retry the same request")
        self.pending_discard = QPushButton("Discard")
        for button in (self.pending_retry, self.pending_discard):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            pending_row.addWidget(button)
        pending_row.addStretch(1)
        pending_box.addLayout(pending_row)
        self.pending_card.setVisible(False)
        centre.addWidget(self.pending_card)

        stage_card = QFrame()
        stage_card.setObjectName("card")
        sbox = QVBoxLayout(stage_card)
        sbox.setContentsMargins(14, 14, 14, 14)
        sbox.setSpacing(8)
        self.stage = FrameView()
        self.stage.setMinimumHeight(260)
        self.stage.show_message("Generated images appear here.")
        sbox.addWidget(self.stage, 1)
        self.job_title = _label("No job yet.", "metricValue", wrap=True)
        sbox.addWidget(self.job_title)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        sbox.addWidget(self.progress)
        self.job_status = _label("", "hint", wrap=True)
        sbox.addWidget(self.job_status)
        stage_actions = QHBoxLayout()
        stage_actions.setSpacing(8)
        self.stage_save_button = QPushButton("Save…")
        self.stage_open_button = QPushButton("Full size…")
        self.stage_save_button.setToolTip("Save a copy of the selected image")
        self.stage_open_button.setToolTip("View the selected image at full size")
        for button in (self.stage_save_button, self.stage_open_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            stage_actions.addWidget(button)
        self.stage_info = _label("", "hint")
        stage_actions.addWidget(self.stage_info, 1)
        sbox.addLayout(stage_actions)
        centre.addWidget(stage_card, 1)

        strip_card = QFrame()
        strip_card.setObjectName("card")
        tbox = QVBoxLayout(strip_card)
        tbox.setContentsMargins(14, 12, 14, 12)
        tbox.setSpacing(6)
        recent_row = QHBoxLayout()
        recent_row.addWidget(_label("Batch", "fieldLabel"))
        self.recent_combo = QComboBox()
        self.recent_combo.setAccessibleName("Earlier jobs")
        recent_row.addWidget(self.recent_combo, 1)
        tbox.addLayout(recent_row)
        self.results_note = _label("Generated images appear here.", "hint", wrap=True)
        tbox.addWidget(self.results_note)
        self.results_grid = QGridLayout()
        self.results_grid.setSpacing(8)
        strip_host = QWidget()
        strip_layout = QHBoxLayout(strip_host)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.addLayout(self.results_grid)
        strip_layout.addStretch(1)
        strip = QScrollArea()
        strip.setWidgetResizable(True)
        strip.setFrameShape(QFrame.Shape.NoFrame)
        strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        strip.setFixedHeight(THUMB.height() + 70)
        strip.setWidget(strip_host)
        tbox.addWidget(strip)
        centre.addWidget(strip_card)

        # -- right: parameters
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.parameter_scroll = form_scroll
        form_scroll.setMinimumWidth(300)
        form_scroll.setMaximumWidth(430)
        form_host = QWidget()
        form_host.setObjectName("connectionsContent")
        form_scroll.setWidget(form_host)
        left = QVBoxLayout(form_host)
        left.setContentsMargins(0, 0, 8, 0)
        left.setSpacing(12)
        self.form_host = form_host

        model_card, mbox = _card("Model")
        self.model_combo = QComboBox()
        self.model_combo.setAccessibleName("Model")
        mbox.addWidget(self.model_combo)
        self.model_hint = _label("", "hint", wrap=True)
        mbox.addWidget(self.model_hint)
        left.addWidget(model_card)

        prompt_card, pbox = _card("Prompt")
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText("Describe the image")
        self.prompt_edit.setMinimumHeight(110)
        self.prompt_edit.setMaximumHeight(170)
        self.prompt_edit.setAccessibleName("Prompt")
        pbox.addWidget(self.prompt_edit)
        self.negative_label = _label("Negative prompt", "fieldLabel")
        pbox.addWidget(self.negative_label)
        self.negative_edit = QPlainTextEdit()
        self.negative_edit.setMinimumHeight(60)
        self.negative_edit.setMaximumHeight(100)
        self.negative_edit.setAccessibleName("Negative prompt")
        pbox.addWidget(self.negative_edit)
        lora_row = QHBoxLayout()
        lora_row.setSpacing(8)
        self.lora_combo = QComboBox()
        self.lora_combo.setAccessibleName("LoRA")
        self.lora_weight = QDoubleSpinBox()
        self.lora_weight.setRange(-2.0, 2.0)
        self.lora_weight.setSingleStep(0.05)
        self.lora_weight.setDecimals(2)
        self.lora_weight.setValue(0.8)
        self.lora_weight.setFixedWidth(80)
        self.lora_button = QPushButton("Add LoRA")
        self.lora_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lora_row.addWidget(self.lora_combo, 1)
        lora_row.addWidget(self.lora_weight)
        lora_row.addWidget(self.lora_button)
        pbox.addLayout(lora_row)
        self.lora_hint = _label("", "hint", wrap=True)
        pbox.addWidget(self.lora_hint)
        self.lora_weights = LoraWeights()
        pbox.addWidget(self.lora_weights)
        left.addWidget(prompt_card)

        set_card, sbox2 = _card("Parameters")
        self.size_combo = QComboBox()
        self.size_combo.setVisible(False)  # the aspect tiles below drive it
        sbox2.addWidget(self.size_combo)
        sbox2.addWidget(_label("Aspect", "fieldLabel"))
        self.aspect_grid = QGridLayout()
        self.aspect_grid.setSpacing(6)
        sbox2.addLayout(self.aspect_grid)
        self.aspect_tiles: list[QToolButton] = []
        self.width_spin = QSpinBox()
        self.height_spin = QSpinBox()
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(64, 4096)
            spin.setSingleStep(8)
        size_row = QHBoxLayout()
        size_row.addWidget(_label("Size", "fieldLabel"))
        size_row.addWidget(self.width_spin)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height_spin)
        size_row.addStretch(1)
        sbox2.addLayout(size_row)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 150)
        self.steps_slider = LinkedSlider(self.steps_spin)
        self.guidance_label = _label("Guidance", "fieldLabel")
        self.guidance_spin = QDoubleSpinBox()
        self.guidance_spin.setRange(0.0, 30.0)
        self.guidance_spin.setSingleStep(0.5)
        self.guidance_spin.setDecimals(2)
        self.guidance_slider = LinkedSlider(self.guidance_spin, scale=20)
        self.sampler_combo = QComboBox()
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 32)
        self.seed_edit = QLineEdit("-1")
        self.seed_edit.setValidator(QRegularExpressionValidator(QRegularExpression(_SEED.pattern)))
        self.seed_edit.setAccessibleName("Seed (-1 for random)")
        self.seed_lock = QCheckBox("Lock seed")
        self.seed_lock.setToolTip(
            "Keep the seed of the selected image so the next run is reproducible. Unlock for a random seed (-1).")
        self.seed_mode = QComboBox()
        for mode, text in (("fixed", "Same seed"), ("increment", "Step the seed"), ("random", "New random each")):
            self.seed_mode.addItem(text, mode)
        self.increment_spin = QSpinBox()
        self.increment_spin.setRange(-1_000_000, 1_000_000)
        self.increment_spin.setValue(1)
        self.increment_label = _label("Seed step", "fieldLabel")

        grid = QFormLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for caption, spin, slider in (("Steps", self.steps_spin, self.steps_slider),
                                      (None, self.guidance_spin, self.guidance_slider)):
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(slider, 1)
            row.addWidget(spin)
            grid.addRow(_label(caption, "fieldLabel") if caption else self.guidance_label, row)
        grid.addRow(_label("Sampler", "fieldLabel"), self.sampler_combo)
        grid.addRow(_label("Images", "fieldLabel"), self.count_spin)
        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)
        seed_row.addWidget(self.seed_edit, 1)
        seed_row.addWidget(self.seed_lock)
        grid.addRow(_label("Seed", "fieldLabel"), seed_row)
        grid.addRow(_label("Seed mode", "fieldLabel"), self.seed_mode)
        grid.addRow(self.increment_label, self.increment_spin)
        sbox2.addLayout(grid)
        left.addWidget(set_card)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.generate_button = QPushButton("Generate")
        self.generate_button.setObjectName("primaryAction")
        self.cancel_button = QPushButton("Cancel job")
        for button in (self.generate_button, self.cancel_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        actions.addWidget(self.generate_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        left.addLayout(actions)
        self.problem_label = _label("", "notice", wrap=True)
        self.problem_label.setVisible(False)
        left.addWidget(self.problem_label)
        left.addStretch(1)
        body.addWidget(form_scroll)

        self.model_combo.currentIndexChanged.connect(self._model_changed)
        self.size_combo.currentIndexChanged.connect(self._preset_changed)
        self.width_spin.valueChanged.connect(lambda _v: self._sync_preset())
        self.height_spin.valueChanged.connect(lambda _v: self._sync_preset())
        self.seed_mode.currentIndexChanged.connect(self._mode_changed)
        self.generate_button.clicked.connect(self._generate)
        self.cancel_button.clicked.connect(self._cancel)
        self.lora_button.clicked.connect(self._add_lora)
        self.prompt_edit.textChanged.connect(self._prompt_changed)
        self.lora_weights.weight_changed.connect(self._lora_weight_changed)
        self.lora_weights.removed.connect(self._lora_removed)
        self.seed_lock.toggled.connect(self._seed_lock_toggled)
        self.stage_save_button.clicked.connect(self._save_selected)
        self.stage_open_button.clicked.connect(self._open_selected)
        self.pending_retry.clicked.connect(self._retry_pending)
        self.pending_discard.clicked.connect(self._discard_pending)
        self.recent_combo.activated.connect(self._recent_chosen)
        self._mode_changed()

    # -- lifecycle ----------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and self._service.available:
            self._refresh_all()

    def reload_models(self) -> None:
        """The backend rescanned its model folders: read the lists again."""
        if self._service.available:
            self._service.load_setup()

    def _refresh_all(self) -> None:
        if not self._checkpoints:
            self._service.load_setup()
        self._service.load_recent()
        self._service.check_pending()

    def _session_changed(self) -> None:
        if self._service.available:
            self.status_line.setText(
                "Images are generated on the connected backend; nothing runs on this computer.")
            self.connect_button.setVisible(False)
            if self._active:
                self._refresh_all()
        else:
            info = self._session.info
            if info is None:
                self.status_line.setText("Connect to a Morphorum backend to generate images.")
                self.connect_button.setVisible(True)
            elif not self._session.feature("sdxl_generation"):
                self.status_line.setText("The connected backend does not advertise image generation.")
                self.connect_button.setVisible(True)
            else:
                self.status_line.setText("The backend is not responding. Studio is retrying.")
                self.connect_button.setVisible(False)
        self._update_buttons()

    def _cleared(self) -> None:
        self._checkpoints, self._loras, self._defaults = (), (), {}
        self._limits = self._limits_key = None
        self._job = None
        self._shown = None
        self._pending = []
        self._pixmaps.clear()
        self._requested.clear()
        self._selected = None
        self._seeds.clear()
        self.stage.show_message("Generated images appear here.")
        self.stage_info.setText("")
        self._recent = ()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.blockSignals(False)
        self.lora_combo.clear()
        self.recent_combo.clear()
        self.pending_card.setVisible(False)
        self.job_title.setText("No job yet.")
        self.job_status.setText("")
        self.progress.setValue(0)
        self._clear_results("Generated images appear here.")
        self._update_buttons()

    # -- setup data ---------------------------------------------------------------------

    def _setup_ready(self, checkpoints, loras, defaults) -> None:
        self._defaults = defaults
        self._checkpoints = tuple(m for m in checkpoints
                                  if m.family in defaults and defaults[m.family].supported)
        self._loras = tuple(loras)
        remembered = self._prefs.image_model(self._session.info.profile_id) if self._session.info else ""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in self._checkpoints:
            label = f"{model.name}  ·  {defaults[model.family].label}"
            self.model_combo.addItem(label, model.id)
        index = max(0, self.model_combo.findData(remembered))
        self.model_combo.setCurrentIndex(index if self._checkpoints else -1)
        self.model_combo.blockSignals(False)
        if not self._checkpoints:
            self.model_hint.setText(
                "No supported checkpoints are indexed on the backend. Add models there and rescan.")
        self._model_changed()

    def _model(self) -> ModelEntry | None:
        index = self.model_combo.currentIndex()
        return self._checkpoints[index] if 0 <= index < len(self._checkpoints) else None

    def _model_changed(self) -> None:
        model = self._model()
        if model is None:
            self._limits = None
            self._update_buttons()
            return
        self._family = model.family
        base = self._defaults[model.family]
        variant = model_variant(model.name, model.filename, model.variant, model.family)
        limits = base.for_variant(variant)
        self._limits = limits
        profile = self._session.info.profile_id if self._session.info else None
        if profile:
            self._prefs.set_image_model(profile, model.id)
        key = (model.family, variant)
        fresh = key != self._limits_key
        self._limits_key = key
        self.model_hint.setText(f"{limits.label}" + (f" · {variant}" if variant and variant != model.family else ""))
        step = size_step(model.family)
        for spin in (self.width_spin, self.height_spin):
            spin.setSingleStep(step)
        if limits.steps_min is not None and limits.steps_max is not None:
            self.steps_spin.setRange(limits.steps_min, limits.steps_max)
        if limits.guidance_min is not None and limits.guidance_max is not None:
            self.guidance_spin.setRange(limits.guidance_min, limits.guidance_max)
        self.guidance_label.setText(limits.guidance_label or "Guidance")
        self.guidance_spin.setEnabled(limits.guidance_min != limits.guidance_max)
        self.steps_slider.sync_range()
        self.guidance_slider.sync_range()
        has_negative = limits.negative_prompt is not False
        self.negative_label.setVisible(has_negative)
        self.negative_edit.setVisible(has_negative)
        if fresh:
            if limits.steps_default is not None:
                self.steps_spin.setValue(limits.steps_default)
            if limits.guidance_default is not None:
                self.guidance_spin.setValue(limits.guidance_default)
            self.sampler_combo.clear()
            for sampler in limits.sampler_ids:
                self.sampler_combo.addItem(sampler, sampler)
            if limits.sampler_default:
                self.sampler_combo.setCurrentIndex(max(0, self.sampler_combo.findData(limits.sampler_default)))
            self.size_combo.blockSignals(True)
            self.size_combo.clear()
            for name, w, h in limits.resolutions:
                self.size_combo.addItem(f"{name}  ({w}×{h})", (w, h))
            self.size_combo.addItem(CUSTOM, None)
            self.size_combo.blockSignals(False)
            self._build_aspect_tiles(limits.resolutions)
            if limits.width and limits.height:
                self.width_spin.setValue(limits.width)
                self.height_spin.setValue(limits.height)
            self._sync_preset()
        self.lora_combo.clear()
        usable = [m for m in self._loras if m.family == model.family and not re.search(r"[:<>]", m.name)]
        for lora in usable:
            self.lora_combo.addItem(lora.name, lora.name)
        self.lora_combo.setEnabled(bool(usable))
        self.lora_button.setEnabled(bool(usable))
        self.lora_hint.setText("" if usable else f"No {limits.label} LoRAs are indexed on the backend.")
        self._update_buttons()

    def _sync_preset(self) -> None:
        size = (self.width_spin.value(), self.height_spin.value())
        index = next((i for i in range(self.size_combo.count())
                      if (d := self.size_combo.itemData(i)) and tuple(d) == size), -1)
        self.size_combo.blockSignals(True)
        self.size_combo.setCurrentIndex(index if index >= 0 else self.size_combo.count() - 1)
        self.size_combo.blockSignals(False)
        for number, tile in enumerate(self.aspect_tiles):
            tile.setChecked(number == index)

    def _preset_changed(self) -> None:
        size = self.size_combo.currentData()
        if size:  # Qt may hand a tuple back as a list
            self.width_spin.setValue(size[0])
            self.height_spin.setValue(size[1])

    def _build_aspect_tiles(self, resolutions) -> None:
        """One tile per size preset the backend offers for this model; nothing is invented."""
        for tile in self.aspect_tiles:
            self.aspect_grid.removeWidget(tile)
            tile.deleteLater()
        self.aspect_tiles = []
        for number, (name, w, h) in enumerate(resolutions):
            tile = QToolButton()
            tile.setObjectName("aspectTile")
            tile.setCheckable(True)
            tile.setText(f"{name}\n{w}×{h}")
            tile.setToolTip(f"{name}: {w} × {h}")
            tile.setAccessibleName(f"{name} {w} by {h}")
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            tile.setFixedHeight(46)
            tile.clicked.connect(lambda _c=False, n=number: self.size_combo.setCurrentIndex(n))
            self.aspect_grid.addWidget(tile, number // 3, number % 3)
            self.aspect_tiles.append(tile)

    # -- LoRA weights live in the prompt tags ---------------------------------------------

    def _prompt_changed(self) -> None:
        self.lora_weights.set_tags(parse_lora_tags(self.prompt_edit.toPlainText()))

    def _rewrite_prompt(self, new: str) -> None:
        old = self.prompt_edit.toPlainText()
        if new == old:
            return
        position = self.prompt_edit.textCursor().position()
        self.prompt_edit.setPlainText(new)
        cursor = self.prompt_edit.textCursor()
        cursor.setPosition(min(position, len(new)))
        self.prompt_edit.setTextCursor(cursor)

    def _lora_weight_changed(self, index: int, weight: float) -> None:
        self.prompt_edit.blockSignals(True)  # rows are already showing this weight
        self._rewrite_prompt(set_lora_weight(self.prompt_edit.toPlainText(), index, weight))
        self.prompt_edit.blockSignals(False)
        self._prompt_changed()

    def _lora_removed(self, index: int) -> None:
        self._rewrite_prompt(remove_lora_tag(self.prompt_edit.toPlainText(), index))

    # -- the image stage ------------------------------------------------------------------

    def _select_result(self, job_id: str, filename: str) -> None:
        key = (job_id, filename)
        self._selected = key
        for other, button in self._buttons.items():
            button.setProperty("selected", other == key)
            button.style().unpolish(button)
            button.style().polish(button)
        pixmap = self._pixmaps.get(key)
        if pixmap is not None:
            self.stage.show_pixmap(pixmap)
        else:
            self.stage.show_message("Loading image…")
            if key not in self._requested:
                self._requested.add(key)
                self._service.fetch_image(job_id, filename)
        seed = self._seeds.get(key)
        self.stage_info.setText(f"{filename} · seed {seed}" if seed is not None else filename)
        if self.seed_lock.isChecked() and seed is not None:
            self._apply_locked_seed(seed)
        self._update_buttons()

    def _apply_locked_seed(self, seed: int) -> None:
        self.seed_edit.setText(str(seed))
        self.seed_mode.setCurrentIndex(max(0, self.seed_mode.findData("fixed")))

    def _seed_lock_toggled(self, on: bool) -> None:
        if not on:
            self.seed_edit.setText("-1")
            return
        seed = self._seeds.get(self._selected) if self._selected else None
        if seed is not None:
            self._apply_locked_seed(seed)

    def _save_selected(self) -> None:
        if self._selected:
            self._save(*self._selected)

    def _open_selected(self) -> None:
        if self._selected:
            self._open(*self._selected)

    def _mode_changed(self) -> None:
        increment = self.seed_mode.currentData() == "increment"
        self.increment_spin.setVisible(increment)
        self.increment_label.setVisible(increment)

    def _add_lora(self) -> None:
        name = self.lora_combo.currentData()
        if not name:
            return
        tag = f"<lora:{name}:{self.lora_weight.value():g}>"
        text = self.prompt_edit.toPlainText().rstrip()
        self.prompt_edit.setPlainText((text + " " if text else "") + tag)

    # -- building and sending a request -------------------------------------------------

    def _seed(self) -> int:
        text = self.seed_edit.text().strip()
        return int(text) if _SEED.fullmatch(text) else -2  # -2 fails validation with a clear message

    def current_spec(self) -> GenerationSpec | None:
        model = self._model()
        if model is None:
            return None
        return GenerationSpec(
            model_id=model.id, prompt=self.prompt_edit.toPlainText(),
            negative_prompt=self.negative_edit.toPlainText(),
            width=self.width_spin.value(), height=self.height_spin.value(),
            steps=self.steps_spin.value(), guidance_scale=self.guidance_spin.value(),
            sampler=self.sampler_combo.currentData() or "", seed=self._seed(),
            seed_mode=self.seed_mode.currentData(), seed_increment=self.increment_spin.value(),
            images=self.count_spin.value())

    def _generate(self) -> None:
        spec, limits = self.current_spec(), self._limits
        if spec is None or limits is None:
            self._show_problem("Choose a model first.")
            return
        problem = validate_spec(spec, limits, self._family)
        if problem:
            self._show_problem(problem)
            return
        self._show_problem("")
        self._service.submit(spec.payload(negative_allowed=limits.negative_prompt is not False))

    def _show_problem(self, text: str) -> None:
        self.problem_label.setText(text)
        self.problem_label.setVisible(bool(text))

    def _submitted(self, entry: JournalEntry, job: ImageJob) -> None:
        self._pending = [e for e in self._pending if e.key != entry.key]
        self._show_pending()
        self._job_updated(job)

    def _cancel(self) -> None:
        if self._job and self._job.active:
            self._service.cancel(self._job.id)

    # -- job display --------------------------------------------------------------------

    def _job_updated(self, job: ImageJob) -> None:
        current = self._job
        if current is not None and current.id != job.id and current.active and not job.active:
            return  # A stale answer about a different job.
        self._job = job
        model = job.model_name or "Image job"
        self.job_title.setText(f"{model}: {job.prompt}" if job.prompt else model)
        self.progress.setValue(int(max(0.0, min(1.0, job.progress)) * 1000))
        text = eta_text(job)
        if job.cancel_requested and job.active:
            text += " (cancelling…)"
        self.job_status.setText(text)
        self._show_results(job)
        self._update_buttons()

    def _show_results(self, job: ImageJob) -> None:
        shown = (job.id, tuple(r.filename for r in job.results), job.active)
        if shown == self._shown:
            return  # Progress ticks must not rebuild (and flicker) the thumbnails.
        self._shown = shown
        self._clear_results("")
        if not job.results:
            self.results_note.setText("No images yet." if job.active else "This job produced no images.")
            return
        self.results_note.setText("")
        keys = []
        for position, result in enumerate(job.results):
            button = QToolButton()
            button.setObjectName("thumb")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIconSize(THUMB)
            seed = f"seed {result.seed}" if result.seed is not None else f"#{result.index}"
            button.setText(seed)
            button.setFixedSize(THUMB.width() + 16, THUMB.height() + 36)
            button.setAccessibleName(f"Result {result.index}, {seed}")
            key = (job.id, result.filename)
            keys.append(key)
            self._seeds[key] = result.seed
            pixmap = self._pixmaps.get(key)
            if pixmap is not None:
                button.setIcon(QIcon(pixmap))
            elif key not in self._requested:
                self._requested.add(key)
                self._service.fetch_image(job.id, result.filename)
            button.clicked.connect(lambda _c=False, j=job.id, f=result.filename: self._select_result(j, f))
            self._buttons[key] = button
            self.results_grid.addWidget(button, 0, position)
        # A new job shows its first image; more images arriving for the same job keep your choice.
        self._select_result(*(self._selected if self._selected in keys else keys[0]))

    def _clear_results(self, note: str) -> None:
        self._buttons.clear()
        while self.results_grid.count():
            item = self.results_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.results_note.setText(note)

    def _image_ready(self, job_id: str, filename: str, data) -> None:
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self._pixmaps[(job_id, filename)] = pixmap
            button = self._buttons.get((job_id, filename))
            if button is not None:
                button.setIcon(QIcon(pixmap))
            if self._selected == (job_id, filename):
                self.stage.show_pixmap(pixmap)
            if self._viewer and self._viewer[1:] == (job_id, filename):
                self._viewer[0].set_pixmap(pixmap)
        else:
            self._requested.discard((job_id, filename))

    # -- opening and saving results -----------------------------------------------------

    def _open(self, job_id: str, filename: str) -> None:
        pixmap = self._pixmaps.get((job_id, filename))
        viewer = ImageViewer(filename, pixmap, self)
        viewer.save_requested.connect(lambda: self._save(job_id, filename))
        self._viewer = (viewer, job_id, filename)
        if pixmap is None:
            self._requested.add((job_id, filename))
            self._service.fetch_image(job_id, filename)
        viewer.exec()
        self._viewer = None

    def _save(self, job_id: str, filename: str) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save a copy", filename, "PNG image (*.png)")
        if path:
            self._service.save_copy(job_id, filename, path)

    def _copied(self, path: str) -> None:
        self.job_status.setText(f"Saved a copy to {path}")

    # -- earlier jobs -------------------------------------------------------------------

    def _recent_ready(self, jobs) -> None:
        self._recent = tuple(j for j in jobs if j.results or j.active)
        self.recent_combo.blockSignals(True)
        self.recent_combo.clear()
        self.recent_combo.addItem("Choose…", None)
        for job in self._recent:
            when = job.created_at[11:16] if job.created_at and len(job.created_at) >= 16 else ""
            snippet = (job.prompt[:48] + "…") if len(job.prompt) > 48 else job.prompt
            self.recent_combo.addItem(f"{when}  {len(job.results)} image(s)  {snippet}".strip(), job.id)
        self.recent_combo.blockSignals(False)

    def _recent_chosen(self, index: int) -> None:
        job_id = self.recent_combo.itemData(index)
        job = next((j for j in self._recent if j.id == job_id), None)
        if job is not None:
            self._job_updated(job)
            if job.active:
                self._service.watch(job.id)

    # -- unfinished submissions ---------------------------------------------------------

    def _pending_ready(self, entries) -> None:
        self._pending = list(entries)
        self._show_pending()

    def _show_pending(self) -> None:
        if not self._pending:
            self.pending_card.setVisible(False)
            return
        entry = self._pending[0]
        prompt = str(entry.payload.get("prompt", ""))[:80]
        when = time.strftime("%H:%M", time.localtime(entry.created))
        self.pending_label.setText(
            f"A request sent at {when} may not have reached the backend: “{prompt}”. "
            "Retrying sends the same request with the same key, so it cannot start a second job.")
        self.pending_card.setVisible(True)

    def _retry_pending(self) -> None:
        if self._pending:
            self._service.retry(self._pending[0])

    def _discard_pending(self) -> None:
        if self._pending:
            self._service.discard(self._pending[0].key)
            self._pending.pop(0)
            self._show_pending()

    # -- errors and buttons -------------------------------------------------------------

    def _failed(self, operation: str, code: str, message: str) -> None:
        if operation == "submit":
            QMessageBox.warning(self, "Could not start the job", message)
        elif operation == "copy":
            QMessageBox.warning(self, "Could not save the copy", message)
        elif operation == "job":
            self.job_status.setText(f"Lost track of the job ({code}). Reconnect and pick it from Earlier jobs.")
        elif operation == "cancel":
            QMessageBox.warning(self, "Could not cancel", message)
        elif operation == "setup":
            self.model_hint.setText(f"Could not load models ({code}). Switch pages or reconnect to retry.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        available = self._service.available
        busy = self._service.submitting
        active = bool(self._job and self._job.active)
        ready = available and self._limits is not None
        self.generate_button.setEnabled(ready and not busy and not active)
        self.cancel_button.setEnabled(available and active and not (self._job and self._job.cancel_requested))
        self.pending_retry.setEnabled(available and not busy)
        picked = available and self._selected is not None
        self.stage_save_button.setEnabled(picked)
        self.stage_open_button.setEnabled(picked)
        self.form_host.setEnabled(available)
