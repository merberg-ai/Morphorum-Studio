"""Design tokens and the Qt stylesheet generated from them.

Every colour, radius and font used by the Studio shell lives here so that a
second theme later is just another ``Tokens`` instance. QSS has no variables,
so the stylesheet is a ``string.Template`` filled from the token fields.

Notes on Qt stylesheet limits that shaped this file: QSS does not support
``letter-spacing`` or CSS variables, ``rgba()`` alpha is 0-255 (not 0-1), and
gradients must use ``qlineargradient``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from string import Template


@dataclass(frozen=True)
class Tokens:
    # Surfaces, darkest to lightest
    void: str = "#04050a"
    base: str = "#070912"
    panel: str = "#0b0e1a"
    raised: str = "#11152a"
    hover: str = "#181d37"
    # Hairlines (periwinkle at 13% / 26%)
    line: str = "rgba(132, 152, 255, 33)"
    line2: str = "rgba(132, 152, 255, 66)"
    # Text
    text: str = "#e8ecff"
    dim: str = "#9aa3c9"
    faint: str = "#646d96"
    # Accent
    cyan: str = "#38d8ff"
    blue: str = "#4f7dff"
    violet: str = "#9468ff"
    grad_a: str = "#2fd3ff"
    grad_b: str = "#5a7cff"
    grad_c: str = "#9a6bff"
    # Status
    ok: str = "#3ddc97"
    warn: str = "#f6b94c"
    bad: str = "#ff5d73"
    # Type
    font_display: str = "Sora"
    font_ui: str = "Geist"
    font_mono: str = "Geist Mono"

    def colors(self) -> dict[str, str]:
        """Plain ``#rrggbb`` tokens (those QColor can parse directly)."""
        return {k: v for k, v in asdict(self).items() if v.startswith("#")}


DARK = Tokens()

