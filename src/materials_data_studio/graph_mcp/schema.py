"""The public, declarative MCP input contract. Fields carry their physical units."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

Id = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,47}$")]
Text = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[^\\\x00-\x1f\x7f]+$")]
Unit = Annotated[str, Field(min_length=1, max_length=80)]
Positive = Annotated[FiniteFloat, Field(gt=0)]
Limits = tuple[FiniteFloat, FiniteFloat]
Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
FilePath = Annotated[str, Field(min_length=1, max_length=4096)]
ColumnIndex = Annotated[int, Field(ge=0, le=4095, strict=True)]
ImageFormat = Literal["png", "svg", "pdf"]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Source(Request):
    path: FilePath
    kind: Literal["table", "quantum_design", "rasx"] = "table"
    delimiter: Literal["Auto", "Comma", "Tab", "Semicolon", "Whitespace"] = "Auto"
    header: bool = Field(
        default=True, description="For table inputs. Use false for headerless XY data."
    )
    first_record: int = Field(
        default=1, ge=1, description="One-based CSV record at which to start a table."
    )


class Column(Request):
    source: Id
    column: Annotated[str, Field(min_length=1, max_length=256)] | ColumnIndex
    unit: Unit = Field(
        description="Confirmed units for the selected values. Use '1' for dimensionless."
    )
    missing: Literal["error", "gap"] = "error"
    rows: tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(gt=0)]] | None = Field(
        default=None,
        description="Half-open [start, stop) slice of zero-based data rows, excluding empty records.",
    )


class Derived(Request):
    name: Id
    wave: Id


class Scale(Derived):
    op: Literal["scale"]
    factor: FiniteFloat
    offset: FiniteFloat = 0
    unit: Unit


class Power(Derived):
    op: Literal["power"]
    exponent: FiniteFloat
    unit: Unit


class Log(Derived):
    op: Literal["ln"]
    reference: Positive = Field(
        description="Positive reference in the same unit as the input wave."
    )


class Binary(Derived):
    op: Literal["add", "subtract", "multiply", "divide"]
    other: Id
    unit: Unit


class Resistivity(Derived):
    op: Literal["resistivity"]
    width_cm: Positive
    thickness_cm: Positive
    voltage_spacing_cm: Positive


class MolarCp(Derived):
    op: Literal["molar_cp"]
    sample_mass_mg: Positive
    molar_mass_g_mol: Positive


class MolarSusceptibility(Derived):
    op: Literal["molar_susceptibility"]
    field: Id
    sample_mass_mg: Positive
    molar_mass_g_mol: Positive


class Magnetoresistance(Derived):
    op: Literal["magnetoresistance"]
    field: Id
    zero_tolerance: float = Field(
        default=0, ge=0, description="Zero-field tolerance in the field wave's units."
    )


class Antisymmetrize(Derived):
    op: Literal["hall_antisymmetrize"]
    field: Id
    other: Id
    opposite_field: Id
    tolerance: float = Field(ge=0, description="Agreement tolerance in the field waves' units.")


Transform = Annotated[
    Scale
    | Power
    | Log
    | Binary
    | Resistivity
    | MolarCp
    | MolarSusceptibility
    | Magnetoresistance
    | Antisymmetrize,
    Field(discriminator="op"),
]


class XY(Request):
    x: Id
    y: Id


class Trace(XY):
    name: Id
    label: Text | None = None
    color: Color | None = None
    style: Literal["line", "points", "line_points", "sticks"] = "line"
    dash: Literal["solid", "dashed", "dotted"] = "solid"
    offset_y: FiniteFloat = 0
    error_y: Id | None = Field(
        default=None, description="Nonnegative symmetric uncertainties in the Y wave's unit."
    )


class Tick(Request):
    value: FiniteFloat
    label: Text


class Axis(Request):
    label: Text
    limits: Limits | None = None
    scale: Literal["linear", "log"] = "linear"
    reverse: bool = False
    ticks: list[Tick] = Field(default_factory=list, max_length=32)


class Guide(Request):
    axis: Literal["x", "y"]
    value: FiniteFloat


class Panel(Request):
    name: Id
    x: Axis
    y: Axis
    traces: list[Trace] = Field(min_length=1, max_length=32)
    legend_notes: list[Text] = Field(
        default_factory=list,
        max_length=4,
        description="Measurement conditions shown below the series labels.",
    )
    guides: list[Guide] = Field(default_factory=list, max_length=32)
    plot_width_pt: Annotated[FiniteFloat, Field(ge=100, le=960)] | None = None
    plot_height_pt: Annotated[FiniteFloat, Field(ge=68, le=1000)] | None = None
    equal_units: bool = Field(
        default=False, description="Draw one X and one Y unit at the same physical scale."
    )


class Inset(Request):
    host: Id
    rect: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat] = Field(
        description="Left, bottom, right, top fractions of the host plot area."
    )
    panel: Panel


class XYPlot(Request):
    kind: Literal["xy"]
    panels: list[Panel] = Field(min_length=1, max_length=6)
    layout: Literal["vertical", "horizontal"] = "vertical"
    share_axis: Literal["x", "y"] | None = None
    insets: list[Inset] = Field(default_factory=list, max_length=6)


class Scan(XY):
    label: Text


class PeakTable(Request):
    kind: Literal["peaks"]
    label: Text
    angles: Id
    intensity: Id | None = None


class CifReference(Request):
    kind: Literal["cif"]
    label: Text
    path: FilePath
    wavelength_angstrom: Positive = Field(
        description="Confirmed experimental X-ray wavelength in Å."
    )


Reference = Annotated[PeakTable | CifReference, Field(discriminator="kind")]


class XrdStack(Request):
    kind: Literal["xrd_stack"]
    scans: list[Scan] = Field(
        min_length=1, max_length=8, description="Conditions in order from bottom to top."
    )
    angle_limits_deg: Limits | None = None
    normalization: Literal["none", "peak100"] = "none"
    offsets: list[FiniteFloat] | None = None
    references: list[Reference] = Field(default_factory=list, max_length=5)


class XrdRietveld(Request):
    kind: Literal["xrd_rietveld"]
    observed: XY
    calculated: XY
    phases: list[Reference] = Field(min_length=1, max_length=6)
    angle_limits_deg: Limits | None = None
    angle_tolerance_deg: float = Field(default=1e-8, ge=0, le=0.1)


class ConditionScan(XY):
    condition: FiniteFloat


class MapScans(Request):
    kind: Literal["scans"]
    scans: list[ConditionScan] = Field(min_length=2, max_length=256)


class MapLongTable(Request):
    kind: Literal["long_table"]
    x: Id
    condition: Id
    intensity: Id


class MapMatrix(Request):
    kind: Literal["flat_matrix"]
    x: Id
    condition: Id
    intensity: Id
    order: Literal["scan_major", "angle_major"]


MapData = Annotated[MapScans | MapLongTable | MapMatrix, Field(discriminator="kind")]


class XrdMap(Request):
    kind: Literal["xrd_map"]
    data: MapData
    condition_label: Text = Field(
        description="Label including explicit units, e.g. Temperature / K."
    )
    condition_unit: Unit
    angle_limits_deg: Limits | None = None
    angle_tolerance_deg: float = Field(default=1e-8, ge=0, le=0.1)
    normalization: Literal["none", "global_max"] = "none"
    color_limits: Limits | None = None


FigurePlot = Annotated[XYPlot | XrdStack | XrdRietveld | XrdMap, Field(discriminator="kind")]


class FigureRecipe(Request):
    sources: dict[Id, Source] = Field(min_length=1, max_length=256)
    columns: dict[Id, Column] = Field(min_length=1, max_length=512)
    transforms: list[Transform] = Field(default_factory=list, max_length=128)
    plot: FigurePlot
    provenance: dict[Id, Text | FiniteFloat] = Field(
        default_factory=dict,
        max_length=32,
        description="Confirmed measurement conditions or supplied model assumptions.",
    )


class ReviewPage(Request):
    pdf: FilePath
    title: Text
