"""Read local measurement columns without guessing the units or dropping points."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from threading import Event
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from materials_data_studio.graph_mcp.schema import Column, Source
from materials_data_studio.modules.ppms.io import read_ppms_text
from materials_data_studio.modules.xrd.parser import parse_xrd_rasx
from materials_data_studio.tools.graph_waves import column_names, detect_start, read_text, text_rows

MAX_INPUT_BYTES = 64 * 1024**2
MAX_CELLS = 8_000_000  # Total numerical values used in one figure.
Array = NDArray[np.float64]


class PlotError(ValueError):
    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


class InputFiles(Protocol):
    """Resolve a file explicitly available to the figure builder."""

    def path(self, value: str, *, max_bytes: int = MAX_INPUT_BYTES) -> Path: ...


@dataclass(frozen=True)
class Workspace:
    root: Path

    def path(self, value: str, *, output: bool = False, max_bytes: int = MAX_INPUT_BYTES) -> Path:
        try:
            if output:
                raw = self.root / value
                path = (raw.parent.resolve() / raw.name).absolute()
                if raw.name in {"", ".", ".."} or path.is_symlink():
                    raise ValueError("invalid output name")
            else:
                path = (self.root / value).resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise PlotError(
                "invalid_path", value, "Path could not be resolved inside the workspace."
            ) from exc
        if path == self.root or not path.is_relative_to(self.root):
            raise PlotError(
                "outside_workspace", value, "Use a path inside the configured workspace."
            )
        if output:
            if not path.parent.is_dir():
                raise PlotError(
                    "missing_directory", value, "The parent directory must already exist."
                )
        else:
            if not path.is_file():
                raise PlotError("missing_file", value, "Provide a readable regular file.")
            if path.stat().st_size > max_bytes:
                raise PlotError(
                    "input_too_large",
                    value,
                    f"This input type is limited to {max_bytes // 1024**2} MiB.",
                )
        return path


@dataclass
class Table:
    headings: list[str]
    rows: list[list[str]]
    first_record: int
    metadata: dict[str, Any] = field(default_factory=dict)
    invalid_rows: int = 0
    numeric_data: Array | None = None

    @property
    def row_count(self) -> int:
        return (
            len(self.numeric_data)
            if self.numeric_data is not None
            else sum(bool(row) for row in self.rows)
        )

    def records(self):
        return ((index, row) for index, row in enumerate(self.rows, self.first_record) if row)

    def describe(self) -> dict[str, Any]:
        return {
            "columns": [{"index": i, "header": name} for i, name in enumerate(self.headings)],
            "rows": self.row_count,
            "first_data_record": self.first_record,
            "invalid_rows": self.invalid_rows,
            "metadata": self.metadata,
        }

    def preview(self, columns: list[int], start: int, count: int) -> list[list[str | float | None]]:
        if start >= self.row_count or any(index >= len(self.headings) for index in columns):
            raise PlotError(
                "invalid_range", "preview", "Select preview columns and rows within the table."
            )
        if self.numeric_data is not None:
            return self.numeric_data[start : start + count, columns].tolist()
        return [
            [row[i][:120] if i < len(row) else None for i in columns]
            for _, row in islice(self.records(), start, start + count)
        ]

    def numeric(self, binding: Column, name: str, *, cancelled: Event | None = None) -> Array:
        field_name = f"columns.{name}"
        if isinstance(binding.column, str):
            matches = [i for i, header in enumerate(self.headings) if header == binding.column]
            if len(matches) != 1:
                raise PlotError(
                    "column_selection",
                    field_name,
                    "Select one existing column by its exact header or zero-based index.",
                )
            index = matches[0]
        else:
            index = binding.column
            if index >= len(self.headings):
                raise PlotError(
                    "column_selection", field_name, "Column index is outside the file's headers."
                )
        if self.invalid_rows:
            raise PlotError(
                "invalid_input_rows",
                field_name,
                f"The RASX parser rejected {self.invalid_rows} rows. Check the file before plotting.",
            )
        if binding.rows is None:
            first, stop = 0, None
        else:
            first, stop = binding.rows
            if not 0 <= first < stop <= self.row_count:
                raise PlotError(
                    "invalid_range",
                    f"{field_name}.rows",
                    "Select a nonempty row range inside the table.",
                )
        if self.numeric_data is not None:
            return self.numeric_data[first:stop, index]

        numbers = []
        for record, row in islice(self.records(), first, stop):
            if cancelled is not None and record % 1024 == 0 and cancelled.is_set():
                raise InterruptedError("Stopped reading plot columns")
            if index >= len(row):
                raise PlotError(
                    "invalid_input_rows", field_name, f"Column is absent at record {record}."
                )
            cell = row[index]
            if binding.missing == "gap" and cell.casefold() in {"", "nan", "na", "n/a"}:
                numbers.append(np.nan)
                continue
            try:
                value = float(cell.replace("D", "E").replace("d", "e"))
            except ValueError as exc:
                raise PlotError(
                    "invalid_input_rows", field_name, f"Expected a number at record {record}."
                ) from exc
            if not np.isfinite(value):
                raise PlotError(
                    "invalid_input_rows", field_name, f"Non-finite number at record {record}."
                )
            numbers.append(value)
        if not numbers:
            raise PlotError("empty_data", field_name, "The selected column has no data records.")
        return np.asarray(numbers, dtype=float)


def _quantum_design_header(rows: list[list[str]], path: str) -> tuple[int, dict[str, Any]]:
    marker = next((i for i, row in enumerate(rows) if row and row[0].casefold() == "[data]"), None)
    if marker is None:
        raise PlotError("missing_header", path, "Quantum Design text requires a [Data] section.")
    metadata = {
        "weight_header_values": [
            row[2]
            for row in rows[:marker]
            if len(row) >= 3 and row[0].casefold() == "info" and row[1].casefold() == "weight"
        ][:10],
    }
    return marker + 1, metadata


def load_table(
    workspace: InputFiles, source: Source, *,
    infer_start: bool = False, cancelled: Event | None = None,
) -> Table:
    path = workspace.path(source.path)
    if source.kind == "rasx":
        parsed = parse_xrd_rasx(path)
        return Table(
            ["two_theta", "intensity"],
            [],
            1,
            {"two_theta_unit": "degree", "warnings": parsed.warnings[:5]},
            invalid_rows=parsed.invalid_rows,
            numeric_data=np.column_stack((parsed.x, parsed.intensity)),
        )
    if source.kind == "quantum_design":
        rows = text_rows(read_ppms_text(path), "Comma", cancelled=cancelled)
        start, metadata = _quantum_design_header(rows, source.path)
    else:
        delimiter: str = source.delimiter
        if delimiter == "Auto" and not infer_start:
            delimiter = {".csv": "Comma", ".tsv": "Tab"}.get(path.suffix.lower(), "Auto")
        rows = text_rows(read_text(path, cancelled=cancelled), delimiter, cancelled=cancelled)
        if infer_start and any(rows):
            start = detect_start(rows, cancelled=cancelled)
            headings = column_names(rows, start) or [""] * len(rows[start])
            records = [row if not row or not row[0].startswith(("#", "*")) else [] for row in rows[start:]]
            return Table(headings, records, start + 1)
        start, metadata = source.first_record - 1, {}
        # Keep record positions accurate even when a text export has comments.
        rows = [row if not row or not row[0].startswith(("#", "*")) else [] for row in rows]
    start = next((i for i in range(start, len(rows)) if any(rows[i])), len(rows))
    if start == len(rows):
        raise PlotError(
            "empty_data", source.path, "No table records found at the requested location."
        )
    if source.header or source.kind == "quantum_design":
        headings, start = rows[start], start + 1
    else:
        headings = ["" for _ in rows[start]]
    return Table(headings, rows[start:], start + 1, metadata)


def paired(first: Array, second: Array, field: str) -> None:
    if first.shape != second.shape:
        raise PlotError(
            "length_mismatch",
            field,
            f"Expected paired rows of equal length, got {len(first)} and {len(second)}.",
        )


def finite(values: Array, field: str) -> None:
    if not np.isfinite(values).all():
        raise PlotError(
            "missing_values",
            field,
            "These coordinates or intensities require finite values at every row.",
        )


def unit_key(unit: str) -> str:
    return unit.replace(" ", "").replace("µ", "u").replace("μ", "u").replace("Ω", "ohm")
