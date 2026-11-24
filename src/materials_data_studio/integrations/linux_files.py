"""Offer MDS documents to freedesktop desktops without changing default apps."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from materials_data_studio.core.resources import resource_root

DESKTOP_ID = "org.kageyamalab.MaterialsDataStudio.desktop"
MIME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-materials-data-studio-session">
    <comment>Materials Data Studio Session</comment>
    <glob pattern="*.mdss"/><glob pattern="*.mdsession"/>
  </mime-type>
  <mime-type type="application/x-materials-data-studio-graph">
    <comment>Materials Data Studio Graph</comment><glob pattern="*.mdsg"/>
  </mime-type>
</mime-info>
"""


def desktop_command(arguments: list[str]) -> str:
    """Quote literal argv for Desktop Entry Exec, including percent field codes."""
    quoted = []
    for value in arguments:
        if any(char in value for char in "\x00\r\n"):
            raise ValueError("Desktop commands must not contain control separators")
        value = value.replace("%", "%%").replace("\\", "\\\\")
        for char in ('"', "`", "$"):
            value = value.replace(char, "\\" + char)
        # Desktop Entry string unescaping precedes Exec argument unescaping.
        quoted.append('"' + value.replace("\\", "\\\\") + '"')
    return " ".join(quoted) + " %F"


def register_document_types(directory: Path | None = None) -> None:
    """Write per-user MIME/launcher/icon entries and refresh available caches."""
    if not sys.platform.startswith("linux"):
        return
    from PySide6.QtGui import QImage

    root = directory or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command += ["-m", "materials_data_studio"]
    applications = root / "applications"
    packages = root / "mime/packages"
    applications.mkdir(parents=True, exist_ok=True)
    packages.mkdir(parents=True, exist_ok=True)
    for source, category, name in (
        ("materials-data-studio.ico", "apps", "materials-data-studio"),
        ("mdss.ico", "mimetypes", "application-x-materials-data-studio-session"),
        ("mdsg.ico", "mimetypes", "application-x-materials-data-studio-graph"),
    ):
        icons = root / "icons/hicolor/256x256" / category
        icons.mkdir(parents=True, exist_ok=True)
        image = QImage(str(resource_root() / "resources/icons" / source))
        if image.isNull() or not image.save(str(icons / (name + ".png"))):
            raise OSError(f"Could not install document icon: {source}")
    (applications / DESKTOP_ID).write_text(
        "[Desktop Entry]\nType=Application\nName=Materials Data Studio\n"
        "Comment=Plot and analyze materials measurement data\n"
        f"Exec={desktop_command(command)}\nIcon=materials-data-studio\nTerminal=false\n"
        "Categories=Education;Science;\n"
        "MimeType=application/x-materials-data-studio-session;application/x-materials-data-studio-graph;\n",
        encoding="utf-8",
    )
    (packages / "materials-data-studio.xml").write_text(MIME_XML, encoding="utf-8")
    for utility, location in (("update-mime-database", root / "mime"),
                              ("update-desktop-database", applications)):
        executable = shutil.which(utility)
        if executable:
            subprocess.run([executable, str(location)], check=False, capture_output=True, timeout=15)
