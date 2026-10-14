"""Project media card (S2.3): source image and imported soundtrack for the open project.

The backend owns the files. Studio uploads a chosen file with its SHA-256, shows what the backend
reports, and can save verified copies. Replacing or removing the source image changes the project
revision, so it is only offered while the form has no unsaved edits, and the page reloads the
project afterwards.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from morphorum_studio.backend.assets import (
    AUDIO_EXTENSIONS,
    OFFSET_LIMIT,
    SOURCE_EXTENSIONS,
    Asset,
    Soundtrack,
)
from morphorum_studio.ui.projects_service import ProjectsService

NA = "—"


def format_bytes(size: int | None) -> str:
    if not size:
        return NA
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return NA


def _filter(label: str, extensions: tuple[str, ...]) -> str:
    return f"{label} ({' '.join('*' + e for e in extensions)});;All files (*)"


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class AssetsCard(QFrame):
    project_changed = Signal()  # the project revision moved on the backend: reload it

    def __init__(self, service: ProjectsService) -> None:
        super().__init__()
        self.setObjectName("card")
        self._service = service
        self._project: str | None = None
        self._assets: tuple[Asset, ...] = ()
        self._soundtrack: Soundtrack | None = None
        self._locked = False
        self._start = "prompt"
        self._build()
        service.assets_loaded.connect(self._loaded)
        service.preview_loaded.connect(self._preview)
        service.asset_changed.connect(self._changed)
        service.copy_saved.connect(self._copied)
        service.busy_changed.connect(lambda _b: self._update())
        service.cleared.connect(lambda: self.set_project(None))
        self._update()

    # -- construction -----------------------------------------------------------------------

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 20)
        box.setSpacing(12)
        box.addWidget(_label("Project media", "cardTitle"))

        box.addWidget(_label("Source image", "fieldLabel"))
        row = QHBoxLayout()
        row.setSpacing(14)
        self.thumb = QLabel("No image")
        self.thumb.setObjectName("assetThumb")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFixedSize(168, 108)
        row.addWidget(self.thumb)
        column = QVBoxLayout()
        column.setSpacing(8)
        self.source_text = _label(NA, "metricValue", wrap=True)
        column.addWidget(self.source_text)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.source_choose = QPushButton("Choose image…")
        self.source_remove = QPushButton("Remove")
        self.source_remove.setObjectName("dangerAction")
        self.source_copy = QPushButton("Save copy…")
        for button in (self.source_choose, self.source_remove, self.source_copy):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            buttons.addWidget(button)
        buttons.addStretch(1)
        column.addLayout(buttons)
        column.addStretch(1)
        row.addLayout(column, 1)
        box.addLayout(row)
        self.source_note = _label("", "hint", wrap=True)
        box.addWidget(self.source_note)
        start_row = QHBoxLayout()
        start_row.setSpacing(8)
        start_row.addWidget(_label("Start from", "fieldLabel"))
        self.start_mode = QComboBox()
        self.start_mode.addItem("The prompt (text to image)", "prompt")
        self.start_mode.addItem("The source image (image to image)", "source")
        self.start_mode.setAccessibleName("How the first frame starts")
        start_row.addWidget(self.start_mode)
        start_row.addStretch(1)
        box.addLayout(start_row)
        self.start_note = _label("", "hint", wrap=True)
        box.addWidget(self.start_note)

        box.addWidget(_label("Soundtrack", "fieldLabel"))
        self.audio_text = _label(NA, "metricValue", wrap=True)
        box.addWidget(self.audio_text)
        audio_row = QHBoxLayout()
        audio_row.setSpacing(8)
        audio_row.addWidget(_label("Offset", "fieldLabel"))
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-OFFSET_LIMIT, OFFSET_LIMIT)
        self.offset.setDecimals(2)
        self.offset.setSingleStep(0.1)
        self.offset.setSuffix(" s")
        self.offset.setAccessibleName("Soundtrack offset in seconds")
        self.offset.setFixedWidth(110)
        audio_row.addWidget(self.offset)
        self.offset_apply = QPushButton("Apply offset")
        self.audio_choose = QPushButton("Attach audio…")
        self.audio_copy = QPushButton("Save copy…")
        for button in (self.offset_apply, self.audio_choose, self.audio_copy):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            audio_row.addWidget(button)
        audio_row.addStretch(1)
        box.addLayout(audio_row)
        self.audio_note = _label(
            "WAV, MP3, OGG or FLAC up to 40 MiB. A positive offset delays the audio.", "hint", wrap=True)
        box.addWidget(self.audio_note)

        self.source_choose.clicked.connect(self._choose_source)
        self.source_remove.clicked.connect(self._remove_source)
        self.source_copy.clicked.connect(lambda: self._save_copy("source_image"))
        self.audio_choose.clicked.connect(self._choose_audio)
        self.audio_copy.clicked.connect(lambda: self._save_copy("soundtrack"))
        self.offset_apply.clicked.connect(self._apply_offset)
        self.offset.valueChanged.connect(lambda _v: self._update())
        self.start_mode.activated.connect(self._start_mode_chosen)

    # -- state ------------------------------------------------------------------------------

    def set_project(self, project_id: str | None) -> None:
        if project_id == self._project:
            return
        self._project = project_id
        self._assets = ()
        self._soundtrack = None
        self._show_source(None)
        self._show_soundtrack(None)
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText("No image")
        if project_id:
            self._service.load_assets(project_id)
        self._update()

    def set_locked(self, locked: bool) -> None:
        """True while the project form has unsaved edits (source image changes are paused)."""
        if locked != self._locked:
            self._locked = locked
            self._update()

    def set_start_mode(self, mode: str | None) -> None:
        """The project's saved start mode (``prompt`` or ``source``)."""
        self._start = "source" if mode == "source" else "prompt"
        self._update()

    def _start_mode_chosen(self, _index: int) -> None:
        mode = self.start_mode.currentData()
        if self._project and mode != self._start:
            self._service.set_start_mode(self._project, mode)

    def _asset(self, kind: str) -> Asset | None:
        return next((a for a in self._assets if a.kind == kind), None)

    def _update(self) -> None:
        ready = (self._project is not None and self._service.available
                 and not self._service.mutating)
        source, audio = self._asset("source_image"), self._asset("soundtrack")
        self.source_choose.setEnabled(ready and not self._locked)
        self.source_remove.setEnabled(ready and not self._locked and source is not None)
        self.source_copy.setEnabled(ready and not self._service.copying and source is not None)
        self.source_note.setText(
            "Save or revert your edits first: changing the source image updates the project." if self._locked
            else "PNG, JPEG, WebP or BMP up to 32 MiB. The backend stores it as PNG.")
        self.start_mode.blockSignals(True)
        self.start_mode.setCurrentIndex(self.start_mode.findData(self._start))
        self.start_mode.blockSignals(False)
        self.start_mode.setEnabled(ready and not self._locked)
        self.start_mode.model().item(1).setEnabled(source is not None or self._start == "source")
        self.start_note.setText(
            "Image to image is selected but no source image is attached; attach one before rendering."
            if self._start == "source" and source is None
            else "Image to image starts frame 0 from the source image; strength controls how far it changes."
            if self._start == "source"
            else "Attach a source image to start from it instead of the prompt.")
        self.audio_choose.setEnabled(ready)
        self.audio_copy.setEnabled(ready and not self._service.copying and audio is not None)
        changed = (self._soundtrack is not None
                   and abs(self.offset.value() - self._soundtrack.offset_seconds) >= 0.005)
        self.offset.setEnabled(ready and self._soundtrack is not None)
        self.offset_apply.setEnabled(ready and changed)
        self.audio_choose.setText("Replace audio…" if self._soundtrack else "Attach audio…")

    def _show_source(self, asset: Asset | None) -> None:
        if asset is None:
            self.source_text.setText("No source image attached.")
        else:
            self.source_text.setText(
                f"{asset.filename} · {format_bytes(asset.size)}\nSHA-256 {asset.sha256[:12]}…")

    def _show_soundtrack(self, track: Soundtrack | None) -> None:
        self.offset.blockSignals(True)
        self.offset.setValue(track.offset_seconds if track else 0.0)
        self.offset.blockSignals(False)
        if track is None:
            self.audio_text.setText("No soundtrack attached.")
        else:
            self.audio_text.setText(
                f"{track.filename} · {track.format.upper()} · {format_bytes(track.size)}\n"
                f"SHA-256 {track.sha256[:12]}…")

    # -- backend results --------------------------------------------------------------------

    def _loaded(self, project_id: str, assets, soundtrack) -> None:
        if project_id != self._project:
            return
        self._assets, self._soundtrack = assets, soundtrack
        source = self._asset("source_image")
        self._show_source(source)
        self._show_soundtrack(soundtrack)
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText("Loading…" if source else "No image")
        if source:
            self._service.load_preview(project_id, source)
        self._update()

    def _preview(self, project_id: str, data) -> None:
        if project_id != self._project:
            return
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self.thumb.setText("")
            self.thumb.setPixmap(pixmap.scaled(
                self.thumb.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("No preview")

    def _changed(self, operation: str, project_id: str, soundtrack) -> None:
        if project_id != self._project:
            return
        self._service.load_assets(project_id)
        if operation in ("source_upload", "source_clear", "start_mode"):
            self.project_changed.emit()
        self._update()

    def _copied(self, path: str) -> None:
        self.audio_note.setText(f"Saved a verified copy to {path}")

    # -- user actions -----------------------------------------------------------------------

    def _choose_source(self) -> None:
        if not self._project:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose source image", "", _filter("Images", SOURCE_EXTENSIONS))
        if path:
            self._service.upload_source(self._project, path)

    def _remove_source(self) -> None:
        if not self._project:
            return
        answer = QMessageBox.question(
            self, "Remove source image",
            "Remove this project's source image from the backend?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._service.clear_source(self._project)

    def _choose_audio(self) -> None:
        if not self._project:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose soundtrack", "", _filter("Audio", AUDIO_EXTENSIONS))
        if path:
            self._service.attach_soundtrack(self._project, path, self.offset.value())

    def _apply_offset(self) -> None:
        if self._project:
            self._service.set_offset(self._project, self.offset.value())

    def _save_copy(self, kind: str) -> None:
        asset = self._asset(kind)
        if not self._project or asset is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save a copy", asset.filename)
        if path:
            self._service.save_copy(self._project, asset, path)
