"""Build portable 1x/2x preview atlases; check without scientific dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tomllib
from pathlib import Path

from materials_data_studio.core.preview_catalog import (
    CELL_HEIGHT,
    CELL_WIDTH,
    COLUMNS,
    FORMAT,
    IMAGE_FILES,
    INPUT_FILES,
)

ROOT = Path(__file__).resolve().parents[1]


def input_signature(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in INPUT_FILES:
        digest.update(relative.encode())
        digest.update((root / relative).read_bytes())
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    version = next(p["version"] for p in lock["package"] if p["name"] == "matplotlib")
    digest.update(version.encode())
    return digest.hexdigest()


def ensure_assets(root: Path = ROOT, *, check_only: bool = False) -> None:
    directory = root / "resources/previews"
    signature = input_signature(root)
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if (manifest["format"] == FORMAT and manifest["input_signature"] == signature
                and all(hashlib.sha256((directory / name).read_bytes()).hexdigest() == manifest["images"][name]
                        for name in IMAGE_FILES.values())):
            return
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if check_only:
        raise RuntimeError("Graph preview assets are missing or stale. Run uv run python scripts/render_graph_previews.py")

    import numpy as np
    from matplotlib import rc_context, rcParamsDefault
    from PIL import Image

    from materials_data_studio.tools.preview_render import colormap_pixels, style_pixels
    from materials_data_studio.tools.pxp_style import COLORMAPS

    entries = [(f"{kind}:{number}:{theme}", (kind, number, theme == "dark"))
               for theme in ("light", "dark") for kind, count in (("marker", 63), ("line", 18))
               for number in range(count)]
    entries += [("colormap:" + name, (name,)) for name in COLORMAPS]
    rectangles = {}
    images = {}
    directory.mkdir(parents=True, exist_ok=True)
    # Build-machine plotting preferences must not change shipped UI previews.
    with rc_context({key: value for key, value in rcParamsDefault.items() if key != "backend"}):
        for scale, filename in IMAGE_FILES.items():
            pixels = np.zeros((math.ceil(len(entries) / COLUMNS) * CELL_HEIGHT * scale,
                               COLUMNS * CELL_WIDTH * scale, 4), dtype=np.uint8)
            for index, (key, args) in enumerate(entries):
                tile = colormap_pixels(*args, scale=scale) if key.startswith("colormap:") else style_pixels(*args, scale=scale)
                x, y = index % COLUMNS * CELL_WIDTH, index // COLUMNS * CELL_HEIGHT
                h, w = tile.shape[:2]
                pixels[y*scale:y*scale+h, x*scale:x*scale+w] = tile
                rectangles[key] = [x, y, w // scale, h // scale]
            path = directory / filename
            Image.fromarray(pixels).save(path)
            images[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(
        {"format": FORMAT, "input_signature": signature, "images": images, "entries": rectangles},
        indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Generated {len(entries)} graph previews at 1x/2x in {directory}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    ensure_assets(check_only=args.check)
