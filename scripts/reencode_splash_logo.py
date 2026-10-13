"""One-time source-artwork re-encode to remove malformed JPEG marker padding."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/morphorum_studio/assets/splash-logo.jpg"
PUBLIC = ROOT / "assets/morphorum-studio-logo.jpg"
for target in (SOURCE, PUBLIC):
    with Image.open(target) as source:
        image = source.convert("RGB")
        image.save(target, format="JPEG", quality=90, optimize=True)
        with Image.open(target) as check:
            check.verify()
    print(f"Re-encoded {target.relative_to(ROOT)}")
