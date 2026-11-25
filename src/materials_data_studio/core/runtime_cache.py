"""Explicit headless preparation of machine-local application caches."""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path


def prepare_runtime_cache(report_path: Path, persistent: Path | None) -> bool:
    """Populate the installed app's font inventory before its first GUI launch."""
    started = time.perf_counter()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("RUNNING\n", encoding="utf-8")
    try:
        import matplotlib
        from matplotlib import font_manager

        directory = Path(matplotlib.get_cachedir())
        if getattr(sys, "frozen", False) and (persistent is None or directory.resolve() != persistent.resolve()):
            raise RuntimeError("A persistent user font cache is unavailable")
        report_path.write_text(
            f"OK\nmatplotlib={matplotlib.__version__}\ncache_directory={directory}\n"
            f"font_entries={len(font_manager.fontManager.ttflist)}\n"
            f"seconds={time.perf_counter() - started:.3f}\n", encoding="utf-8")
        return True
    except Exception:
        report_path.write_text("ERROR\n" + traceback.format_exc(), encoding="utf-8")
        return False
