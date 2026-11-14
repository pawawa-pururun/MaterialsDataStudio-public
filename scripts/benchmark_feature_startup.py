"""Fresh-process first-opening probes for graph and XRD analysis windows."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ("graph", "search", "peak_fitting", "peak_fitting_empty")


def synthetic_state():
    import numpy as np

    from materials_data_studio.core.models import Dataset, ModuleType
    from materials_data_studio.core.project_state import ProjectState

    x = np.linspace(10., 90., 20000)
    positions = np.rad2deg(2 * np.arcsin(1.540598 * np.sqrt([2., 3., 4.]) / 8))
    intensity = 10 + sum(100 * np.exp(-((x - center) / .1)**2) for center in positions)
    observed = Dataset("Synthetic observation", ModuleType.XRD, {"x": x, "intensity": intensity},
                       metadata={"source_axis": "two_theta", "wavelength_a": 1.540598,
                                 "background_enabled": True}, processed_data={"background": np.full_like(x, 10.)})
    cif = """data_generated
_symmetry_space_group_name_H-M 'P m -3 m'
_cell_length_a 4
_cell_length_b 4
_cell_length_c 4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na1 Na 0 0 0
"""
    phase = Dataset("Synthetic phase", ModuleType.XRD, {"x": positions, "intensity": np.array([100., 60., 30.])},
                    source_filename="synthetic.cif", source_bytes=cif.encode(),
                    metadata={"is_simulated_phase": True, "edited_cif": cif, "wavelength_a": 1.540598,
                              "stick_two_theta_deg": positions.tolist(), "stick_intensity": [100., 60., 30.],
                              "stick_hkl_labels": ["(1 1 0)", "(1 1 1)", "(2 0 0)"],
                              "stick_d_spacing_a": (4 / np.sqrt([2., 3., 4.])).tolist(), "fwhm_deg": .2})
    return ProjectState([observed, phase])


def child(feature: str, root: Path) -> dict:
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from materials_data_studio.core.startup_metrics import process_memory
    from materials_data_studio.ui.main_window import MainWindow

    app = QApplication([])
    app.setStyle("Fusion")
    main = MainWindow()
    main.show()
    app.processEvents()
    state = synthetic_state()
    if feature == "peak_fitting_empty":
        state.datasets.pop()
    before = process_memory()
    start = time.perf_counter()
    if feature == "graph":
        window = main.tool_manager.open_tool("pxp_viewer")
    elif feature == "search":
        from materials_data_studio.modules.xrd.phase_store import PhaseStore
        from materials_data_studio.modules.xrd.phase_window import PhaseSearchWindow

        window = PhaseSearchWindow(state, main, store=PhaseStore(root / "reference-store"))
        window.show()
    else:
        from materials_data_studio.modules.xrd.peak_fitting.fitting_window import (
            XrdPeakFittingWindow,
        )

        window = XrdPeakFittingWindow(state, apply_callback=lambda *args: None)
        window.show()
    app.processEvents()
    seconds = time.perf_counter() - start
    QTest.qWait(120)
    loaded = [name for name in ("scipy.optimize", "scipy.signal", "matplotlib.figure") if name in sys.modules]
    report = {"feature": feature, "first_events_seconds": seconds, "loaded_modules": loaded,
              "memory_before": before, "memory_after": process_memory()}
    if feature == "graph":
        window._discard_approved = True
    window.close()
    main.state.modified = False
    main.undo_history.reset(clean=True)
    main.close()
    app.processEvents()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=FEATURES)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.child:
        print(json.dumps(child(args.child, args.root)))
        return
    if not 1 <= args.repeat <= 20:
        raise ValueError("Use 1–20 repetitions")
    source = args.source_root.resolve()
    if not (source / "src/materials_data_studio").is_dir():
        raise ValueError("Select an MDS source checkout")
    samples = []
    for iteration in range(args.repeat):
        for feature in FEATURES:
            work = ROOT / ".test-tmp/feature-startup" / uuid.uuid4().hex
            work.mkdir(parents=True)
            environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONUTF8": "1",
                           "MDS_SETTINGS_DIRECTORY": str(work / "settings"),
                           "MDS_RECOVERY_DIRECTORY": str(work / "recovery"),
                           "PYTHONPATH": str(source / "src"), "TEMP": str(work), "TMP": str(work)}
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", feature, "--root", str(work)],
                                    cwd=source, env=environment, check=True, capture_output=True, text=True, encoding="utf-8", timeout=90)
            samples.append({"iteration": iteration, **json.loads(result.stdout.splitlines()[-1])})
    report = {"samples": samples,
              "medians_seconds": {feature: statistics.median(row["first_events_seconds"] for row in samples if row["feature"] == feature) for feature in FEATURES},
              "python": sys.version.split()[0], "platform": sys.platform,
              "scope": "Fresh Python processes after main-window startup, generated 20,000-point data and local synthetic CIF. OS cache is uncontrolled. Measures source windows and first event processing."}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
