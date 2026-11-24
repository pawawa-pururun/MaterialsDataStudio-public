"""Frozen launches retain font discovery while test caches stay isolated."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QStandardPaths

from materials_data_studio.core.matplotlib_cache import configure_frozen_matplotlib_cache


@pytest.fixture
def frozen_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["MaterialsDataStudio"])
    monkeypatch.setenv("MDS_MATPLOTLIB_CACHE_DIRECTORY", str(tmp_path / "cache"))
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "pyinstaller-temporary"))
    monkeypatch.delenv("MPL_IGNORE_SYSTEM_FONTS", raising=False)
    return tmp_path / "cache"


def test_source_preserves_matplotlib_configuration(monkeypatch, frozen_cache):
    monkeypatch.setattr(sys, "frozen", False)
    before = os.environ["MPLCONFIGDIR"]
    assert configure_frozen_matplotlib_cache() is None
    assert os.environ["MPLCONFIGDIR"] == before


def test_frozen_cache_uses_native_user_cache(monkeypatch, frozen_cache, tmp_path: Path):
    monkeypatch.delenv("MDS_MATPLOTLIB_CACHE_DIRECTORY")
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda _location: str(tmp_path))
    cache = configure_frozen_matplotlib_cache()
    assert cache == tmp_path / "org.kageyamalab.MaterialsDataStudio/matplotlib/system-fonts"
    assert cache.is_dir()
    assert os.environ["MPLCONFIGDIR"] == str(cache)


def test_system_font_diagnostic_uses_separate_cache(monkeypatch, frozen_cache):
    normal = configure_frozen_matplotlib_cache()
    monkeypatch.setenv("MPL_IGNORE_SYSTEM_FONTS", "1")
    bundled = configure_frozen_matplotlib_cache()
    assert normal == frozen_cache / "system-fonts"
    assert bundled == frozen_cache / "bundled-fonts"


@pytest.mark.parametrize("flag", ["--packaging-smoke-test", "--native-gui-smoke-test"])
def test_manual_smoke_keeps_temporary_cache_without_override(monkeypatch, frozen_cache, flag):
    monkeypatch.delenv("MDS_MATPLOTLIB_CACHE_DIRECTORY")
    monkeypatch.setattr(sys, "argv", ["MaterialsDataStudio", flag, "report.txt"])
    before = os.environ["MPLCONFIGDIR"]
    assert configure_frozen_matplotlib_cache() is None
    assert os.environ["MPLCONFIGDIR"] == before


def test_unwritable_cache_falls_back_to_pyinstaller_cache(monkeypatch, frozen_cache, tmp_path: Path):
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("MDS_MATPLOTLIB_CACHE_DIRECTORY", str(blocked))
    before = os.environ["MPLCONFIGDIR"]
    assert configure_frozen_matplotlib_cache() is None
    assert os.environ["MPLCONFIGDIR"] == before


def test_actual_pyinstaller_hook_and_bootstrap_reuse_font_cache(tmp_path: Path):
    script = r'''
import os, runpy, sys
from pathlib import Path
from types import SimpleNamespace
import PyInstaller

root = Path(sys.argv[1])
require_warm_cache = sys.argv[2] == "warm"
installation = Path(PyInstaller.__file__).parent
sys._MEIPASS = str(root / "Materials Data Studio.app/Contents/Frameworks")
sys.path.insert(0, str(installation / "fake-modules"))
runpy.run_path(str(installation / "hooks/rthooks/pyi_rth_mplconfig.py"))
temporary_cache = os.environ["MPLCONFIGDIR"]
sys.frozen = True
sys.argv = ["MaterialsDataStudio"]

def application_main():
    assert "matplotlib" not in sys.modules
    import matplotlib
    assert os.environ["MPLCONFIGDIR"] != temporary_cache
    assert Path(matplotlib.get_cachedir()).is_relative_to(root / "persistent")
    def reject_scan(frame, event, arg):
        if event == "call" and frame.f_globals.get("__name__") == "matplotlib.font_manager" and frame.f_code.co_qualname == "FontManager.__init__":
            raise AssertionError("Font discovery repeated instead of reusing the saved cache")
    if require_warm_cache:
        sys.setprofile(reject_scan)
    from matplotlib import font_manager
    sys.setprofile(None)
    assert Path(font_manager.findfont("DejaVu Sans")).is_file()
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    figure = Figure(figsize=(2, 1))
    FigureCanvasAgg(figure)
    figure.text(.1, .5, "Materials Data Studio")
    figure.savefig(root / "render.png")
    return 0

sys.modules["materials_data_studio.app"] = SimpleNamespace(main=application_main)
from materials_data_studio.bootstrap import main
raise SystemExit(main())
'''
    env = {**os.environ, "MDS_MATPLOTLIB_CACHE_DIRECTORY": str(tmp_path / "persistent")}
    env.pop("MPL_IGNORE_SYSTEM_FONTS", None)
    for mode in ("cold", "warm"):
        before = {p.name: p.stat().st_mtime_ns for p in tmp_path.rglob("fontlist-*.json")}
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path), mode], env=env,
                                check=False, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        after = {p.name: p.stat().st_mtime_ns for p in tmp_path.rglob("fontlist-*.json")}
        assert after
        if mode == "warm":
            assert after == before
    cache = next(tmp_path.rglob("fontlist-*.json"))
    fonts = json.loads(cache.read_text(encoding="utf-8"))["ttflist"]
    assert any(not Path(font["fname"]).is_absolute() for font in fonts)
    assert (tmp_path / "render.png").stat().st_size > 1000
