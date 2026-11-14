"""First opening an analysis window only loads its presentation dependencies."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("feature", ["graph", "search", "peak_fitting", "peak_fitting_empty"])
def test_first_open_defers_unused_numerical_dependencies(feature, tmp_path):
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONUTF8": "1",
                   "MDS_SETTINGS_DIRECTORY": str(tmp_path / "settings"),
                   "MDS_RECOVERY_DIRECTORY": str(tmp_path / "recovery")}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/benchmark_feature_startup.py"),
                             "--child", feature, "--root", str(tmp_path)],
                            cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90, check=True)
    report = json.loads(result.stdout.splitlines()[-1])
    assert "scipy.optimize" not in report["loaded_modules"]
    assert "scipy.signal" not in report["loaded_modules"]
    if feature != "graph":
        assert "matplotlib.figure" not in report["loaded_modules"]
    assert report["first_events_seconds"] < 20
