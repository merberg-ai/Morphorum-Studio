"""Bundled UI fonts (SIL OFL: Sora, Geist, Geist Mono).

Loading is best-effort: if a font cannot be registered the stylesheet's
fallback stack (Segoe UI / system sans) is used and the app still works.
"""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtGui import QFontDatabase

FONT_FILES = (
    "Sora-Variable.ttf",
    "Geist-Variable.ttf",
    "GeistMono-Variable.ttf",
)


def font_path(name: str):
    return files("morphorum_studio").joinpath("assets", "fonts", name)


def load_bundled_fonts() -> list[str]:
    """Register bundled fonts with Qt; return the family names that loaded."""
    families: list[str] = []
    for name in FONT_FILES:
        path = font_path(name)
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return families
