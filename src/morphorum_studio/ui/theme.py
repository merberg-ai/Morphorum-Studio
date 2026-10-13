"""Application stylesheet. The values live in ``tokens.py``; this keeps the old import path."""

from morphorum_studio.ui.tokens import DARK, build_stylesheet

DARK_STYLESHEET = build_stylesheet(DARK)
