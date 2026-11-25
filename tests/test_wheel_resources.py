"""Install-shaped wheel checks run outside the checkout and editable imports."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path


def test_built_wheel_contains_usable_icons_and_localized_manuals(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-m", "hatchling", "build", "-t", "wheel", "-d", str(tmp_path)],
                   cwd=project, check=True, capture_output=True, timeout=120)
    wheel = next(tmp_path.glob("*.whl"))
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)
    code = '''
import re
from pathlib import Path
import materials_data_studio
from PySide6.QtWidgets import QApplication
from materials_data_studio.ui.icons import TOOLBAR_ICON_NAMES, toolbar_icon
from materials_data_studio.ui.manual import resolve_user_manual_path, resolve_graph_manual_path
from materials_data_studio.ui.preview_assets import preview_icon
assert Path(materials_data_studio.__file__).resolve().is_relative_to(Path.cwd() / "installed")
application = QApplication([])
assert not preview_icon("marker:16:light").isNull()
assert not preview_icon("colormap:Viridis").isNull()
for theme in ("light", "dark"):
    for name in TOOLBAR_ICON_NAMES:
        assert not toolbar_icon(name, theme).isNull()
for resolve in (resolve_user_manual_path, resolve_graph_manual_path):
    for language in ("en", "ja"):
        manual = resolve(language)
        images = re.findall(r"!\\[[^\\]]*\\]\\((screenshots/[^)]+\\.png)\\)", manual.read_text(encoding="utf-8"))
        assert images, manual
        for image in images:
            assert (manual.parent / image).is_file(), image
'''
    completed = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                               env={**os.environ, "PYTHONPATH": str(installed)},
                               check=False, capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stdout + completed.stderr
