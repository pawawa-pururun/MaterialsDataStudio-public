"""Cache preparation exits before GUI imports and survives a fresh process."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from materials_data_studio import bootstrap
from materials_data_studio.core.runtime_cache import prepare_runtime_cache


def test_missing_report_is_rejected_before_gui_start(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["MaterialsDataStudio", "--prepare-runtime-cache"])
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert bootstrap.main() == 2


def test_unavailable_persistent_cache_reports_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    report = tmp_path / "cache.txt"
    assert not prepare_runtime_cache(report, None)
    assert report.read_text(encoding="utf-8").startswith("ERROR\n")

def test_frozen_cache_preparation_is_headless_and_reusable(tmp_path: Path):
    script = r'''
import importlib.abc, os, runpy, sys
from pathlib import Path
import PyInstaller

report = Path(sys.argv[1])
warm = sys.argv[2] == "warm"
root = Path(PyInstaller.__file__).parent
sys._MEIPASS = str(report.parent / "MDS.app/Contents/Frameworks")
sys.path.insert(0, str(root / "fake-modules"))
runpy.run_path(str(root / "hooks/rthooks/pyi_rth_mplconfig.py"))
sys.frozen = True
sys.argv = ["MaterialsDataStudio", "--prepare-runtime-cache", str(report)]
class RejectGUI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ("PySide6.QtWidgets", "materials_data_studio.app"):
            raise AssertionError("GUI imported during cache preparation")
sys.meta_path.insert(0, RejectGUI())
if warm:
    def reject_scan(frame, event, arg):
        if event == "call" and frame.f_code.co_qualname == "FontManager.__init__":
            raise AssertionError("A saved font cache was not reused")
    sys.setprofile(reject_scan)
from materials_data_studio.bootstrap import main
raise SystemExit(main())
'''
    env = {**os.environ, "MDS_MATPLOTLIB_CACHE_DIRECTORY": str(tmp_path / "cache")}
    env.pop("MPL_IGNORE_SYSTEM_FONTS", None)
    for mode in ("cold", "warm"):
        report = tmp_path / (mode + ".txt")
        result = subprocess.run([sys.executable, "-c", script, str(report), mode], env=env,
                                check=False, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        text = report.read_text(encoding="utf-8")
        assert text.startswith("OK\n") and "font_entries=" in text
        assert "cache_directory=" + str(tmp_path / "cache/system-fonts") in text
