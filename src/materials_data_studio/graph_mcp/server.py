"""Run the Graph Editor MCP server over local stdio."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import Field, ValidationError
from pypdf.errors import PyPdfError

from materials_data_studio.core.exceptions import MaterialsDataStudioError
from materials_data_studio.graph_mcp.inputs import PlotError, Workspace, load_table
from materials_data_studio.graph_mcp.review import create_review_pdf
from materials_data_studio.graph_mcp.schema import (
    ColumnIndex,
    FigureRecipe,
    FilePath,
    ImageFormat,
    Request,
    ReviewPage,
    Source,
)
from materials_data_studio.graph_mcp.service import create_figure, inspect_document
from materials_data_studio.version import __version__


class InputPreview(Request):
    columns: list[ColumnIndex] = Field(min_length=1, max_length=8)
    start: int = Field(default=0, ge=0)
    count: int = Field(default=8, ge=1, le=32)


class InspectInput(Request):
    source: Source
    preview: InputPreview | None = None


class CreateFigure(Request):
    recipe: FigureRecipe
    output_dir: FilePath | None = Field(
        default=None, description="New directory inside the workspace, required for output."
    )
    formats: list[ImageFormat] = Field(default_factory=lambda: ["png", "svg", "pdf"], max_length=3)
    dpi: int = Field(default=180, ge=72, le=600)
    validate_only: bool = False


class InspectDocument(Request):
    path: FilePath
    graph: str | None = None
    wave: str | None = Field(
        default=None, description="Exact root: path or stable ID from the document state."
    )
    start: int = Field(default=0, ge=0)
    count: int = Field(default=16, ge=1, le=256)


class CreateReview(Request):
    output_pdf: FilePath
    pages: Annotated[list[ReviewPage], Field(min_length=1, max_length=64)]


def _inspect_input(workspace: Workspace, request: InspectInput) -> dict[str, Any]:
    table = load_table(workspace, request.source)
    preview = request.preview
    return {
        "path": request.source.path,
        "kind": request.source.kind,
        **table.describe(),
        **(
            {"preview": table.preview(preview.columns, preview.start, preview.count)}
            if preview
            else {}
        ),
    }


def _create(workspace: Workspace, request: CreateFigure) -> dict[str, Any]:
    if len(set(request.formats)) != len(request.formats):
        raise PlotError("duplicate_format", "formats", "Choose each export format at most once.")
    return create_figure(
        workspace,
        request.recipe,
        output_dir=request.output_dir,
        formats=request.formats,
        dpi=request.dpi,
        validate_only=request.validate_only,
    )


def _inspect_document(workspace: Workspace, request: InspectDocument) -> dict[str, Any]:
    return inspect_document(
        workspace,
        request.path,
        graph=request.graph,
        wave=request.wave,
        start=request.start,
        count=request.count,
    )


def _review(workspace: Workspace, request: CreateReview) -> dict[str, Any]:
    return create_review_pdf(workspace, request.output_pdf, request.pages)


def _result(payload: dict[str, Any], *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text", text=json.dumps(payload, ensure_ascii=False, allow_nan=False)
            )
        ],
        structuredContent=payload,
        isError=error,
    )


def _error(code: str, field: str, message: str) -> dict[str, str]:
    return {"code": code, "field": field, "message": message}


def make_server(workspace: Workspace) -> Server:
    server = Server(
        "materials-data-studio",
        version=__version__,
        instructions="Make editable Graph Editor figures from local measurements. Inspect input headers first. "
        "Confirm ambiguous units, sample parameters and CIF radiation. Use validate_only for a dry run. "
        "Figure exports omit titles. Add page titles separately with create_review_pdf.",
    )
    definitions: dict[str, tuple[type[Request], Callable[..., dict[str, Any]], str, bool]] = {
        "inspect_input": (
            InspectInput,
            _inspect_input,
            "Inspect local CSV, TSV, headerless text, Quantum Design MPMS/PPMS [Data] exports or Rigaku RASX column headings and data row counts.",
            True,
        ),
        "create_figure": (
            CreateFigure,
            _create,
            "Validate or create a new editable MDSG figure plus PNG/SVG/PDF and a manifest. Supports XRD stacks, CIF/peak reference strips, supplied Rietveld overlays and condition maps, and scientific XY panels.",
            False,
        ),
        "inspect_document": (
            InspectDocument,
            _inspect_document,
            "Read stable wave, graph, trace and axis state from a saved MDSG or preview values in a selected wave.",
            True,
        ),
        "create_review_pdf": (
            CreateReview,
            _review,
            "Assemble single-figure PDFs into a review PDF with supplied page titles and bookmarks outside each figure.",
            False,
        ),
    }
    limiter = anyio.CapacityLimiter(1)  # Matplotlib and its font manager are process-global.

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=description,
                inputSchema=model.model_json_schema(),
                annotations=types.ToolAnnotations(
                    readOnlyHint=read_only,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
            for name, (model, _, description, read_only) in definitions.items()
        ]

    @server.call_tool(
        validate_input=False
    )  # Pydantic below returns structured field-level validation errors.
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        try:
            if name not in definitions:
                raise PlotError("unknown_tool", name, "List the available Graph Editor tools.")
            model, run, _, _ = definitions[name]
            request = model.model_validate(arguments)
            result = await anyio.to_thread.run_sync(run, workspace, request, limiter=limiter)
            return _result({"ok": True, **result})
        except ValidationError as exc:
            details = [
                _error(e["type"], ".".join(map(str, e["loc"])), e["msg"])
                for e in exc.errors(include_input=False, include_context=False, include_url=False)
            ]
        except PlotError as exc:
            details = [_error(exc.code, exc.field, str(exc))]
        except (
            MaterialsDataStudioError,
            ValueError,
            csv.Error,
            zipfile.BadZipFile,
            PyPdfError,
        ) as exc:
            details = [_error("invalid_data", "input", str(exc))]
        except OSError as exc:
            details = [_error("file_error", "path", exc.strerror or str(exc))]
        return _result({"ok": False, "errors": details}, error=True)

    return server


async def _run(root: Path) -> None:
    server = make_server(Workspace(root))
    async with stdio_server() as (incoming, outgoing):
        await server.run(incoming, outgoing, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, required=True, help="Existing local root for inputs and outputs."
    )
    args = parser.parse_args()
    root = args.workspace.expanduser().resolve()
    if not root.is_dir():
        parser.error("--workspace must be an existing directory")
    logging.basicConfig(level=logging.WARNING)
    anyio.run(_run, root)


if __name__ == "__main__":
    main()