_QSS = Template(
    """
* {
    font-family: "$font_ui", "Segoe UI Variable Text", "Segoe UI", "Arial", sans-serif;
    font-size: 13px;
}
QWidget {
    background: $base;
    color: $text;
}
QLabel, QCheckBox, QRadioButton, QToolButton {
    background: transparent;
}
QToolTip {
    background: $raised;
    color: $text;
    border: 1px solid $line2;
    padding: 4px 8px;
}
QMainWindow, QWidget#shell {
    background: $base;
}
QWidget#shell {
    border: 1px solid $line2;
}

/* ---------- title bar ---------- */
QWidget#titleBar {
    background: $void;
    border-bottom: 1px solid $line;
}
QLabel#brandName {
    font-family: "$font_display", "Segoe UI", sans-serif;
    font-size: 13px;
    font-weight: 600;
    color: $text;
}
QLabel#brandSub {
    font-family: "$font_display", "Segoe UI", sans-serif;
    font-size: 10px;
    font-weight: 500;
    color: $faint;
}
QToolButton#menuButton {
    padding: 5px 9px;
    border-radius: 6px;
    color: $dim;
    border: none;
}
QToolButton#menuButton:hover, QToolButton#menuButton:pressed {
    background: $raised;
    color: $text;
}
QToolButton#menuButton::menu-indicator {
    image: none;
    width: 0px;
}
QToolButton#winButton, QToolButton#winClose {
    border: none;
    border-radius: 0px;
    background: transparent;
}
QToolButton#winButton:hover {
    background: $raised;
}
QToolButton#winClose:hover {
    background: #c8344a;
}
QPushButton#searchButton {
    min-height: 0px;
    padding: 0px 58px 0px 10px;
    text-align: left;
    border-radius: 13px;
    border: 1px solid $line2;
    background: $panel;
    color: $faint;
    font-size: 12px;
}
QPushButton#searchButton:hover {
    background: $raised;
    color: $dim;
    border-color: $cyan;
}
QLabel#searchHint {
    color: $faint;
    background: transparent;
    font-family: "$font_mono", "Consolas", monospace;
    font-size: 10px;
}
QLabel#hostChip {
    color: $dim;
    font-family: "$font_mono", "Consolas", monospace;
    font-size: 11px;
}
QPushButton#connectionPill {
    min-height: 0px;
    padding: 3px 12px 3px 8px;
    border-radius: 12px;
    border: 1px solid $line2;
    background: $panel;
    color: $dim;
    font-family: "$font_mono", "Consolas", monospace;
    font-size: 11px;
    font-weight: 500;
}
QPushButton#connectionPill:hover {
    background: $raised;
}
QPushButton#connectionPill[state="connected"] {
    background: rgba(61, 220, 151, 23);
    border-color: rgba(61, 220, 151, 71);
    color: #9ff0c9;
}
QPushButton#connectionPill[state="busy"] {
    background: rgba(246, 185, 76, 23);
    border-color: rgba(246, 185, 76, 71);
    color: #ffd592;
}
QPushButton#connectionPill[state="error"] {
    background: rgba(255, 93, 115, 23);
    border-color: rgba(255, 93, 115, 71);
    color: #ff9aaa;
}

/* ---------- menus ---------- */
QMenu {
    background: $panel;
    border: 1px solid $line2;
    border-radius: 8px;
    padding: 5px;
}
QMenu::item {
    padding: 6px 26px 6px 12px;
    border-radius: 5px;
    color: $text;
}
QMenu::item:selected {
    background: $hover;
}
QMenu::separator {
    height: 1px;
    background: $line;
    margin: 4px 6px;
}

/* ---------- icon rail ---------- */
QFrame#rail {
    background: $void;
    border: none;
    border-right: 1px solid $line;
}
QToolButton#railItem {
    border: none;
    border-radius: 10px;
    color: $faint;
    font-size: 10px;
    padding: 6px 0px 4px 0px;
}
QToolButton#railItem:hover {
    background: $panel;
    color: $dim;
}
QToolButton#railItem:checked {
    color: $text;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(79, 125, 255, 51), stop:1 rgba(148, 104, 255, 26));
    border: 1px solid $line2;
}
QToolButton#railItem:focus {
    border: 2px solid $cyan;
}

/* ---------- status bar ---------- */
QFrame#footer {
    background: $void;
    border-top: 1px solid $line;
}
QLabel#footerStat {
    color: $dim;
    font-family: "$font_mono", "Consolas", monospace;
    font-size: 11px;
}
QLabel#footerText {
    color: $faint;
    font-family: "$font_mono", "Consolas", monospace;
    font-size: 11px;
}

/* ---------- Lab: batch thumbnails and aspect tiles ---------- */
QToolButton#thumb {
    border: 1px solid $line2;
    border-radius: 8px;
    background: $base;
    padding: 4px;
    color: $dim;
    font-size: 11px;
}
QToolButton#thumb:hover {
    border-color: $dim;
}
QToolButton#thumb[selected="true"] {
    border: 2px solid $cyan;
    color: $text;
}
QToolButton#aspectTile {
    border: 1px solid $line2;
    border-radius: 8px;
    background: $base;
    padding: 4px;
    color: $dim;
    font-size: 11px;
}
QToolButton#aspectTile:hover {
    border-color: $dim;
}
QToolButton#aspectTile:checked {
    border: 2px solid $cyan;
    color: $text;
    background: $raised;
}

/* ---------- segmented tabs (Library) ---------- */
QPushButton#segButton {
    min-height: 0px;
    padding: 6px 16px;
    border-radius: 14px;
    border: 1px solid $line2;
    background: transparent;
    color: $dim;
    font-weight: 500;
}
QPushButton#segButton:hover {
    background: $raised;
    color: $text;
}
QPushButton#segButton:checked {
    background: rgba(79, 125, 255, 46);
    border-color: rgba(79, 125, 255, 120);
    color: $text;
}

/* ---------- command palette ---------- */
QDialog#palette {
    background: $panel;
    border: 1px solid $line2;
    border-radius: 10px;
}
QListWidget#paletteResults {
    background: transparent;
    border: none;
    font-size: 13px;
}
QListWidget#paletteResults::item {
    padding: 7px 10px;
    border-radius: 6px;
}
QListWidget#paletteResults::item:selected {
    background: $raised;
    color: $text;
}

/* ---------- pages ---------- */
QWidget#pages, QStackedWidget#pages {
    background: $base;
}
QFrame#pageSurface {
    background: $base;
    border: none;
}
QLabel#pageHeading {
    font-family: "$font_display", "Segoe UI", sans-serif;
    color: $text;
    font-size: 28px;
    font-weight: 600;
}
QLabel#pageDescription, QLabel#panelDescription {
    color: $dim;
    font-size: 14px;
}
QLabel#sidebarCaption, QLabel#sectionCaption {
    color: $faint;
    font-size: 10px;
    font-weight: 500;
}
QFrame#infoPanel, QGroupBox {
    background: $panel;
    border: 1px solid $line2;
    border-radius: 14px;
}
QGroupBox {
    font-size: 13px;
    font-weight: 600;
    margin-top: 15px;
    padding: 18px 14px 12px 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 7px;
    color: $dim;
    background: $base;
}

/* ---------- buttons ---------- */
QPushButton {
    background: $raised;
    border: 1px solid $line2;
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 20px;
    color: $text;
    font-weight: 500;
}
QPushButton:hover {
    background: $hover;
}
QPushButton:pressed {
    background: $panel;
    border-color: $violet;
}
QPushButton:focus {
    border: 2px solid $cyan;
}
QPushButton:disabled {
    background: $panel;
    color: $faint;
    border-color: $line;
}
QPushButton#primaryAction {
    border: none;
    color: #05060d;
    font-weight: 600;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 $grad_a, stop:0.55 $grad_b, stop:1 $grad_c);
}
QPushButton#primaryAction:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6fe3ff, stop:0.55 #86a0ff, stop:1 #b595ff);
}
QPushButton#primaryAction:pressed {
    background: $grad_b;
}
QPushButton#primaryAction:focus {
    border: 2px solid #ffffff;
}
QPushButton#primaryAction:disabled {
    background: $raised;
    color: $faint;
}
QPushButton#dangerAction {
    background: rgba(255, 93, 115, 31);
    border: 1px solid rgba(255, 93, 115, 102);
    color: #ff9aaa;
}
QPushButton#dangerAction:hover {
    background: rgba(255, 93, 115, 56);
}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background: $base;
    border: 1px solid $line2;
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 20px;
    selection-background-color: $blue;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus,
QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid $cyan;
}
QPlainTextEdit#consoleView {
    background: $void;
    font-family: "$font_mono", "Consolas", monospace;
    font-size: 12px;
}
QLineEdit:read-only {
    color: $dim;
    background: $panel;
}
QLineEdit:disabled, QComboBox:disabled {
    color: $faint;
    background: $panel;
}
QComboBox {
    padding-right: 28px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border: none;
    border-left: 1px solid $line;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    background: $raised;
}
QComboBox QAbstractItemView {
    background: $panel;
    color: $text;
    border: 1px solid $line2;
    padding: 4px;
    selection-background-color: $hover;
    outline: none;
}
QCheckBox {
    spacing: 9px;
    color: $dim;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid $line2;
    background: $base;
}
QCheckBox::indicator:hover {
    border-color: $cyan;
}
QCheckBox::indicator:checked {
    background: $blue;
    border: 1px solid $cyan;
}

/* ---------- scrolling ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 3px;
    border: none;
}
QScrollBar::handle:vertical {
    background: $hover;
    min-height: 26px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:disabled, QScrollBar::handle:horizontal:disabled {
    background: transparent;
}
QScrollBar::handle:vertical:hover {
    background: $line2;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 3px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: $hover;
    min-width: 26px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: $line2;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QListWidget, QListView, QTreeView, QTableView {
    background: $panel;
    border: 1px solid $line;
    border-radius: 8px;
    outline: none;
}
QListWidget::item:selected, QListView::item:selected {
    background: $hover;
    color: $text;
}

/* ---------- cards and form text ---------- */
QScrollArea#connectionsScroll, QWidget#connectionsContent {
    background: $base;
    border: none;
}
QFrame#card {
    background: $panel;
    border: 1px solid $line2;
    border-radius: 14px;
}
QFrame#hero {
    border: 1px solid $line2;
    border-radius: 14px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(79, 125, 255, 46), stop:1 rgba(148, 104, 255, 20));
}
QLabel#heroTitle {
    font-family: "$font_display", "Segoe UI", sans-serif;
    font-size: 22px;
    font-weight: 600;
    color: $text;
    background: transparent;
}
QFrame#tile {
    background: $base;
    border: 1px solid $line2;
    border-radius: 12px;
}
QFrame#tile:hover, QFrame#tile:focus {
    border-color: $cyan;
}
QLabel#chip {
    padding: 2px 9px;
    border-radius: 9px;
    border: 1px solid $line2;
    color: $dim;
    font-size: 11px;
    font-weight: 500;
}
QLabel#chip[state="ok"] {
    background: rgba(61, 220, 151, 23);
    border-color: rgba(61, 220, 151, 71);
    color: #9ff0c9;
}
QLabel#chip[state="busy"] {
    background: rgba(79, 125, 255, 38);
    border-color: rgba(79, 125, 255, 110);
    color: #b7caff;
}
QLabel#chip[state="warn"] {
    background: rgba(246, 185, 76, 23);
    border-color: rgba(246, 185, 76, 71);
    color: #ffd592;
}
QLabel#chip[state="bad"] {
    background: rgba(255, 93, 115, 23);
    border-color: rgba(255, 93, 115, 71);
    color: #ff9aa8;
}
QLabel#cardTitle {
    font-family: "$font_display", "Segoe UI", sans-serif;
    font-size: 15px;
    font-weight: 600;
    color: $text;
}
QLabel#fieldLabel {
    color: $dim;
    font-size: 12px;
    font-weight: 500;
}
QLabel#hint {
    color: $faint;
    font-size: 12px;
}
QLabel#connectionDetails {
    color: $dim;
    font-size: 13px;
}
QToolButton#linkButton {
    border: none;
    color: $cyan;
    font-weight: 500;
    padding: 2px 0px;
}
QToolButton#linkButton:hover {
    color: #9ee8ff;
}
QLabel#metricValue {
    font-family: "$font_mono", "Consolas", monospace;
    font-size: 12px;
    color: $text;
}
QLabel#metricValue[stale="true"] {
    color: $faint;
}
QLabel#assetThumb {
    background: $void;
    border: 1px solid $line;
    border-radius: 10px;
    color: $faint;
}
QLabel#notice {
    color: #ffd592;
    background: rgba(246, 185, 76, 23);
    border: 1px solid rgba(246, 185, 76, 71);
    border-radius: 10px;
    padding: 9px 14px;
}
QTreeWidget#modelTree {
    background: $base;
    border: 1px solid $line;
    border-radius: 8px;
    outline: none;
}
QTreeWidget#modelTree::item {
    height: 28px;
    color: $text;
}
QTreeWidget#modelTree::item:selected {
    background: $hover;
}
QHeaderView::section {
    background: $panel;
    color: $faint;
    border: none;
    border-bottom: 1px solid $line;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 500;
}
QCheckBox {
    spacing: 9px;
    color: $text;
}
"""
)


