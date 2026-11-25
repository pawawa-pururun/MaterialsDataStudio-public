"""Run Tools actions, paint and cursor conversion in a fresh application."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import qVersion


def test_gui_launch_smoke_uses_real_tools_actions(tmp_path: Path) -> None:
    report = tmp_path / "native-gui-smoke.txt"
    result = subprocess.run(
        [sys.executable, "-m", "materials_data_studio", "--native-gui-smoke-test", str(report)],
        env={**os.environ, "QT_QPA_PLATFORM": "cocoa" if sys.platform == "darwin" else "offscreen",
             "MDS_SETTINGS_DIRECTORY": str(tmp_path / "settings"),
             "MDS_RECOVERY_DIRECTORY": str(tmp_path / "recovery"),
             "MPLCONFIGDIR": str(tmp_path / "matplotlib")},
        capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
    )
    text = report.read_text(encoding="utf-8") if report.exists() else "No GUI smoke report"
    assert result.returncode == 0, "\n".join((text, result.stdout, result.stderr))
    assert text.startswith("OK\n")
    assert f"Qt={qVersion()}\n" in text
    assert text.count("Opening Tools >") == 4
    assert "custom-color-space cursor" in text
    assert "tools_launch_and_canvas_cursors=OK" in text
    if sys.platform == "darwin":
        assert "platform=cocoa\n" in text
