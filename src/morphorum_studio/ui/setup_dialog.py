"""New project wizard (S4.4): choose the basics, review the backend's verdict, then create.

Defaults come from the backend template. Nothing is created until the choices pass the local
checks and the backend's schedule review, and any edit throws that review away. The wizard never
writes camera values.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from morphorum_studio.backend.setup import MAX_FRAMES, MAX_SIDE, MIN_SIDE, Choices, check_choices, has_errors
from morphorum_studio.ui.setup_service import SetupService

SIZES = (("Square 1024 × 1024", 1024, 1024), ("Landscape 1344 × 768", 1344, 768),
         ("Portrait 768 × 1344", 768, 1344), ("Square 768 × 768", 768, 768),
         ("Square 512 × 512", 512, 512))


class NewProjectDialog(QDialog):
    project_created = Signal(str)

    def __init__(self, service: SetupService, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.resize(640, 720)
        self._service = service
        self._template: dict | None = None
        self._reviewed = False
        self._local: tuple = ()
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(12)
        intro = QLabel("Pick the basics. The backend supplies every other default and checks the "
                       "result before anything is created; camera schedules are left untouched.")
        intro.setWordWrap(True)
        box.addWidget(intro)
        form = QFormLayout()
        self.name = QLineEdit("Untitled Animation")
        self.model = QComboBox()
        self.model.addItem("Choose a checkpoint…", None)
        self.size_preset = QComboBox()
        for label, _w, _h in SIZES:
            self.size_preset.addItem(label)
        self.size_preset.addItem("Custom")
        self.width = QSpinBox()
        self.height = QSpinBox()
        for spin in (self.width, self.height):
            spin.setRange(MIN_SIDE, MAX_SIDE)
            spin.setSingleStep(8)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(1, 240)
        self.fps.setDecimals(2)
        self.fps.setValue(24)
        self.frames = QSpinBox()
        self.frames.setRange(1, MAX_FRAMES)
        self.frames.setValue(120)
        self.length_label = QLabel("")
        self.mode = QComboBox()
        self.mode.addItem("2D (fast camera moves)", "2d")
        self.mode.addItem("3D (depth-based camera)", "3d")
        self.start = QComboBox()
        self.start.addItem("The prompt (text to image)", "prompt")
        self.start.addItem("A source image (attach it afterwards)", "source")
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("First prompt (frame 0)")
        self.prompt.setFixedHeight(70)
        self.negative = QPlainTextEdit()
        self.negative.setPlaceholderText("Negative prompt (optional)")
        self.negative.setFixedHeight(50)
        form.addRow("Name", self.name)
        form.addRow("Checkpoint", self.model)
        form.addRow("Size", self.size_preset)
        size_row = QHBoxLayout()
        size_row.addWidget(self.width)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height)
        size_row.addStretch(1)
        form.addRow("", size_row)
        form.addRow("Frame rate", self.fps)
        form.addRow("Frames", self.frames)
        form.addRow("", self.length_label)
        form.addRow("Mode", self.mode)
        form.addRow("Start from", self.start)
        form.addRow("Prompt", self.prompt)
        form.addRow("Negative", self.negative)
        box.addLayout(form)

        row = QHBoxLayout()
        self.check_button = QPushButton("Check")
        self.create_button = QPushButton("Create project")
        self.create_button.setObjectName("primaryAction")
        self.cancel_button = QPushButton("Cancel")
        row.addWidget(self.check_button)
        row.addWidget(self.create_button)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        box.addLayout(row)
        self.summary = QLabel("Loading the backend defaults…")
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        self.issues = QListWidget()
        box.addWidget(self.issues, 1)

        self._apply_preset(0)
        for widget in (self.name,):
            widget.textChanged.connect(lambda _t: self._edited())
        for combo in (self.model, self.mode, self.start):
            combo.currentIndexChanged.connect(lambda _i: self._edited())
        for spin in (self.fps, self.frames):
            spin.valueChanged.connect(lambda _v: self._edited())
        for text in (self.prompt, self.negative):
            text.textChanged.connect(self._edited)
        self.size_preset.activated.connect(self._apply_preset)
        for spin in (self.width, self.height):
            spin.valueChanged.connect(lambda _v: self._size_edited())
        self.check_button.clicked.connect(self._check)
        self.create_button.clicked.connect(self._create)
        self.cancel_button.clicked.connect(self.reject)
        service.setup_ready.connect(self._ready)
        service.reviewed.connect(self._reviewed_by_backend)
        service.created.connect(self._created)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.load()
        self._update()

    # -- state ------------------------------------------------------------------------------

    def choices(self) -> Choices:
        entry = self.model.currentData()
        return Choices(
            name=self.name.text(), width=self.width.value(), height=self.height.value(),
            fps=self.fps.value(), frames=self.frames.value(), mode=self.mode.currentData(),
            start_mode=self.start.currentData(),
            model_id=entry.id if entry else "", family=(entry.family or "") if entry else "",
            variant=(entry.variant or "") if entry else "",
            prompt=self.prompt.toPlainText(), negative=self.negative.toPlainText())

    def _apply_preset(self, index: int) -> None:
        if index < len(SIZES):
            _label, width, height = SIZES[index]
            for spin, value in ((self.width, width), (self.height, height)):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        self._edited()

    def _size_edited(self) -> None:
        match = next((i for i, (_l, w, h) in enumerate(SIZES)
                      if (w, h) == (self.width.value(), self.height.value())), len(SIZES))
        self.size_preset.setCurrentIndex(match)
        self._edited()

    def _edited(self) -> None:
        self._reviewed = False
        seconds = self.frames.value() / self.fps.value() if self.fps.value() else 0
        self.length_label.setText(f"{seconds:.1f} seconds")
        if self._template is not None:
            self.summary.setText("Choose Check to review these settings with the backend.")
            self.issues.clear()
        self._update()

    def _update(self) -> None:
        idle = not self._service.busy and self._service.available and self._template is not None
        self.check_button.setEnabled(idle)
        self.create_button.setEnabled(idle and self._reviewed)

    # -- backend steps ------------------------------------------------------------------------

    def _ready(self, template: dict, checkpoints) -> None:
        self._template = template
        animation = template.get("animation") or {}
        self.model.blockSignals(True)
        for entry in checkpoints:
            self.model.addItem(f"{entry.name}  ({entry.family})", entry)
        self.model.blockSignals(False)
        self.fps.setValue(float(animation.get("fps") or 24))
        self.frames.setValue(int(animation.get("max_frames") or 120))
        self.width.setValue(int(animation.get("width") or 1024))
        self.height.setValue(int(animation.get("height") or 1024))
        self.summary.setText("Choose Check to review these settings with the backend.")
        self._edited()

    def _show_issues(self, issues) -> None:
        self.issues.clear()
        for issue in issues:
            self.issues.addItem(f"{'⚠' if issue.severity == 'warning' else '✖'} "
                                f"{issue.field or 'project'}: {issue.message}")

    def _check(self) -> None:
        local = check_choices(self.choices())
        if has_errors(local):
            self._show_issues(local)
            self.summary.setText("Fix the problems below, then Check again.")
            return
        self._local = local
        self.summary.setText("Asking the backend…")
        self._service.review(self._template, self.choices())

    def _reviewed_by_backend(self, validation) -> None:
        local = self._local
        self._show_issues(tuple(local) + validation.issues)
        if validation.errors:
            self.summary.setText(f"The backend found {len(validation.errors)} schedule error(s); "
                                 "the project cannot be created yet.")
            self._reviewed = False
        else:
            warnings = len(validation.warnings) + sum(1 for i in local if i.severity == "warning")
            self.summary.setText("Ready to create." + (f" {warnings} warning(s) to be aware of." if warnings else ""))
            self._reviewed = True
        self._update()

    def _create(self) -> None:
        if self._reviewed and self._template is not None:
            self.summary.setText("Creating…")
            self._reviewed = False
            self._service.create(self._template, self.choices())

    def _created(self, detail) -> None:
        self.project_created.emit(detail.id)
        self.accept()

    def _failed(self, operation: str, code: str, message: str) -> None:
        self.summary.setText(f"{operation.capitalize()} failed: {message}")
        self._update()