_GLYPH_QSS = Template(
    """
QComboBox::down-arrow, QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("$dir/chev-down.png");
    width: 12px;
    height: 12px;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("$dir/chev-up.png");
    width: 12px;
    height: 12px;
}
QSpinBox, QDoubleSpinBox {
    padding-right: 26px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 22px;
    border: none;
    border-left: 1px solid $line;
    border-top-right-radius: 8px;
    background: $raised;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 22px;
    border: none;
    border-left: 1px solid $line;
    border-top: 1px solid $line;
    border-bottom-right-radius: 8px;
    background: $raised;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: $hover;
}
QCheckBox::indicator:checked {
    image: url("$dir/check.png");
}
"""
)

_DIALOG_QSS = """
QDialog {
    background: $base;
}
QTabWidget::pane {
    border: 1px solid $line;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: $dim;
    padding: 7px 16px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:selected {
    color: $text;
    background: $panel;
    border-color: $line;
    border-bottom-color: $panel;
}
QTabBar::tab:hover:!selected {
    color: $text;
}
QListWidget {
    background: $base;
    color: $text;
    border: 1px solid $line;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 5px 8px;
    border-radius: 5px;
}
QListWidget::item:selected {
    background: $hover;
}
QMessageBox, QInputDialog {
    background: $base;
}
"""


def build_stylesheet(tokens: Tokens = DARK, glyph_dir: str | None = None) -> str:
    """The application stylesheet. ``glyph_dir`` (see ``icons.write_style_glyphs``) adds the arrow and
    check-mark images; without it those controls fall back to Qt's defaults."""
    values = asdict(tokens)
    sheet = _QSS.substitute(values) + Template(_DIALOG_QSS).substitute(values)
    if glyph_dir:
        sheet += _GLYPH_QSS.substitute({**values, "dir": glyph_dir})
    return sheet
