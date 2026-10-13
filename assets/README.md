# Morphorum Studio branding

The optimized branded splash image is committed at `assets/morphorum-studio-logo.jpg`.
An identical copy is included as `src/morphorum_studio/assets/splash-logo.jpg` for installation via the Python wheel. The UI loads the bundled package resource using `importlib.resources`, independent of the current working directory. The image is displayed within a maximum 410 × 308 pixel area, preserving aspect ratio.

The full-resolution source artwork is not redistributed in the repository. The optimized JPEG is a startup asset, not a new logo design. The `scripts/verify_clean_install.py` CI smoke test proves that a fresh wheel install includes a loadable image without manually copying files.
