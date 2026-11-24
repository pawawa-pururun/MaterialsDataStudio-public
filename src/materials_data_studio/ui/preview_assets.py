"""Load immutable preview images without running the graph renderer."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon, QImage, QPixmap

from materials_data_studio.core.preview_catalog import FORMAT, IMAGE_FILES
from materials_data_studio.core.resources import resource_root


@lru_cache(maxsize=4)
def _manifest(directory: str) -> dict:
    try:
        data = json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))
        return data if data.get("format") == FORMAT else {}
    except (OSError, ValueError, AttributeError):
        return {}


@lru_cache(maxsize=8)
def _atlas(directory: str, scale: int) -> QImage:
    return QImage(str(Path(directory) / IMAGE_FILES[scale]))


@lru_cache(maxsize=512)
def _icon(directory: str, key: str) -> QIcon | None:
    try:
        rect = _manifest(directory)["entries"][key]
        if len(rect) != 4 or not all(isinstance(value, int) for value in rect):
            return None
        x, y, width, height = rect
        if min(x, y) < 0 or min(width, height) <= 0:
            return None
        icon = QIcon()
        for scale in IMAGE_FILES:
            atlas = _atlas(directory, scale)
            if atlas.isNull() or (x + width) * scale > atlas.width() or (y + height) * scale > atlas.height():
                return None
            image = atlas.copy(x * scale, y * scale, width * scale, height * scale)
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(scale)
            icon.addPixmap(pixmap)
        return icon
    except (KeyError, TypeError):
        return None


def preview_icon(key: str) -> QIcon | None:
    return _icon(str(resource_root() / "resources/previews"), key)


def pixels_icon(pixels) -> QIcon:  # type: ignore[no-untyped-def]
    """Convert a custom-style render with independent image storage."""
    image = QImage(pixels.data, pixels.shape[1], pixels.shape[0], QImage.Format.Format_RGBA8888).copy()
    return QIcon(QPixmap.fromImage(image))
