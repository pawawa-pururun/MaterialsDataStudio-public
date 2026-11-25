"""Locate bundled assets in editable, wheel and frozen installations."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    """Return an installation-owned asset directory, independent of cwd."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is not None:
        return Path(bundle)
    packaged = Path(__file__).resolve().parents[1] / "_assets"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[3]
