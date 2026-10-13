"""CI smoke test: freshly installed wheel contains loadable Morphorum artwork."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="morphorum-fresh-") as folder:
        temp = Path(folder)
        wheel_dir = temp / "wheel"
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheel_dir), str(root)],
            check=True,
        )
        wheels = list(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise AssertionError("Expected exactly one Studio wheel")
        venv_dir = temp / "fresh"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])], check=True)
        probe = (
            "from importlib.resources import files; "
            "from PySide6.QtGui import QPixmap; "
            "p=files('morphorum_studio').joinpath('assets','splash-logo.jpg'); "
            "assert p.is_file(), p; "
            "assert p.read_bytes().startswith(bytes.fromhex('ffd8ff')); "
            "from morphorum_studio.ui.splash import splash_logo_path; "
            "assert splash_logo_path().is_file(); "
            "assert not QPixmap(str(splash_logo_path())).isNull(); "
            "print('PASS: fresh wheel contains loadable splash logo')"
        )
        subprocess.run([str(python), "-c", probe], check=True, cwd=temp)


if __name__ == "__main__":
    main()
