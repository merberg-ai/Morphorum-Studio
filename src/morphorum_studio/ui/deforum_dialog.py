"""Import Deforum settings as a new project: choose file and checkpoint, preview, then create.

Nothing is created until the backend's own preview says the project can be created, and the
preview is thrown away whenever the file, checkpoint or name changes.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from morphorum_studio.backend.deforum import DeforumCreated, DeforumPreview, read_settings_file
from morphorum_studio.ui.import_service import ImportService



class DeforumImportDialog(QDialog):
    project_created = Signal(str)

    def __init__(self, service: ImportService, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Deforum settings")
        self.resize(760, 640)
        self._service = service
        self._text = ""
        self._filename = ""
        self._preview: DeforumPreview | None = None
        box = QVBoxLayout(self)
        intro = QLabel("Creates a new project from a Deforum settings file. The backend translates "
                       "it; unsupported settings are listed, never silently dropped.")
        intro.setWordWrap(True)
        box.addWidget(intro)

        row = QHBoxLayout()
        self.file_button = QPushButton("Choose settings file…")
        self.file_label = QLabel("No file chosen")
        row.addWidget(self.file_button)
        row.addWidget(self.file_label, 1)
        box.addLayout(row)
        row = QHBoxLayout()
        self.model = QComboBox()
        self.model.addItem("Choose a checkpoint…", None)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Project name (optional)")
        row.addWidget(QLabel("Checkpoint"))
        row.addWidget(self.model, 1)
        row.addWidget(self.name, 1)
        box.addLayout(row)

        row = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.create_button = QPushButton("Create project")
        self.create_button.setObjectName("primaryAction")
        self.close_button = QPushButton("Close")
        for button in (self.preview_button, self.create_button):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(self.close_button)
        box.addLayout(row)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        self.warnings = QListWidget()
        self.warnings.setMaximumHeight(120)
        box.addWidget(self.warnings)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Deforum setting", "Becomes", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        box.addWidget(self.table, 1)

        self.file_button.clicked.connect(self._choose_file)
        self.model.currentIndexChanged.connect(lambda _i: self._invalidate())
        self.name.textChanged.connect(lambda _t: self._invalidate())
        self.preview_button.clicked.connect(self._do_preview)
        self.create_button.clicked.connect(self._do_create)
        self.close_button.clicked.connect(self.close)
        service.models_ready.connect(self._models)
        service.preview_ready.connect(self._previewed)
        service.created.connect(self._created)
        service.failed.connect(self._failed)
        service.busy_changed.connect(lambda _b: self._update())
        service.load_models()
        self._update()

    def _model_id(self) -> str | None:
        return self.model.currentData()

    def _models(self, models) -> None:
        current = self._model_id()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItem("Choose a checkpoint…", None)
        for entry in models:
            self.model.addItem(f"{entry.name}  ({entry.family})", entry.id)
        index = self.model.findData(current)
        self.model.setCurrentIndex(max(0, index))
        self.model.blockSignals(False)
        self._update()

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Deforum settings", "",
                                              "Deforum settings (*.txt *.json);;All files (*)")
        if not path:
            return
        try:
            self._filename, self._text = read_settings_file(path)
        except ValueError as exc:
            self.summary.setText(str(exc))
            return
        self.file_label.setText(self._filename)
        self._invalidate()

    def _invalidate(self) -> None:
        self._preview = None
        self.table.setRowCount(0)
        self.warnings.clear()
        self.summary.setText("Choose Preview to see how the settings translate." if self._text else "")
        self._update()

    def _update(self) -> None:
        idle = not self._service.busy and self._service.available
        self.preview_button.setEnabled(idle and bool(self._text))
        self.create_button.setEnabled(
            idle and bool(self._preview and self._preview.can_create) and self._model_id() is not None)

    def _name(self) -> str | None:
        return self.name.text().strip() or None

    def _do_preview(self) -> None:
        self.summary.setText("Asking the backend…")
        self._service.preview(self._text, self._filename, self._model_id(), self._name())

    def _previewed(self, preview: DeforumPreview) -> None:
        self._preview = preview
        v = preview.validation
        bits = []
        if preview.frames:
            bits.append(f"{preview.frames} frames")
        if preview.fps:
            bits.append(f"{preview.fps:g} fps")
        if preview.size:
            bits.append(f"{preview.size[0]}×{preview.size[1]}")
        if preview.mode:
            bits.append(preview.mode.upper())
        counts = (f"{preview.count('mapped')} mapped, {preview.count('mapped_with_warning')} with warnings, "
                  f"{len(preview.unsupported)} unsupported, {len(preview.unmapped)} kept as metadata")
        verdict = ("Ready to create." if preview.can_create else
                   "Choose a checkpoint, then Preview again." if preview.model_required else
                   f"Cannot be created yet: {len(v.errors)} schedule error(s).")
        self.summary.setText(f"“{preview.project_name}” — {', '.join(bits)}\n{counts}\n{verdict}")
        self.warnings.clear()
        for issue in v.issues:
            self.warnings.addItem(f"{'⚠' if issue.severity == 'warning' else '✖'} {issue.field}: {issue.message}")
        for warning in preview.warnings:
            self.warnings.addItem(f"⚠ {warning}")
        self.table.setRowCount(len(preview.mappings))
        for row, item in enumerate(preview.mappings):
            self.table.setItem(row, 0, QTableWidgetItem(item.source_key))
            self.table.setItem(row, 1, QTableWidgetItem(item.target or "—"))
            status = item.status.replace("_", " ")
            self.table.setItem(row, 2, QTableWidgetItem(f"{status}: {item.message}" if item.message else status))
        self._update()

    def _do_create(self) -> None:
        if self._preview and self._preview.can_create and self._model_id():
            self.summary.setText("Creating…")
            self._service.create(self._text, self._filename, self._model_id(), self._name())

    def _created(self, created: DeforumCreated) -> None:
        self.project_created.emit(created.project_id)
        self.close()

    def _failed(self, operation: str, code: str, message: str) -> None:
        self.summary.setText(f"{operation.capitalize()} failed: {message}")
        self._update()
