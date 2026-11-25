"""Bind locally selected measurements to the Graph Editor's shared plot recipes."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from typing import Literal

import numpy as np

from materials_data_studio.graph_mcp.data import Data, derive
from materials_data_studio.graph_mcp.inputs import (
    MAX_INPUT_BYTES,
    Array,
    PlotError,
    Table,
    Workspace,
    finite,
    load_table,
)
from materials_data_studio.graph_mcp.schema import (
    XY,
    Axis,
    Binary,
    CifReference,
    Column,
    FigurePlot,
    MapLongTable,
    MolarCp,
    MolarSusceptibility,
    Panel,
    PeakTable,
    Power,
    Scale,
    Scan,
    Source,
    Trace,
    XrdMap,
    XrdRietveld,
    XrdStack,
    XYPlot,
)
from materials_data_studio.graph_mcp.service import build_document
from materials_data_studio.plotting.igor_names import unique_igor_name
from materials_data_studio.tools.graph_document import EditableGraphDocument, GraphState
from materials_data_studio.tools.graph_waves import put_waves, validate_references
from materials_data_studio.tools.pxp_model import PxpWave

TemplateKind = Literal["xy", "xrd_stack", "xrd_map", "xrd_rietveld", "mpms_zfc_fc", "ppms_cp"]

TEMPLATE_NAMES: dict[TemplateKind, str] = {
    "xy": "XY plot",
    "xrd_stack": "XRD stacked scans",
    "xrd_map": "XRD condition map",
    "xrd_rietveld": "XRD Rietveld display",
    "mpms_zfc_fc": "MPMS ZFC / FC molar susceptibility",
    "ppms_cp": "PPMS Cp/T versus T²",
}


@dataclass(frozen=True, slots=True)
class Slot:
    key: str
    label: str
    unit: str = ""
    hints: tuple[str, ...] = ()
    required: bool = True


ANGLE = Slot("angle", "2θ", "degree", ("2theta", "two_theta", "2θ", "angle"))
INTENSITY = Slot("intensity", "Intensity", "count", ("intensity", "counts", "count"))
TEMPERATURE = Slot("temperature", "Temperature", "K", ("temperature", "temp", "t"))
FIELD = Slot("field", "Field", "Oe", ("magnetic_field", "field", "field_oe"))


def template_slots(
    kind: TemplateKind, scan_count: int = 1, peak_phases: tuple[int, ...] = (),
) -> tuple[Slot, ...]:
    if kind == "xy":
        return (
            Slot("x", "X", hints=("x", "time", "temperature", "field")),
            Slot("y", "Y", hints=("y", "signal", "intensity", "value")),
            Slot("sigma", "Y uncertainty", hints=("sigma", "uncertainty", "error"), required=False),
        )
    if kind == "xrd_map":
        return (
            ANGLE,
            Slot("condition", "Condition", hints=("condition", "temperature", "pressure")),
            INTENSITY,
        )
    if kind == "mpms_zfc_fc":
        return (
            replace(TEMPERATURE, label="ZFC temperature"),
            replace(FIELD, label="ZFC field"),
            Slot("zfc", "ZFC moment", "emu", ("moment_zfc", "zfc_moment", "zfc")),
            replace(TEMPERATURE, key="fc_temperature", label="FC temperature (default: ZFC)",
                    hints=("temperature_fc", "fc_temperature"), required=False),
            replace(FIELD, key="fc_field", label="FC field (default: ZFC)",
                    hints=("field_fc", "fc_field"), required=False),
            Slot("fc", "FC moment", "emu", ("moment_fc", "fc_moment", "fc")),
        )
    if kind == "ppms_cp":
        return (
            TEMPERATURE,
            Slot("capacity", "Heat capacity", "µJ/K", ("heat_capacity", "cp", "cp_uj_k", "capacity")),
            Slot("sigma", "Heat-capacity uncertainty", "µJ/K",
                 ("cp_error_uj_k", "cp_uncertainty", "cp_error", "sigma"), False),
            Slot("model", "Supplied Cp/T model", "mJ/(mol K²)",
                 ("cp_over_t_model", "reference"), False),
        )
    if kind == "xrd_rietveld":
        scans = (
            ANGLE,
            Slot("observed", "Observed intensity", "count", ("observed", "obs", "observed_intensity")),
            Slot("calculated_angle", "Calculated 2θ (default: observed)", "degree",
                 ("calculated_angle", "calc_2theta"), False),
            Slot("calculated", "Calculated intensity", "count",
                 ("calculated", "calculated_intensity", "calc", "ycalc")),
        )
    else:
        scans = (ANGLE,)
        for i in range(1, scan_count + 1):
            if i > 1:
                scans += (Slot(f"angle_{i}", f"Scan {i} 2θ (default: first scan)", "degree",
                               (f"2theta_{i}", f"two_theta_{i}"), False),)
            scans += (Slot(f"scan_{i}", f"Scan {i} intensity", "count",
                           (f"counts{i - 1}", f"scan{i}", f"scan_{i}", *INTENSITY.hints)
                           if i == 1 else (f"counts{i - 1}", f"scan{i}", f"scan_{i}")),)
    for i in peak_phases:
        scans += (Slot(f"phase_{i}_angle", f"Phase {i} Bragg positions", "degree",
                       (f"phase_{i}_2theta", f"phase_{i}_bragg", f"bragg_{i}", "bragg_positions")),)
        if kind == "xrd_stack":
            scans += (Slot(f"phase_{i}_intensity", f"Phase {i} relative intensity", "relative",
                           (f"phase_{i}_intensity", f"relative_intensity_{i}", "relative_intensity")),)
    return scans


def clean_label(text: str) -> str:
    return re.sub(r"[\\\x00-\x1f\x7f]", " ", text).strip()[:120]


def heading_parts(heading: str) -> tuple[str, str]:
    match = re.fullmatch(r"(.*?)\s*(?:\[([^\[\]]+)\]|\((.+)\))", heading)
    if match and match[1]:
        return clean_label(match[1]), clean_label(match[2] or match[3])[:80]
    return clean_label(heading), ""


@dataclass(frozen=True, slots=True)
class LoadedTable:
    path: Path
    table: Table
    count: int
    cells: int


def read_template_table(path: Path, cancelled: Event) -> LoadedTable:
    path = path.resolve(strict=True)
    scope = Workspace(path.parent)
    source = Source(path=path.name, kind="rasx" if path.suffix.lower() == ".rasx" else "table")
    table = load_table(scope, source, infer_start=True, cancelled=cancelled)
    count = table.row_count
    if not table.headings or not count:
        raise ValueError("The selected file has no measurement columns.")
    cells = table.numeric_data.size if table.numeric_data is not None else sum(map(len, table.rows))
    return LoadedTable(path, table, count, cells)


@dataclass(frozen=True, slots=True)
class InputColumn:
    title: str
    unit: str
    source: LoadedTable | PxpWave
    index: int = 0

    @property
    def display(self) -> str:
        if isinstance(self.source, PxpWave):
            description = self.source.igor_path
        else:
            description = f"{self.source.path.name} · {self.index + 1}"
            if self.title:
                description += f" · {self.title}"
        return f"{description} ({self.unit})" if self.unit else description


@dataclass(frozen=True, slots=True)
class Binding:
    column: InputColumn
    unit: str
    rows: tuple[int, int] | None = None

    def read(self, name: str, *, allow_gaps: bool, cancelled: Event) -> tuple[Array, dict]:
        if cancelled.is_set():
            raise InterruptedError("Stopped reading template data")
        source = self.column.source
        if isinstance(source, LoadedTable):
            binding = Column(source="input", column=self.column.index, unit=self.unit,
                             rows=self.rows, missing="gap" if allow_gaps else "error")
            values = source.table.numeric(binding, name, cancelled=cancelled)
            note = {"file": source.path.name, "column": self.column.index,
                    "header": self.column.title, "first_data_record": source.table.first_record}
        else:
            if len(source.shape) != 1 or np.dtype(source.dtype).kind not in "biuf":
                raise ValueError("Select a real one-dimensional wave.")
            values = np.asarray(source.data, dtype=float)
            if self.rows:
                first, stop = self.rows
                if not 0 <= first < stop <= len(values):
                    raise ValueError("Select a nonempty row range inside the wave.")
                values = values[first:stop]
            note = {"wave": source.igor_path}
        if np.isinf(values).any() or not len(values):
            raise ValueError("Select nonempty measurement data without infinite values.")
        if not allow_gaps:
            finite(values, name)
        return values, {**note, "rows": self.rows, "unit": self.unit}


@dataclass(frozen=True, slots=True)
class Phase:
    label: str
    cif: Path | None = None
    wavelength: float | None = None


@dataclass(frozen=True, slots=True)
class TemplateRequest:
    kind: TemplateKind
    bindings: Mapping[str, Binding]
    scan_labels: tuple[str, ...] = ("",)
    phases: tuple[Phase, ...] = ()
    normalize: bool = False
    sample_mass_mg: float | None = None
    molar_mass_g_mol: float | None = None


@dataclass(frozen=True, slots=True)
class SelectedCifs:
    files: Mapping[str, Path]

    def path(self, value: str, *, max_bytes: int = MAX_INPUT_BYTES) -> Path:
        if value not in self.files:
            raise PlotError("missing_file", value, "Select a reference CIF file.")
        selected = self.files[value]
        return Workspace(selected.parent).path(selected.name, max_bytes=max_bytes)


def _references(request: TemplateRequest) -> tuple[SelectedCifs, list[PeakTable | CifReference]]:
    files: dict[str, Path] = {}
    refs: list[PeakTable | CifReference] = []
    for i, phase in enumerate(request.phases, 1):
        if phase.cif is not None:
            if phase.wavelength is None:
                raise ValueError(f"Phase {i}: enter the measured X-ray wavelength in Å.")
            # A local alias retains the selected basename without serializing an absolute path.
            key = f"{i}-{phase.cif.name}"
            files[key] = phase.cif
            refs.append(CifReference(kind="cif", label=phase.label, path=key,
                                     wavelength_angstrom=phase.wavelength))
        else:
            refs.append(PeakTable(kind="peaks", label=phase.label, angles=f"phase_{i}_angle",
                                  intensity=f"phase_{i}_intensity" if request.kind == "xrd_stack" else None))
    return SelectedCifs(files), refs


def _axis_label(request: TemplateRequest, key: str, default: str) -> str:
    binding = request.bindings[key]
    title = binding.column.title or default
    return f"{title} ({binding.unit})" if binding.unit != "1" else title


def _scan_angle(request: TemplateRequest, angle: str, intensity: str) -> str:
    if angle in request.bindings:
        return angle
    first = request.bindings["angle"].column.source
    scan = request.bindings[intensity].column.source
    if isinstance(first, LoadedTable) and isinstance(scan, LoadedTable) and first.path != scan.path:
        raise ValueError("Select a 2θ column for each scan from a different file.")
    return "angle"


def _plot(request: TemplateRequest, data: Data, refs: list[PeakTable | CifReference]) -> FigurePlot:
    if request.kind == "xrd_stack":
        return XrdStack(kind="xrd_stack", scans=[
            Scan(x=_scan_angle(request, f"angle_{i}", f"scan_{i}"), y=f"scan_{i}", label=label)
            for i, label in enumerate(request.scan_labels, 1)
        ], normalization="peak100" if request.normalize else "none", references=refs)
    if request.kind == "xrd_map":
        return XrdMap(kind="xrd_map", data=MapLongTable(kind="long_table", x="angle", condition="condition",
                                                       intensity="intensity"),
                      condition_label=_axis_label(request, "condition", "Condition"),
                      condition_unit=data.unit("condition"),
                      normalization="global_max" if request.normalize else "none")
    if request.kind == "xrd_rietveld":
        return XrdRietveld(kind="xrd_rietveld", observed=XY(x="angle", y="observed"),
                          calculated=XY(x=_scan_angle(request, "calculated_angle", "calculated"),
                                        y="calculated"), phases=refs)
    if request.kind == "xy":
        return XYPlot(kind="xy", panels=[
            Panel(name="xy_plot", x=Axis(label=_axis_label(request, "x", "X")),
                  y=Axis(label=_axis_label(request, "y", "Y")),
                  traces=[Trace(name="data", x="x", y="y", style="line_points",
                                error_y="sigma" if "sigma" in data.waves else None)])
        ])
    mass, molar = request.sample_mass_mg, request.molar_mass_g_mol
    if mass is None or molar is None:
        raise ValueError("Enter the sample mass in mg and molar mass in g/mol.")
    for name in ("temperature", "fc_temperature"):
        if name in data.waves:
            data.require_unit(name, {"K"}, "K")
            if (data.numeric(name) <= 0).any():
                raise ValueError("Temperature values must be above zero kelvin.")
    notes = [f"Sample mass = {mass:g} mg", f"Molar mass = {molar:g} g/mol"]
    if request.kind == "mpms_zfc_fc":
        t_fc = "fc_temperature" if "fc_temperature" in data.waves else "temperature"
        h_fc = "fc_field" if "fc_field" in data.waves else "field"
        for raw, field in (("zfc", "field"), ("fc", h_fc)):
            derive(data, MolarSusceptibility(op="molar_susceptibility", name=f"chi_{raw}", wave=raw,
                                            field=field, sample_mass_mg=mass, molar_mass_g_mol=molar))
        traces = [Trace(name="ZFC", x="temperature", y="chi_zfc", label="ZFC"),
                  Trace(name="FC", x=t_fc, y="chi_fc", label="FC", dash="dashed")]
        return XYPlot(kind="xy", panels=[Panel(name="susceptibility", x=Axis(label="Temperature (K)"),
                                              y=Axis(label="χₘ (emu/(Oe mol))"),
                                              traces=traces, legend_notes=notes)])
    unit = "mJ/(mol K²)"
    derive(data, Power(op="power", wave="temperature", name="temperature_sq", exponent=2, unit="K²"))
    error = "sigma_display" if "sigma" in data.waves else None
    for raw, name in (("capacity", "cp"), ("sigma", "sigma")):
        if raw in data.waves:
            derive(data, MolarCp(op="molar_cp", name=f"molar_{name}", wave=raw,
                                 sample_mass_mg=mass, molar_mass_g_mol=molar))
            derive(data, Binary(op="divide", name=f"{name}_per_t", wave=f"molar_{name}",
                                other="temperature", unit="J/(mol K²)"))
            derive(data, Scale(op="scale", name=f"{name}_display", wave=f"{name}_per_t",
                               factor=1000, unit=unit))
    traces = [Trace(name="data", x="temperature_sq", y="cp_display", label="Observations",
                    style="points", error_y=error, color="#0072B2")]
    if "model" in data.waves:
        traces.insert(0, Trace(name="model", x="temperature_sq", y="model", label="Supplied model", color="#D55E00"))
    return XYPlot(kind="xy", panels=[Panel(name="heat_capacity", x=Axis(label="T² (K²)"),
                                          y=Axis(label="Cₚ/T (mJ mol⁻¹ K⁻²)"), traces=traces, legend_notes=notes)])


def add_template(
    document: EditableGraphDocument, request: TemplateRequest, cancelled: Event,
) -> tuple[str, GraphState]:
    """Return one validated edit that preserves all existing graphs and waves."""
    projection = document.render_source()
    paths = {item.casefold() for item in (*projection.folders, *(wave.igor_path for wave in projection.waves))}
    i = 1
    while any(path == f"root:templates:figure_{i}" or path.startswith(f"root:templates:figure_{i}:") for path in paths):
        i += 1
    data = Data(folder=f"root:Templates:Figure_{i}")
    peak_phases = tuple(i for i, phase in enumerate(request.phases, 1) if phase.cif is None)
    slots = template_slots(request.kind, len(request.scan_labels), peak_phases)
    for slot in slots:
        binding = request.bindings.get(slot.key)
        if binding is None:
            if slot.required:
                raise ValueError(f"Select a column or wave for {slot.label}.")
            continue
        if not binding.unit.strip() or len(binding.unit) > 80:
            raise ValueError(f"Enter a unit for {slot.label}. Use 1 for dimensionless values.")
        try:
            values, note = binding.read(slot.key, allow_gaps=request.kind == "xy", cancelled=cancelled)
            data.store(slot.key, values, binding.unit, note)
        except ValueError as error:
            raise ValueError(f"{slot.label}: {error}") from error
    workspace, refs = _references(request)
    graph_name, generated = build_document(workspace, data, _plot(request, data, refs))
    if cancelled.is_set():
        raise InterruptedError("Stopped creating the template graph")
    used = {name.casefold() for name in (*projection.tables, *(graph.name for graph in projection.graphs))}
    names = {graph.name: unique_igor_name(graph.name, used, fallback="Graph") for graph in generated.current.graphs}
    graphs = tuple(
        replace(graph, name=names[graph.name], host=names[graph.host] if graph.host else "",
                layout_items=tuple(replace(item, graph=names[item.graph]) for item in graph.layout_items))
        for graph in generated.current.graphs
    )
    after = put_waves(document, list(generated.render_source().waves))
    after.graphs = (*after.graphs, *graphs)
    validate_references(document, after)
    return names[graph_name], after
