"""Stroke icon set rendered from inline SVG, so icons follow the theme colours."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 24x24 viewBox, 1.6 stroke (the rail icons from the approved mockup).
_RAIL = {
    "home": '<path d="M4 11.5 12 5l8 6.5V19a1 1 0 0 1-1 1h-4v-5h-6v5H5a1 1 0 0 1-1-1z"/>',
    "plug": '<path d="M9 4v5M15 4v5M7 9h10v3a5 5 0 0 1-10 0zM12 17v3.5"/>',
    "library": (
        '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/>'
        '<rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>'
    ),
    "sparkle": (
        '<path d="M12 3.5l1.7 4.8 4.8 1.7-4.8 1.7L12 16.5l-1.7-4.8L5.5 10l4.8-1.7z"/>'
        '<path d="M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>'
    ),
    "search": '<circle cx="10.5" cy="10.5" r="5.5"/><path d="M15 15l5 5"/>',
    "timeline": '<path d="M4 7h8M9 12h11M6 17h9"/>',
    "graph": (
        '<circle cx="6" cy="6.5" r="2.2"/><circle cx="18" cy="6.5" r="2.2"/><circle cx="12" cy="18" r="2.2"/>'
        '<path d="M8.2 6.5h7.6M7.2 8.4l3.7 7.6M16.8 8.4l-3.7 7.6"/>'
    ),
    "queue": '<path d="M5 6h14M5 12h14M5 18h7"/><path d="M16 15.5l4 2.5-4 2.5z"/>',
    "console": (
        '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M7.5 10l3 2.5-3 2.5M13 15h4"/>'
    ),
    "settings": (
        '<path d="M5 8h8M17 8h2M5 16h2M11 16h8"/><circle cx="15" cy="8" r="2"/><circle cx="9" cy="16" r="2"/>'
    ),
}

# 12x12 viewBox, 1.2 stroke (window controls).
_WINDOW = {
    "win-min": '<path d="M1 6h10"/>',
    "win-max": '<rect x="1.5" y="1.5" width="9" height="9" rx="1"/>',
    "win-restore": '<path d="M3.5 3.5V1.5h7v7h-2"/><rect x="1.5" y="3.5" width="7" height="7" rx="1"/>',
    "win-close": '<path d="M1.5 1.5l9 9M10.5 1.5l-9 9"/>',
    # Control glyphs used by the stylesheet (combo and spin arrows, check mark).
    "chev-down": '<path d="M2.5 4.5 6 8l3.5-3.5"/>',
    "chev-up": '<path d="M2.5 7.5 6 4l3.5 3.5"/>',
    "check": '<path d="M2.5 6.5 5 9l4.5-5.5"/>',
}

ICON_NAMES = tuple(_RAIL) + tuple(_WINDOW)


def _svg(name: str, color: str) -> bytes:
    if name in _RAIL:
        view, width, body = 24, 1.6, _RAIL[name]
    else:
        view, width, body = 12, 1.2, _WINDOW[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" fill="none" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    ).encode()


def pixmap(name: str, color: str, size: int = 20) -> QPixmap:
    """Render icon ``name`` in ``color`` at ``size`` logical pixels (HiDPI aware)."""
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    px = max(1, round(size * ratio))
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(ratio)
    return result


def icon(
    name: str,
    normal: str,
    checked: str | None = None,
    hover: str | None = None,
    size: int = 20,
) -> QIcon:
    """An icon with a normal colour and optional checked and hover colours."""
    result = QIcon()
    result.addPixmap(pixmap(name, normal, size), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, checked or normal, size), QIcon.Mode.Normal, QIcon.State.On)
    if hover:
        result.addPixmap(pixmap(name, hover, size), QIcon.Mode.Active, QIcon.State.Off)
    return result


def icon_size(size: int = 20) -> QSize:
    return QSize(size, size)


STYLE_GLYPHS = ("chev-down", "chev-up", "check")


def write_style_glyphs(directory: str, color: str, size: int = 12) -> str:
    """Write the stylesheet glyphs as PNGs (1x and @2x) and return the directory with ``/`` separators.

    QSS can only reference image files, so these are generated once at start-up into a cache
    directory. Qt picks the ``@2x`` file on high-DPI screens.
    """
    import os

    os.makedirs(directory, exist_ok=True)
    for name in STYLE_GLYPHS:
        for scale, suffix in ((1, ""), (2, "@2x")):
            px = size * scale
            image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            QSvgRenderer(QByteArray(_svg(name, color))).render(painter)
            painter.end()
            image.save(os.path.join(directory, f"{name}{suffix}.png"))
    return directory.replace("\\", "/")
