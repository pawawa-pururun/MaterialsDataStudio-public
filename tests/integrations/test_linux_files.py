"""Registration offers file types without changing another application's defaults."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from materials_data_studio.integrations import linux_files


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="freedesktop registration")
def test_registration_creates_launcher_mime_and_icons_only_in_requested_directory(tmp_path: Path, monkeypatch, qapp) -> None:
    calls = []
    monkeypatch.setattr(linux_files.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(linux_files.subprocess, "run", lambda args, **_kwargs: calls.append(args))
    linux_files.register_document_types(tmp_path)
    desktop = (tmp_path / "applications" / linux_files.DESKTOP_ID).read_text(encoding="utf-8")
    assert " %F\n" in desktop and "Terminal=false" in desktop
    assert '"-m" "materials_data_studio"' in desktop
    xml = ET.parse(tmp_path / "mime/packages/materials-data-studio.xml")
    assert {item.attrib["pattern"] for item in xml.iter("{http://www.freedesktop.org/standards/shared-mime-info}glob")} == {"*.mdss", "*.mdsession", "*.mdsg"}
    assert len(list((tmp_path / "icons").rglob("*.png"))) == 3
    assert not (tmp_path / "applications/mimeapps.list").exists()
    assert all(args[0].endswith(("update-mime-database", "update-desktop-database")) for args in calls)


def test_desktop_exec_quotes_reserved_characters_and_field_codes() -> None:
    command = linux_files.desktop_command(['/a path/with"$`%/MDS', "-m", "materials_data_studio"])
    assert command.endswith('"-m" "materials_data_studio" %F')
    assert "%%" in command and '\\\\"' in command and "\\\\$" in command and "\\\\`" in command
    with pytest.raises(ValueError):
        linux_files.desktop_command(["/path\nExec=other"])
