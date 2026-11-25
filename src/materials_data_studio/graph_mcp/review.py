"""Compose titled review pages from existing, title-free single-figure PDFs."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties, findfont, fontManager, get_font
from pypdf import PdfReader, PdfWriter, Transformation

from materials_data_studio.graph_mcp.inputs import PlotError, Workspace
from materials_data_studio.graph_mcp.schema import ReviewPage
from materials_data_studio.graph_mcp.service import ensure_new, stage_output

_TITLE_FONTS = ("DejaVu Sans", "Noto Sans CJK JP", "Yu Gothic", "Meiryo", "Hiragino Sans")


def _title_page(title: str, width: float, height: float) -> BytesIO:
    installed = {font.name for font in fontManager.ttflist}
    family = [name for name in _TITLE_FONTS if name in installed]
    fonts = [get_font(findfont(FontProperties(family=name))) for name in family]
    if any(not any(font.get_char_index(ord(char)) for font in fonts) for char in title):
        raise PlotError(
            "missing_title_font",
            "pages.title",
            "Install a font with the title's glyphs, such as Noto Sans CJK JP, or supply a supported title.",
        )
    figure = Figure(figsize=(width / 72, height / 72), dpi=72)
    canvas = FigureCanvasAgg(figure)
    text = figure.text(
        24 / width, 1 - 24 / height, title, va="top", family=family, fontsize=15, parse_math=False
    )
    measured = text.get_window_extent(canvas.get_renderer()).width
    text.set_fontsize(min(15, 15 * (width - 48) / max(1, measured)))
    buffer = BytesIO()
    figure.savefig(buffer, format="pdf")
    buffer.seek(0)
    return buffer


def create_review_pdf(
    workspace: Workspace, filename: str, pages: list[ReviewPage]
) -> dict[str, Any]:
    target = workspace.path(filename, output=True)
    if target.suffix.casefold() != ".pdf":
        raise PlotError("invalid_output_format", filename, "Use a .pdf output name.")
    ensure_new(target)
    writer = PdfWriter()
    for number, spec in enumerate(pages):
        path = workspace.path(spec.pdf)
        if path.suffix.casefold() != ".pdf":
            raise PlotError("invalid_review_input", spec.pdf, "Choose a single-figure PDF.")
        source = PdfReader(path)
        if source.is_encrypted or len(source.pages) != 1:
            raise PlotError(
                "invalid_review_input",
                spec.pdf,
                "Review inputs must be single-page, unencrypted PDFs.",
            )
        figure = source.pages[0]
        if figure.rotation:
            figure.transfer_rotation_to_content()
        figure.pop("/Annots", None)
        figure_width, figure_height = float(figure.mediabox.width), float(figure.mediabox.height)
        if not 0 < figure_width <= 4000 or not 0 < figure_height <= 4000:
            raise PlotError(
                "invalid_review_input",
                spec.pdf,
                "Figure page dimensions must be between 0 and 4000 points.",
            )
        width, height = max(480, figure_width + 48), figure_height + 88
        with _title_page(spec.title, width, height) as title:
            destination = writer.add_page(PdfReader(title).pages[0])
        destination.merge_transformed_page(
            figure,
            Transformation().translate(
                tx=(width - figure_width) / 2 - float(figure.mediabox.left),
                ty=24 - float(figure.mediabox.bottom),
            ),
        )
        writer.add_outline_item(spec.title, number)
    with stage_output(target, directory=False) as staging:
        writer.write(staging)
    return {
        "pdf": target.relative_to(workspace.root).as_posix(),
        "pages": len(pages),
        "titles": [page.title for page in pages],
    }
