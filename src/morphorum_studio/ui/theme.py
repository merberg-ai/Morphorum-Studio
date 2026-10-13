"""Pre-S2 UI polish: native graphite controls with restrained cyan/violet focus."""
DARK_STYLESHEET = """
QWidget {
    background: #10131d;
    color: #e8edfb;
    font-family: "Segoe UI", "Inter", "Arial", sans-serif;
    font-size: 13px;
}
QFrame#topBar {
    background: #171d2a;
    border-bottom: 1px solid #2b3345;
}
QLabel#brandName {
    color: #eaf6ff;
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#connectionStatus {
    color: #eababa;
    background: #37232a;
    border: 1px solid #73444b;
    border-radius: 10px;
    padding: 9px 15px;
    font-weight: 700;
}
QFrame#sidebar {
    background: #171c29;
    border: 1px solid #2a3140;
    border-radius: 12px;
}
QLabel#sidebarCaption, QLabel#sectionCaption {
    color: #8d9bb4;
    letter-spacing: 1.4px;
    font-size: 11px;
    font-weight: 700;
}
QListWidget#navigation {
    background: transparent;
    border: none;
    outline: none;
    padding: 2px;
}
QListWidget#navigation::item {
    min-height: 38px;
    padding-left: 14px;
    margin: 2px;
    border-radius: 9px;
    color: #b4bdce;
}
QListWidget#navigation::item:selected {
    background: #303a52;
    color: #ffffff;
    border-left: 3px solid #a28cff;
}
QListWidget#navigation::item:hover:!selected {
    background: #252e40;
}
QFrame#pageSurface {
    background: #181e2b;
    border: 1px solid #2b3345;
    border-radius: 12px;
}
QLabel#pageHeading {
    color: #ffffff;
    font-size: 29px;
    font-weight: 800;
}
QLabel#pageDescription, QLabel#panelDescription {
    color: #b9c4d9;
    font-size: 14px;
}
QFrame#infoPanel, QGroupBox {
    background: #1c2535;
    border: 1px solid #354258;
    border-radius: 11px;
}
QGroupBox {
    font-size: 13px;
    font-weight: 650;
    margin-top: 15px;
    padding: 18px 14px 12px 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 7px;
    color: #c8d5f0;
}
QPushButton {
    background: #28334a;
    border: 1px solid #445370;
    border-radius: 10px;
    padding: 9px 16px;
    min-height: 21px;
    color: #e6f1ff;
    font-weight: 600;
}
QPushButton:hover {
    background: #344461;
    border-color: #74b8ef;
}
QPushButton:pressed {
    background: #1e2940;
    border-color: #9b87ff;
}
QPushButton:focus {
    border: 2px solid #8eabff;
}
QPushButton:disabled {
    background: #1e2532;
    color: #748198;
    border-color: #31394a;
}
QPushButton#primaryAction {
    background: #3b5191;
    border-color: #698cf0;
    color: white;
}
QPushButton#primaryAction:hover {
    background: #4e66ad;
    border-color: #92b7ff;
}
QPushButton#dangerAction {
    background: #422b37;
    border-color: #92536a;
}
QPushButton#dangerAction:hover {
    background: #613545;
    border-color: #df8098;
}
QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background: #141d2c;
    border: 1px solid #3b4860;
    border-radius: 9px;
    padding: 8px 11px;
    min-height: 21px;
    selection-background-color: #6848bf;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus,
QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #64c6ff;
    background: #18243a;
}
QLineEdit:read-only {
    color: #b3c3df;
    background: #1a2332;
}
QComboBox {
    padding-right: 30px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #344156;
    background: #25334a;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}
QComboBox QAbstractItemView {
    background: #202b3d;
    color: #edf2ff;
    border: 1px solid #516181;
    padding: 5px;
    selection-background-color: #435981;
    outline: none;
}
QCheckBox {
    spacing: 9px;
    color: #cfdaed;
    background: transparent;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid #62728f;
    background: #151e2d;
}
QCheckBox::indicator:hover {
    border-color: #67c8ff;
}
QCheckBox::indicator:checked {
    background: #7054bd;
    border: 2px solid #b2a0ff;
}
QScrollBar:vertical {
    background: #161e2c;
    width: 10px;
    margin: 3px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #485b79;
    min-height: 26px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #6588bb;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QFrame#footer {
    background: #121725;
    border-top: 1px solid #263044;
}
QLabel#footerText {
    color: #8895aa;
    font-size: 11px;
}
"""
