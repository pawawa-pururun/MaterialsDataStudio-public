"""Opening an empty Graph Editor must not load unused analysis backends."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_blank_editor_defers_scipy_and_analysis_forms(tmp_path: Path):
    script = r'''
import importlib.abc, sys
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog

class RejectAnalysisImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in (
            "scipy.optimize", "scipy.signal", "scipy.stats",
            "materials_data_studio.tools.graph_analysis_forms",
        )):
            raise AssertionError("Unused analysis imported during Graph Editor startup: " + fullname)

guard = RejectAnalysisImports()
sys.meta_path.insert(0, guard)
from materials_data_studio.tools.graph_window import GraphEditorWindow
app = QApplication([])
window = GraphEditorWindow()
window._discard_approved = True
window.show()
app.processEvents()
assert not window.canvas.grab().isNull()
sys.meta_path.remove(guard)
# The real menu still loads its dialog module when the user requests it.
with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
    next(a for a in window.statistics_menu.actions() if a.text() == "Wave Stats…").trigger()
assert "materials_data_studio.tools.graph_analysis_forms" in sys.modules
window.close()
app.processEvents()
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
             "MPLCONFIGDIR": str(tmp_path / "matplotlib"),
             "MDS_SETTINGS_DIRECTORY": str(tmp_path / "settings"),
             "MDS_RECOVERY_DIRECTORY": str(tmp_path / "recovery")},
        check=False, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
