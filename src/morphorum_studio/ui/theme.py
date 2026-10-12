"""S0 dark graphite styling. No external fonts or generated assets required."""

DARK_STYLESHEET = """
QWidget {
    background: #10131d;
    color: #e6eaf4;
    font-family: "Segoe UI", "Inter", "Arial", sans-serif;
    font-size: 13px;
}
QFrame#topBar {
    background: #171d2a;
    border-bottom: 1px solid #2b3345;
}
QLabel#brandName {
    color: #e6eaf4;
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#connectionStatus {
    color: #eababa;
    background: #37232a;
    border: 1px solid #73444b;
    border-radius: 9px;
    padding: 8px 14px;
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
    min-height: 37px;
    padding-left: 14px;
    margin: 2px;
    border-radius: 8px;
    color: #b4bdce;
}
QListWidget#navigation::item:selected {
    background: #303a52;
    color: #ffffff;
    border-left: 3px solid #9b87ff;
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
QFrame#infoPanel {
    background: #20293a;
    border: 1px solid #354258;
    border-radius: 10px;
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
