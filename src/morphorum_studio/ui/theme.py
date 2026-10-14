"""Application stylesheet. The values live in ``tokens.py``; this keeps the old import path."""

from morphorum_studio.ui.tokens import DARK, build_stylesheet

DARK_STYLESHEET = build_stylesheet(DARK)


def application_stylesheet() -> str:
    """The stylesheet with arrow and check-mark images (written once into the cache directory)."""
    from PySide6.QtCore import QStandardPaths

    from morphorum_studio.ui.icons import write_style_glyphs

    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    try:
        glyphs = write_style_glyphs(f"{base or '.'}/style-glyphs", DARK.dim)
    except OSError:
        return DARK_STYLESHEET
    return build_stylesheet(DARK, glyph_dir=glyphs)
