"""Add titles and bookmarks to the generated single-figure PDFs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from materials_data_studio.graph_mcp.inputs import Workspace
from materials_data_studio.graph_mcp.review import create_review_pdf
from materials_data_studio.graph_mcp.schema import ReviewPage


def build_review_pdf(directory: Path, suite: str) -> Path:
    root = directory.resolve(strict=True)
    if suite == "solid-state-v2":
        manifest = root / "manifest.json"
        target = root / "all_domain_figures.pdf"
        figure_pattern = "cases/{id}/figure.pdf"
    else:
        manifest = root / "checks/manifest.json"
        target = root / "review/all_figures.pdf"
        figure_pattern = "figures/{id}.pdf"
    cases = json.loads(manifest.read_text(encoding="utf-8"))["cases"]
    pages = [
        ReviewPage(pdf=figure_pattern.format(id=case["id"]), title=case["title"])
        for case in cases
    ]
    with TemporaryDirectory(prefix=".review-", dir=target.parent) as work:
        staged = Path(work) / target.name
        create_review_pdf(Workspace(root), staged.relative_to(root).as_posix(), pages)
        staged.replace(target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--suite", choices=("solid-state-v2", "exploratory-v1"), required=True)
    arguments = parser.parse_args()
    print(build_review_pdf(arguments.directory, arguments.suite))
