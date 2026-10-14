"""Projects page (S2.2): browse, open, rename/annotate, create and trash backend projects.

Edits are saved with the revision (ETag) the project was loaded at. If the backend copy changed
in the meantime the save is refused and the user chooses to reload; nothing is overwritten
silently. Only the name and notes are editable here; everything else is shown read-only until
the editors arrive in S4.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from morphorum_studio.backend.projects import (
    MAX_NAME,
    MAX_NOTES,
    ProjectDetail,
    ProjectSummary,
    RenderSummary,
)
from morphorum_studio.backend.session import BackendSession
from morphorum_studio.ui.assets_card import AssetsCard
from morphorum_studio.ui.preferences import StudioPreferences
from morphorum_studio.ui.render_card import RenderCard
from morphorum_studio.ui.projects_service import ProjectsService

NA = "—"


def format_when(text: str | None) -> str:
    """ISO timestamp from the backend, shown in local time; unknown stays unknown."""
    if not text:
        return NA
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return NA
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def format_length(frames: int | None, fps: float | None) -> str:
    if not frames:
        return NA
    if not fps:
        return f"{frames} frames"
    return f"{frames} frames at {fps:g} fps ({frames / fps:.1f} s)"


def format_size(width: int | None, height: int | None) -> str:
    return f"{width}×{height}" if width and height else NA


def summary_line(p: ProjectSummary) -> str:
    bits = [format_size(p.width, p.height)]
    if p.max_frames and p.fps:
        bits.append(f"{p.max_frames / p.fps:.1f} s")
    bits.append(format_when(p.updated_at))
    return " · ".join(bit for bit in bits if bit != NA)


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class ProjectsPage(QFrame):
    open_connections = Signal()

    def __init__(self, session: BackendSession, service: ProjectsService,
                 preferences: StudioPreferences, render_service=None, video_service=None,
                 import_service=None, setup_service=None, models_service=None) -> None:
        super().__init__()
        self._render_service = render_service
        self._video_service = video_service
        self._import_service = import_service
        self._setup_service = setup_service
        self._models_service = models_service
        self.setObjectName("pageSurface")
        self._session = session
        self._service = service
        self._prefs = preferences
        self._active = False
        self._projects: tuple[ProjectSummary, ...] = ()
        self._selected: str | None = None  # id of the project shown on the right
        self._loaded: ProjectDetail | None = None
        self._etag: str | None = None
        self._conflict_for: str | None = None
        self._restore_pending = True  # Reopen the last project once per connection.
        self._build()
        session.changed.connect(self._session_changed)
        service.cleared.connect(self._cleared)
        service.listed.connect(self._listed)
        service.opened.connect(self._opened)
        service.created.connect(self._created)
        service.saved.connect(self._saved)
        service.trashed.connect(self._trashed)
        service.failed.connect(self._failed)
        service.peeked.connect(self._peeked)
        service.busy_changed.connect(lambda _busy: self._update_buttons())
        self._session_changed()

    # -- construction -------------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(38, 34, 38, 24)
        outer.setSpacing(12)
        outer.addWidget(_label("PROJECTS / STUDIO", "sectionCaption"))
        outer.addWidget(_label("Projects", "pageHeading"))
        self.status_line = _label("", "pageDescription", wrap=True)
        outer.addWidget(self.status_line)

        body = QHBoxLayout()
        body.setSpacing(16)
        outer.addLayout(body, 1)

        # -- left: list
        left = QFrame()
        left.setObjectName("card")
        left.setFixedWidth(340)
        lbox = QVBoxLayout(left)
        lbox.setContentsMargins(14, 14, 14, 14)
        lbox.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.new_button = QPushButton("New project")
        self.new_button.setObjectName("primaryAction")
        self.import_button = QPushButton("Import Deforum…")
        self.import_button.setVisible(self._import_service is not None)
        self.refresh_button = QPushButton("Refresh")
        self.models_button = QPushButton("Models and LoRAs…")
        self.models_button.setVisible(self._models_service is not None)
        for button in (self.new_button, self.import_button, self.refresh_button, self.models_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        head.addWidget(self.new_button)
        head.addStretch(1)
        head.addWidget(self.refresh_button)
        lbox.addLayout(head)
        more = QHBoxLayout()
        more.setSpacing(8)
        more.addWidget(self.import_button)
        more.addWidget(self.models_button)
        more.addStretch(1)
        lbox.addLayout(more)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search projects")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search projects")
        lbox.addWidget(self.search)
        self.recent_combo = QComboBox()
        self.recent_combo.setAccessibleName("Recently opened projects")
        lbox.addWidget(self.recent_combo)
        self.project_list = QListWidget()
        self.project_list.setObjectName("projectList")
        self.project_list.setAccessibleName("Projects")
        lbox.addWidget(self.project_list, 1)
        self.list_note = _label("", "hint", wrap=True)
        lbox.addWidget(self.list_note)
        self.connect_button = QPushButton("Open connection settings")
        self.connect_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lbox.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignLeft)
        body.addWidget(left)

        # -- right: detail
        self.detail_stack = QStackedWidget()
        body.addWidget(self.detail_stack, 1)
        self.empty_detail = _label("", "hint", wrap=True)
        self.empty_detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.detail_stack.addWidget(self.empty_detail)

        scroll = QScrollArea()
        scroll.setObjectName("connectionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("connectionsContent")
        scroll.setWidget(content)
        dbox = QVBoxLayout(content)
        dbox.setContentsMargins(0, 0, 8, 0)
        dbox.setSpacing(14)

        edit = QFrame()
        edit.setObjectName("card")
        ebox = QVBoxLayout(edit)
        ebox.setContentsMargins(20, 18, 20, 20)
        ebox.setSpacing(10)
        ebox.addWidget(_label("Project", "cardTitle"))
        ebox.addWidget(_label("Name", "fieldLabel"))
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(MAX_NAME)
        self.name_edit.setAccessibleName("Project name")
        ebox.addWidget(self.name_edit)
        self.id_label = _label("", "hint")
        self.id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ebox.addWidget(self.id_label)
        ebox.addWidget(_label("Notes", "fieldLabel"))
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(110)
        self.notes_edit.setMaximumHeight(200)
        self.notes_edit.setAccessibleName("Project notes")
        ebox.addWidget(self.notes_edit)
        self.dirty_label = _label("", "hint")
        ebox.addWidget(self.dirty_label)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.trash_button = QPushButton("Move to Trash")
        self.trash_button.setObjectName("dangerAction")
        self.reload_button = QPushButton("Reload")
        self.revert_button = QPushButton("Revert edits")
        self.save_button = QPushButton("Save changes")
        self.trash_button.setToolTip("Move this project to the backend's Trash")
        self.reload_button.setToolTip("Discard local edits and read the project from the backend again")
        self.revert_button.setToolTip("Undo your unsaved edits to the name and notes")
        self.save_button.setToolTip("Save the name and notes to the backend (Ctrl+S)")
        self.save_button.setObjectName("primaryAction")
        for button in (self.trash_button, self.reload_button, self.revert_button, self.save_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        actions.addWidget(self.trash_button)
        actions.addStretch(1)
        actions.addWidget(self.reload_button)
        actions.addWidget(self.revert_button)
        actions.addWidget(self.save_button)
        ebox.addLayout(actions)
        dbox.addWidget(edit)

        info = QFrame()
        info.setObjectName("card")
        ibox = QVBoxLayout(info)
        ibox.setContentsMargins(20, 18, 20, 20)
        ibox.setSpacing(10)
        ibox.addWidget(_label("Details", "cardTitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        self._info: dict[str, QLabel] = {}
        keys = ("Frame size", "Length", "Mode", "Start from", "Model", "Prompt keyframes",
                "First prompt", "Motion layers", "Source image", "Hybrid video", "Created",
                "Updated")
        for row, key in enumerate(keys):
            grid.addWidget(_label(key, "fieldLabel"), row, 0, Qt.AlignmentFlag.AlignTop)
            value = _label(NA, "metricValue", wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(value, row, 1)
            self._info[key] = value
        grid.setColumnStretch(1, 1)
        ibox.addLayout(grid)
        dbox.addWidget(info)

        self.assets_card = AssetsCard(self._service)
        self.assets_card.project_changed.connect(self._reload_after_asset_change)
        dbox.addWidget(self.assets_card)

        self.render_card = None
        if self._render_service is not None:
            self.render_card = RenderCard(self._render_service, self._video_service)
            dbox.addWidget(self.render_card)

        renders = QFrame()
        renders.setObjectName("card")
        rbox = QVBoxLayout(renders)
        rbox.setContentsMargins(20, 18, 20, 20)
        rbox.setSpacing(8)
        rbox.addWidget(_label("Recent renders", "cardTitle"))
        self.renders_label = _label("", "metricValue", wrap=True)
        rbox.addWidget(self.renders_label)
        dbox.addWidget(renders)
        dbox.addStretch(1)
        self.detail_stack.addWidget(scroll)

        self.search.textChanged.connect(self._apply_filter)
        self.project_list.currentItemChanged.connect(self._item_changed)
        self.recent_combo.activated.connect(self._recent_chosen)
        self.refresh_button.clicked.connect(self._service.refresh)
        self.new_button.clicked.connect(self._new_project)
        self.import_button.clicked.connect(self._import_deforum)
        self.models_button.clicked.connect(self._open_models)
        self.new_button.setToolTip("Create a project with the backend's defaults (Ctrl+N)")
        self.import_button.setToolTip('Create a new project from a Deforum settings file')
        self.refresh_button.setToolTip('Reload the project list (F5)')
        self.models_button.setToolTip('Browse the checkpoints and LoRAs the backend has indexed')
        self.connect_button.clicked.connect(self.open_connections)
        self.name_edit.textChanged.connect(self._edited)
        self.notes_edit.textChanged.connect(self._edited)
        self.save_button.clicked.connect(self._save)
        self.revert_button.clicked.connect(self._revert)
        self.reload_button.clicked.connect(self._reload)
        self.trash_button.clicked.connect(self._trash)

    # -- activation and session -----------------------------------------------------------

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and self._service.available:
            self._service.refresh()

    @property
    def profile_id(self) -> str | None:
        info = self._session.info
        return info.profile_id if info else None

    def _session_changed(self) -> None:
        if self._service.available:
            self.status_line.setText(
                "Projects stored on the connected backend. Changes are saved there, not on this computer.")
            self.connect_button.setVisible(False)
            if self._active:
                self._service.refresh()
        else:
            self._show_unavailable()
        self._update_buttons()

    def _show_unavailable(self) -> None:
        info = self._session.info
        if info is not None and self._session.feature("project_crud"):
            # Reconnecting: keep the list and any unsaved edits; controls are disabled meanwhile.
            text = "The backend is not responding. Studio is retrying."
            self.connect_button.setVisible(False)
            self.list_note.setText(text)
            self.status_line.setText(text)
            return
        self._clear_all()
        if info is None:
            text = "Connect to a Morphorum backend to browse its projects."
        else:
            text = "The connected backend does not advertise project support."
        self.status_line.setText(text)
        self.list_note.setText(text)
        self.connect_button.setVisible(True)

    def _cleared(self) -> None:
        self._restore_pending = True
        self._clear_all()

    def _clear_all(self) -> None:
        self._projects = ()
        self._selected = None
        self._loaded = None
        self._etag = None
        self.project_list.blockSignals(True)
        self.project_list.clear()
        self.project_list.blockSignals(False)
        self.recent_combo.clear()
        self._cards_project(None)
        self.detail_stack.setCurrentIndex(0)
        self.empty_detail.setText("")

    # -- list ---------------------------------------------------------------------------

    def _listed(self, projects: tuple[ProjectSummary, ...]) -> None:
        self._projects = projects
        self.list_note.setText("" if projects else "No projects on this backend yet. Create one with New project.")
        self._apply_filter()
        self._fill_recent()
        ids = {p.id for p in projects}
        if self._selected and self._selected not in ids and not self.has_unsaved_changes():
            self._selected = None
            self._loaded = None
            self._cards_project(None)
            self.detail_stack.setCurrentIndex(0)
        if self._restore_pending:
            self._restore_pending = False
            profile = self.profile_id
            last = next((p for p in self._prefs.recent_projects(profile) if p in ids), None) if profile else None
            if last and self._selected is None:
                self._select(last)
        if self._selected is None and not projects:
            self.empty_detail.setText("Create a project to get started.")
        elif self._selected is None:
            self.empty_detail.setText("Select a project to see its details.")

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().lower()
        self.project_list.blockSignals(True)
        self.project_list.clear()
        keep = None
        for project in self._projects:
            if needle and needle not in project.name.lower() and needle not in project.id:
                continue
            item = QListWidgetItem(f"{project.name}\n{summary_line(project)}")
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            item.setToolTip(project.id)
            self.project_list.addItem(item)
            if project.id == self._selected:
                keep = item
        if keep is not None:
            self.project_list.setCurrentItem(keep)
        self.project_list.blockSignals(False)
        if needle and self.project_list.count() == 0 and self._projects:
            self.list_note.setText("No project matches the search.")
        elif self._projects:
            self.list_note.setText("")

    def _fill_recent(self) -> None:
        self.recent_combo.blockSignals(True)
        self.recent_combo.clear()
        self.recent_combo.addItem("Recently opened…", None)
        names = {p.id: p.name for p in self._projects}
        profile = self.profile_id
        for project_id in (self._prefs.recent_projects(profile) if profile else []):
            if project_id in names:
                self.recent_combo.addItem(names[project_id], project_id)
        self.recent_combo.blockSignals(False)
        self.recent_combo.setEnabled(self.recent_combo.count() > 1)

    def _recent_chosen(self, index: int) -> None:
        project_id = self.recent_combo.itemData(index)
        self.recent_combo.setCurrentIndex(0)
        if project_id:
            self._select(project_id)

    def _item_changed(self, current, previous) -> None:
        if current is None:
            return
        self._select(current.data(Qt.ItemDataRole.UserRole), from_list=True)

    # -- selection and opening ------------------------------------------------------------

    def open_project(self, project_id: str) -> None:
        """Open a project by id (used by Home tiles); asks before discarding unsaved edits."""
        self._select(project_id)

    def _select(self, project_id: str, from_list: bool = False) -> None:
        if project_id == self._selected and self._loaded is not None:
            return
        if self.has_unsaved_changes() and not self._confirm_discard():
            # Put the list back on the project being edited.
            self._apply_filter()
            return
        self._selected = project_id
        self._loaded = None
        self._etag = None
        self._cards_project(None)
        self.detail_stack.setCurrentIndex(0)
        self.empty_detail.setText("Opening project…")
        self._apply_filter()
        self._service.open(project_id)
        self._update_buttons()

    def _confirm_discard(self) -> bool:
        answer = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes to this project. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Discard

    def _opened(self, detail: ProjectDetail, etag: str, renders) -> None:
        if detail.id != self._selected:
            return
        self._fill_detail(detail, etag)
        self._show_renders(renders)
        profile = self.profile_id
        if profile:
            self._prefs.remember_project(profile, detail.id)
            self._fill_recent()

    def _fill_detail(self, detail: ProjectDetail, etag: str) -> None:
        self._loaded, self._etag = detail, etag
        for edit in (self.name_edit, self.notes_edit):
            edit.blockSignals(True)
        self.name_edit.setText(detail.name)
        self.notes_edit.setPlainText(detail.notes)
        for edit in (self.name_edit, self.notes_edit):
            edit.blockSignals(False)
        self.id_label.setText("ID: " + detail.id)
        self.assets_card.set_start_mode(detail.start_mode)
        info = self._info
        info["Frame size"].setText(format_size(detail.width, detail.height))
        info["Length"].setText(format_length(detail.max_frames, detail.fps))
        info["Mode"].setText((detail.mode or NA).upper() if detail.mode else NA)
        info["Start from"].setText(detail.start_mode or NA)
        model = " · ".join(x for x in (detail.model_family, detail.model_id, detail.model_variant) if x)
        info["Model"].setText(model or "None chosen yet")
        info["Prompt keyframes"].setText(str(detail.prompt_keyframes))
        info["First prompt"].setText(detail.first_prompt or "Empty")
        info["Motion layers"].setText(str(detail.motion_layers))
        info["Source image"].setText(detail.source_image_name or "None")
        info["Hybrid video"].setText("On" if detail.hybrid_enabled else "Off")
        info["Created"].setText(format_when(detail.created_at))
        info["Updated"].setText(format_when(detail.updated_at))
        self.detail_stack.setCurrentIndex(1)
        self._cards_project(detail.id)
        self._edited()

    def _show_renders(self, renders: tuple[RenderSummary, ...] | None) -> None:
        if renders is None:
            self.renders_label.setText("Render history is unavailable right now.")
        elif not renders:
            self.renders_label.setText("No renders yet.")
        else:
            lines = []
            for render in renders[:5]:
                frame = "no frames yet" if render.latest_frame is None else f"frame {render.latest_frame}"
                lines.append(f"{format_when(render.created_at)} · {render.status or NA} · {frame}")
            more = len(renders) - 5
            if more > 0:
                lines.append(f"…and {more} more")
            self.renders_label.setText("\n".join(lines))

    # -- editing --------------------------------------------------------------------------

    def has_unsaved_changes(self) -> bool:
        loaded = self._loaded
        if loaded is None or self.detail_stack.currentIndex() != 1:
            return False
        return (self.name_edit.text().strip() != loaded.name
                or self.notes_edit.toPlainText() != loaded.notes)

    def _edited(self) -> None:
        self.dirty_label.setText("Unsaved changes" if self.has_unsaved_changes() else "")
        self._cards_locked(self.has_unsaved_changes())
        self._update_buttons()

    def _update_buttons(self) -> None:
        available = self._service.available
        busy = self._service.mutating
        dirty = self.has_unsaved_changes()
        valid = bool(self.name_edit.text().strip()) and len(self.notes_edit.toPlainText()) <= MAX_NOTES
        has_project = self._loaded is not None
        self.new_button.setEnabled(available and not busy)
        self.import_button.setEnabled(available and not busy)
        self.models_button.setEnabled(available)
        self.refresh_button.setEnabled(available)
        self.save_button.setEnabled(available and not busy and dirty and valid)
        self.revert_button.setEnabled(dirty and not busy)
        self.reload_button.setEnabled(available and has_project and not busy)
        self.trash_button.setEnabled(available and has_project and not busy)
        for widget in (self.name_edit, self.notes_edit):
            widget.setEnabled(available and not busy)

    def _cards_project(self, project_id: str | None) -> None:
        self.assets_card.set_project(project_id)
        if self.render_card is not None:
            self.render_card.set_project(project_id)

    def _cards_locked(self, locked: bool) -> None:
        self.assets_card.set_locked(locked)
        if self.render_card is not None:
            self.render_card.set_locked(locked)

    def _reload_after_asset_change(self) -> None:
        # The source image changed the project's revision; fetch the new ETag (form is clean).
        if self._selected:
            self._service.open(self._selected)

    def _revert(self) -> None:
        if self._loaded is not None and self._etag is not None:
            self._fill_detail(self._loaded, self._etag)

    def _reload(self) -> None:
        if self._selected is None:
            return
        if self.has_unsaved_changes() and not self._confirm_discard():
            return
        self._service.open(self._selected)

    def _save(self) -> None:
        if self._loaded is None or self._etag is None:
            return
        self._service.save(self._loaded.id, self._etag, self.name_edit.text(),
                           self.notes_edit.toPlainText())

    def _saved(self, detail: ProjectDetail, etag: str) -> None:
        if detail.id == self._selected:
            self._fill_detail(detail, etag)
        self.dirty_label.setText("Saved")
        self._service.refresh()

    # -- create and trash -----------------------------------------------------------------

    def _new_project(self) -> None:
        if self.has_unsaved_changes() and not self._confirm_discard():
            return
        if self._setup_service is not None:
            from morphorum_studio.ui.setup_dialog import NewProjectDialog
            dialog = NewProjectDialog(self._setup_service, self)
            dialog.project_created.connect(self._imported)
            self.setup_dialog = dialog
            dialog.open()
            return
        name, accepted = QInputDialog.getText(
            self, "New project", "Project name:", QLineEdit.EchoMode.Normal, "Untitled Animation")
        if accepted and name.strip():
            self._service.create(name)

    def _open_models(self) -> None:
        if self._models_service is None:
            return
        from morphorum_studio.ui.models_dialog import ModelsDialog
        dialog = ModelsDialog(self._models_service, self)
        self.models_dialog = dialog
        dialog.open()

    def _import_deforum(self) -> None:
        if self._import_service is None:
            return
        if self.has_unsaved_changes() and not self._confirm_discard():
            return
        from morphorum_studio.ui.deforum_dialog import DeforumImportDialog
        dialog = DeforumImportDialog(self._import_service, self)
        dialog.project_created.connect(self._imported)
        self.import_dialog = dialog
        dialog.open()

    def _imported(self, project_id: str) -> None:
        self._loaded = None
        self._selected = None
        self._service.refresh()
        self._select(project_id)

    def _created(self, detail: ProjectDetail) -> None:
        self._loaded = None  # Anything unsaved was already discarded when the user chose New.
        self._selected = None
        self._service.refresh()
        self._select(detail.id)

    def _trash(self) -> None:
        if self._loaded is None:
            return
        answer = QMessageBox.question(
            self, "Move to Trash",
            f"Move '{self._loaded.name}' to the backend's Trash?\n\n"
            "Rendered output is not deleted. The backend refuses if the project is rendering.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._service.trash(self._loaded.id)

    def _trashed(self, project_id: str) -> None:
        profile = self.profile_id
        if profile:
            self._prefs.forget_project(profile, project_id)
        if project_id == self._selected:
            self._selected = None
            self._loaded = None
            self._cards_project(None)
            self.detail_stack.setCurrentIndex(0)
            self.empty_detail.setText("Project moved to the backend's Trash.")
        self._service.refresh()

    # -- errors ---------------------------------------------------------------------------

    def _failed(self, operation: str, code: str, message: str) -> None:
        if operation == "list":
            self.list_note.setText(f"Could not load projects ({code}). Use Refresh to retry.")
        elif operation == "open":
            self.empty_detail.setText(f"Could not open this project ({code}).")
            self.detail_stack.setCurrentIndex(0)
            self._loaded = None
            self._cards_project(None)
        elif operation == "assets":
            self.dirty_label.setText(f"Could not load project media ({code}).")
        elif operation == "save" and code == "PRECONDITION_FAILED":
            self._conflict_for = self._selected
            if self._selected:
                self._service.peek(self._selected)
            else:
                self._conflict(None)
        else:
            extra = ""
            if operation == "create" and code in ("NETWORK_ERROR", "CONNECTION_ERROR"):
                extra = ("\n\nThe request may have reached the backend before the connection "
                         "dropped. Check the project list before trying again.")
                self._service.refresh()
            titles = {"save": "Could not save", "create": "Could not create the project",
                      "trash": "Could not move to Trash",
                      "source_upload": "Could not upload the image",
                      "source_clear": "Could not remove the image",
                      "start_mode": "Could not change the start mode",
                      "audio_attach": "Could not attach the soundtrack",
                      "audio_offset": "Could not change the offset",
                      "copy": "Could not save the copy"}
            QMessageBox.warning(self, titles.get(operation, "Request failed"), message + extra)
        self._update_buttons()

    def _peeked(self, project_id: str, detail) -> None:
        if project_id != self._conflict_for or project_id != self._selected:
            return
        self._conflict_for = None
        self._conflict(detail)

    @staticmethod
    def _excerpt(text: str, limit: int = 160) -> str:
        text = " ".join(text.split())
        if not text:
            return "(empty)"
        return text if len(text) <= limit else text[:limit] + "…"

    def _conflict(self, theirs: ProjectDetail | None = None) -> None:
        mine_name, mine_notes = self.name_edit.text().strip(), self.notes_edit.toPlainText()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Project changed on the backend")
        box.setText("Another client saved this project after you opened it, so your changes were not saved.")
        lines = []
        if theirs is not None:
            if theirs.name != mine_name:
                lines.append(f"Name — yours: {self._excerpt(mine_name)}\n         backend: {self._excerpt(theirs.name)}")
            if theirs.notes != mine_notes:
                lines.append(f"Notes — yours: {self._excerpt(mine_notes)}\n          backend: {self._excerpt(theirs.notes)}")
            if not lines:
                lines.append("The backend's name and notes now match yours; something else in the project changed.")
        box.setInformativeText(
            "Your edits are still in the form.\n\n" + ("\n\n".join(lines) + "\n\n" if lines else "")
            + "Reload to take the backend's version (your edits are discarded), or keep editing.")
        reload_button = box.addButton("Reload from backend", QMessageBox.ButtonRole.DestructiveRole)
        copy_button = box.addButton("Copy my edits, keep editing", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Keep editing", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is copy_button:
            QApplication.clipboard().setText(f"{mine_name}\n\n{mine_notes}")
        elif clicked is reload_button and self._selected:
            self._service.open(self._selected)
