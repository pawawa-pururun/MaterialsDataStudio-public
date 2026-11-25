"""Validate, persist, and read back editable Graph Editor documents."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np

from materials_data_studio.graph_mcp.data import Data, load_data
from materials_data_studio.graph_mcp.graphs import xy_graphs
from materials_data_studio.graph_mcp.inputs import InputFiles, PlotError, Workspace
from materials_data_studio.graph_mcp.schema import (
    FigurePlot,
    FigureRecipe,
    ImageFormat,
    XrdMap,
    XrdStack,
    XYPlot,
)
from materials_data_studio.graph_mcp.xrd import map_graphs, rietveld_graphs, stack_graphs
from materials_data_studio.tools.graph_document import (
    EditableGraphDocument,
    load_graph_document,
    save_graph_document,
)
from materials_data_studio.tools.graph_export import GraphicsSettings, save_graphics
from materials_data_studio.tools.graph_render import IgorMatplotlibRenderer
from materials_data_studio.tools.graph_waves import empty_document, put_waves, validate_references
from materials_data_studio.tools.pxp_model import PxpGraph, PxpWave
from materials_data_studio.version import __version__


def build_figure(workspace: Workspace, recipe: FigureRecipe) -> tuple[str, EditableGraphDocument]:
    return build_document(workspace, load_data(workspace, recipe), recipe.plot)


def build_document(workspace: InputFiles, data: Data, plot: FigurePlot) -> tuple[str, EditableGraphDocument]:
    """Build the same editable figure from recipe files or interactive column bindings."""
    if isinstance(plot, XYPlot):
        name, graphs = xy_graphs(data, plot)
    elif isinstance(plot, XrdStack):
        name, graphs = stack_graphs(workspace, data, plot)
    elif isinstance(plot, XrdMap):
        name, graphs = map_graphs(data, plot)
    else:
        name, graphs = rietveld_graphs(workspace, data, plot)
    document = empty_document()
    document.current = put_waves(document, list(data.waves.values()))
    # Graph Editor selects the first graph when opening a new document.
    document.current.graphs = tuple(sorted(graphs, key=lambda graph: graph.name != name))
    validate_references(document, document.current)
    for graph in graphs:
        report = document.compatibility(graph.name)
        if report.rendered == "blocked":
            diagnostic = next(d for d in report.diagnostics if d.severity == "error")
            raise PlotError(
                "graph_incompatible", graph.name, f"{diagnostic.property}: {diagnostic.message}"
            )
    return name, document


def _wave_info(wave: PxpWave) -> dict[str, Any]:
    return {
        "id": wave.id,
        "path": wave.igor_path,
        "shape": wave.shape,
        "unit": wave.data_units,
        "dtype": wave.dtype,
        "note": wave.wave_note,
    }


def _graph_info(graph: PxpGraph) -> dict[str, Any]:
    return {
        "name": graph.name,
        "kind": graph.window_kind,
        "host": graph.host or None,
        "host_rect": graph.host_rect,
        "size_inches": IgorMatplotlibRenderer.export_size(graph),
        "axes": [
            {
                "name": axis.name,
                "label": axis.label_raw,
                "limits": axis.limits,
                "reverse": bool(axis.style.reverse),
                "major_ticks": axis.style.manual_ticks,
                "minor_ticks": axis.style.manual_minor,
                "tick_count": axis.style.tick_count,
                "show_labels": axis.style.no_label not in {1, 2},
                "scale": "log" if axis.style.log else "linear",
                "user_ticks": axis.style.user_ticks,
            }
            for axis in graph.axes
        ],
        "traces": [
            {
                "name": trace.name,
                "x": trace.x_wave,
                "y": trace.y_wave,
                "offset": trace.offset,
                "color_igor": trace.color_igor,
                "line_style": trace.line_style,
                "mode": trace.mode,
                "error_y": trace.error_high,
            }
            for trace in graph.traces
        ],
        "annotations": [
            {
                "name": item.name,
                "text": item.raw,
                "anchor": item.style.anchor,
                "offset_percent": (item.style.x_percent, item.style.y_percent),
            }
            for item in graph.annotations
        ],
        "images": [
            {
                "wave": image.wave,
                "x_edges": image.x_wave,
                "y_edges": image.y_wave,
                "palette": image.color_table,
                "range": image.color_range,
                "colorbar_label": image.colorbar_label_raw,
            }
            for image in graph.images
        ],
        "panels": [asdict(item) for item in graph.layout_items],
    }


def document_state(document: EditableGraphDocument, graph: str | None = None) -> dict[str, Any]:
    graphs = [item for item in document.current.graphs if graph is None or graph == item.name]
    if graph is not None and not graphs:
        raise PlotError("unknown_graph", graph, "Select a graph name listed in this document.")
    projection = document.render_source()
    return {
        "document_id": document.document_id,
        "graphs": [_graph_info(item) for item in graphs],
        "waves": [_wave_info(wave) for wave in projection.waves],
    }


def inspect_document(
    workspace: Workspace,
    filename: str,
    *,
    graph: str | None,
    wave: str | None,
    start: int,
    count: int,
) -> dict[str, Any]:
    path = workspace.path(filename, max_bytes=256 * 1024**2)
    if path.suffix.casefold() != ".mdsg":
        raise PlotError(
            "invalid_document", filename, "Provide a saved Graph Editor .mdsg document."
        )
    document = load_graph_document(path)
    if wave is None:
        return document_state(document, graph)
    source = document.render_source()
    item = next((w for w in source.waves if wave in {w.id, w.igor_path}), None)
    if item is None:
        raise PlotError(
            "unknown_wave", wave, "Select an exact wave path or wave id from the saved document."
        )
    flattened = item.data.ravel(order="C")
    if start >= flattened.size:
        raise PlotError("invalid_range", "start", "Start is outside the selected wave.")
    subset = flattened[start : start + count]
    if subset.dtype.kind in "biuf":
        values = [value.item() if np.isfinite(value) else None for value in subset]
    elif subset.dtype.kind in "SU":
        values = subset.astype(str).tolist()
    else:
        raise PlotError(
            "unsupported_dtype", wave, "Wave preview supports real numerical or text data."
        )
    return {
        "document_id": document.document_id,
        "wave": _wave_info(item),
        "start": start,
        "values": values,
        "order": "C",
    }


def ensure_new(target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise PlotError(
            "output_exists", target.name, "Choose a new output name or inspect the existing output."
        )


@contextmanager
def stage_output(target: Path, *, directory: bool) -> Iterator[Path]:
    """Publish a complete result in one rename; concurrent callers cannot replace it."""
    ensure_new(target)
    lock = target.with_name(f".{target.name}.mds-lock")
    try:
        lock.touch(exist_ok=False)
    except FileExistsError as exc:
        raise PlotError(
            "output_busy", target.name, "Another request is writing to this output name."
        ) from exc
    try:
        with TemporaryDirectory(prefix=".mds-stage-", dir=target.parent) as temp:
            staging = Path(temp) / target.name
            if directory:
                staging.mkdir()
            yield staging
            ensure_new(target)
            staging.rename(target)
    finally:
        lock.unlink(missing_ok=True)


def create_figure(
    workspace: Workspace,
    recipe: FigureRecipe,
    *,
    output_dir: str | None,
    formats: list[ImageFormat],
    dpi: int,
    validate_only: bool,
) -> dict[str, Any]:
    if not validate_only and output_dir is None:
        raise PlotError(
            "missing_parameter",
            "output_dir",
            "Specify a new output directory inside the workspace.",
        )
    target = workspace.path(output_dir, output=True) if output_dir and not validate_only else None
    if target is not None:
        ensure_new(target)
    name, document = build_figure(workspace, recipe)
    state = document_state(document)
    result = {"graph": name, "state": state, "validated_only": validate_only}
    if target is None:
        return result

    filenames = {
        "document": "figure.mdsg",
        "manifest": "manifest.json",
        **{fmt: f"figure.{fmt}" for fmt in formats},
    }
    published = {
        kind: (target / filename).relative_to(workspace.root).as_posix()
        for kind, filename in filenames.items()
    }
    manifest = {
        "schema_version": 1,
        "application_version": __version__,
        "recipe": recipe.model_dump(mode="json"),
        "graph": name,
        "state": state,
        "dpi": dpi,
        "files": filenames,
    }
    with stage_output(target, directory=True) as staging:
        save_graph_document(staging / filenames["document"], document)
        for fmt in formats:
            save_graphics(
                staging / filenames[fmt],
                document,
                name,
                GraphicsSettings(format=fmt, dpi=dpi, rasterize_meshes=True),
            )
        (staging / filenames["manifest"]).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return {**result, "files": published}
