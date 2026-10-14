"""Render every Studio page offscreen against a scripted fake backend and save PNGs.

Used by CI (artifact "ui-screenshots") so the UI can be reviewed without a display. The fake
backend reuses the test doubles; nothing here talks to a real server.

    python scripts/render_screenshots.py OUTDIR [--sizes 1200x760,880x560]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]

import test_editor_ui as ed  # noqa: E402
import test_projects_ui as pj  # noqa: E402
from fakes import info  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from morphorum_studio.backend.client import BackendError  # noqa: E402

MODELS = {
    "checkpoints": [{"id": "c1", "family": "sdxl", "kind": "checkpoints", "name": "Juggernaut XL", "variant": "base"},
                    {"id": "c2", "family": "flux", "kind": "checkpoints", "name": "Flux Dev"}],
    "loras": [{"id": "l1", "family": "sdxl", "kind": "loras", "name": "Fox Style"},
              {"id": "l2", "family": "flux", "kind": "loras", "name": "Ink Wash"}],
}
FEATURES = {"project_crud": True, "timeline": True, "model_discovery": True, "console_sse": False}


class Fake:
    """Routes to the project/asset double or the timeline double by path."""

    def __init__(self) -> None:
        self.store = pj.Store()
        self.projects = pj.Client(self.store)
        self.timeline = ed.Client(ed.Backend())

    def get_json(self, path, params=None):
        if path == "/api/models":
            return {"models": MODELS.get((params or {}).get("kind"), [])}
        if path.endswith("/timeline"):
            return self.timeline.get_json(path, params)
        if path == "/api/animation/project-template":
            return {"project": {"animation": {"max_frames": 120, "fps": 24.0, "width": 1024, "height": 1024}}}
        if path.endswith("/inspect"):
            return {"name": "Fox Style", "family": "sdxl", "trigger_words": ["foxstyle"],
                    "ranks": [{"rank": 16, "modules": 480}], "warnings": ["Old adapter format"]}
        return self.projects.get_json(path, params)

    def get_json_etag(self, path, params=None):
        return self.projects.get_json_etag(path, params)

    def send_json(self, method, path, body=None, **kwargs):
        if path.endswith(("/schedule-series", "/validate-schedules", "/resolve-timeline")):
            return self.timeline.send_json(method, path, body, **kwargs)
        raise BackendError("NOT_FOUND", "no route", 404)

    def upload_bytes(self, *args, **kwargs):
        raise BackendError("NOT_FOUND", "no route", 404)

    def download(self, *args, **kwargs):
        raise BackendError("NOT_FOUND", "no route", 404)


def settle(ms: int = 250) -> None:
    QTest.qWait(ms)
    QApplication.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("outdir")
    parser.add_argument("--sizes", default="1200x760,880x560,1600x900")
    args = parser.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    from morphorum_studio.ui.fonts import load_bundled_fonts
    from morphorum_studio.ui.main_window import PAGES, StudioMainWindow
    from morphorum_studio.ui.preferences import StudioPreferences
    from morphorum_studio.ui.theme import DARK_STYLESHEET

    app = QApplication.instance() or QApplication(["screenshots"])
    app.setStyle("Fusion")
    load_bundled_fonts()
    app.setStyleSheet(DARK_STYLESHEET)
    settings = QSettings(str(out / "prefs.ini"), QSettings.Format.IniFormat)
    window = StudioMainWindow(preferences=StudioPreferences(settings))
    fake = Fake()
    window.session._factory = lambda url, token, timeout=6.0: fake
    window.show()
    names = [entry[0] for entry in PAGES]
    shots = 0
    for connected in (False, True):
        if connected:
            window.session.connected(info(features=FEATURES), "tok")
            settle(400)
        for size in args.sizes.split(","):
            width, height = (int(v) for v in size.split("x"))
            window.resize(width, height)
            for row, name in enumerate(names):
                window.navigation.setCurrentRow(row)
                settle(150)
                if connected and name == "Projects":
                    window.projects_page._select("alpha")
                    settle(300)
                if connected and name == "Editor":
                    window.projects_service.refresh()
                    settle(200)
                    page = window.editor_page
                    page.project.setCurrentIndex(1)
                    page._project_chosen(1)
                    settle(400)
                label = "connected" if connected else "offline"
                target = out / f"{label}-{size}-{name.lower().replace(' ', '-')}.png"
                window.grab().save(str(target))
                shots += 1
    if True:  # dialogs, connected, at the default size
        window.resize(1200, 760)
        window.navigation.setCurrentRow(names.index("Projects"))
        settle(200)
        for label, opener in (("wizard", window.projects_page._new_project),
                              ("models", window.projects_page._open_models)):
            opener()
            settle(500)
            dialog = getattr(window.projects_page, "setup_dialog" if label == "wizard" else "models_dialog")
            if label == "models":
                dialog.lora_list.setCurrentRow(0)
                settle(300)
            dialog.grab().save(str(out / f"dialog-{label}.png"))
            shots += 1
            dialog.close()
    print(f"saved {shots} screenshots to {out}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # avoid the PySide6 interpreter-exit teardown crash (see tests/conftest.py)
