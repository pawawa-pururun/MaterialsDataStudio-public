"""Include application assets and only the images referenced by shipped manuals."""

from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

MANUALS = ("user_manual.md", "user_manual_en.md", "graph_viewer_manual.md", "graph_viewer_manual_en.md")


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel":
            return
        root = Path(self.root)
        sys.path.insert(0, str(root / "src"))
        try:
            runpy.run_path(str(root / "scripts/render_graph_previews.py"))["ensure_assets"](root, check_only=True)
        finally:
            sys.path.pop(0)
        destination = "materials_data_studio/_assets"
        included = build_data.setdefault("force_include", {})
        included[str(root / "resources")] = f"{destination}/resources"
        included[str(root / "THIRD_PARTY_NOTICES.md")] = f"{destination}/THIRD_PARTY_NOTICES.md"
        for name in (*MANUALS, "building_and_licenses.md", "building_and_licenses_ja.md",
                     "cross_platform.md", "cross_platform_en.md"):
            manual = root / "docs" / name
            included[str(manual)] = f"{destination}/docs/{name}"
            for relative in re.findall(r"!\[[^\]]*\]\((screenshots/[^)]+\.png)\)", manual.read_text(encoding="utf-8")):
                image = (root / "docs" / relative).resolve()
                if not image.is_relative_to((root / "docs/screenshots").resolve()) or not image.is_file():
                    raise ValueError(f"Invalid manual image: {relative}")
                included[str(image)] = f"{destination}/docs/{relative}"
