"""Platform capabilities shared by the UI, broker and packaging checks."""

from __future__ import annotations

import sys

PROCEDURE_UNAVAILABLE = (
    "Python Procedure execution is unavailable on Linux and macOS. "
    "You can edit and convert procedures, but running them requires Windows "
    "AppContainer isolation."
)


def procedure_execution_available() -> bool:
    """Advertise only platforms with an implemented OS isolation backend."""
    return sys.platform == "win32"
