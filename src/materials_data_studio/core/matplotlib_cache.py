"""Reuse font discovery across frozen application launches."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path


def configure_frozen_matplotlib_cache() -> Path | None:
    """Override PyInstaller's per-process cache before Matplotlib is imported."""
    if not getattr(sys, "frozen", False):
        return None
    configured = os.environ.get("MDS_MATPLOTLIB_CACHE_DIRECTORY", "").strip()
    if not configured and any(flag in sys.argv for flag in (
        "--packaging-smoke-test", "--native-gui-smoke-test",
    )):
        # A manually invoked smoke test must not populate the user's cache.
        return None
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        from PySide6.QtCore import QStandardPaths

        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
        if not location:
            return None
        root = Path(location) / "org.kageyamalab.MaterialsDataStudio" / "matplotlib"
    mode = "bundled-fonts" if os.environ.get("MPL_IGNORE_SYSTEM_FONTS") else "system-fonts"
    cache = root / mode
    try:
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=cache):
            pass
    except OSError:
        logging.getLogger(__name__).warning("Could not reuse the Matplotlib cache; using temporary cache", exc_info=True)
        return None
    # Matplotlib versions its font-list JSON and stores bundled font paths
    # relative to mpl-data, so it can rebase them after the .app is moved.
    os.environ["MPLCONFIGDIR"] = str(cache)
    return cache
