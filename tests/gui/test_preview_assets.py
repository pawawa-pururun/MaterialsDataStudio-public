"""Built previews match the renderer and avoid rendering during UI creation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QComboBox
from scripts.render_graph_previews import ensure_assets

from materials_data_studio.core.preview_catalog import IMAGE_FILES, INPUT_FILES
from materials_data_studio.core.resources import resource_root
from materials_data_studio.tools import graph_symbols, preview_render
from materials_data_studio.tools.pxp_style import COLORMAPS, colormap
from materials_data_studio.ui import preview_assets
from materials_data_studio.ui.style_inputs import colormap_swatches

ROOT = Path(__file__).resolve().parents[2]


def test_build_rejects_stale_or_damaged_previews(tmp_path: Path):
    for relative in (*INPUT_FILES, "uv.lock"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    shutil.copytree(ROOT / "resources/previews", tmp_path / "resources/previews")
    ensure_assets(tmp_path, check_only=True)
    image = tmp_path / "resources/previews/graph-previews.png"
    original = image.read_bytes()
    image.write_bytes(b"damaged image")
    with pytest.raises(RuntimeError, match="stale"):
        ensure_assets(tmp_path, check_only=True)
    image.write_bytes(original)
    source = tmp_path / INPUT_FILES[0]
    source.write_text(source.read_text() + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="stale"):
        ensure_assets(tmp_path, check_only=True)


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("kind,number,dark", [
    ("marker", 0, False), ("marker", 16, True), ("marker", 62, False),
    ("line", 0, True), ("line", 7, False), ("line", 17, True),
])
def test_preview_pixels_match_reference_renderer(scale, kind, number, dark):
    directory = resource_root() / "resources/previews"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    key = f"{kind}:{number}:{'dark' if dark else 'light'}"
    x, y, width, height = manifest["entries"][key]
    image = QImage(str(directory / IMAGE_FILES[scale])).copy(
        x * scale, y * scale, width * scale, height * scale).convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4)
    expected = preview_render.style_pixels(kind, number, dark, scale=scale)
    assert np.max(np.abs(pixels.astype(int) - expected.astype(int))) <= 2


def test_all_standard_icons_and_palettes_load_without_rendering(qapp, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A standard preview was rendered at runtime")

    monkeypatch.setattr(preview_render, "style_pixels", forbidden)
    monkeypatch.setattr(preview_render, "colormap_pixels", forbidden)
    graph_symbols.style_icon.cache_clear()
    for dark in (False, True):
        for kind in ("marker", "line"):
            for _text, number in graph_symbols.visual_choices(kind):
                icon = graph_symbols.style_icon(kind, number, dark)
                assert not icon.isNull()
                pixmap = icon.pixmap(QSize(96, 28), 2.)
                assert pixmap.size() == QSize(192, 56)
                assert pixmap.devicePixelRatio() == 2
    for _ in range(2):
        combo = QComboBox()
        combo.addItems(list(COLORMAPS))
        colormap_swatches(combo)
        assert all(not combo.itemIcon(i).isNull() for i in range(combo.count()))


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("name", ["Viridis", "Rainbow", "VioletOrangeYellow"])
def test_palette_pixels_match_original_qt_colors(name, scale):
    from matplotlib import colormaps

    directory = resource_root() / "resources/previews"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    x, y, width, height = manifest["entries"]["colormap:" + name]
    image = QImage(str(directory / IMAGE_FILES[scale])).copy(
        x * scale, y * scale, width * scale, height * scale).convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4)
    row = np.array([QColor.fromRgbF(*rgba).getRgb() for rgba in colormaps[colormap(name)](np.linspace(0, 1, 90))])
    expected = np.repeat(np.repeat(row, scale, axis=0)[np.newaxis, :, :], 16 * scale, axis=0)
    assert np.max(np.abs(pixels.astype(int) - expected)) <= 1


def test_custom_styles_and_missing_assets_use_renderer(qapp, monkeypatch, tmp_path: Path):
    calls = []
    original = preview_render.style_pixels

    def render(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(preview_render, "style_pixels", render)
    graph_symbols.style_icon.cache_clear()
    assert not graph_symbols.style_icon("line", 1, pattern=(1., 2., 3., 4.)).isNull()
    assert len(calls) == 1
    monkeypatch.setattr(preview_assets, "resource_root", lambda: tmp_path)
    assert not graph_symbols.style_icon("marker", 3).isNull()
    assert len(calls) == 2
    combo = QComboBox()
    combo.addItem("magma")
    colormap_swatches(combo)
    assert not combo.itemIcon(0).isNull()
