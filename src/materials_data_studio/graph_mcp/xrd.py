"""The XRD layouts agreed on in the solid-state Graph Editor baseline."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from warnings import catch_warnings, simplefilter

import numpy as np

from materials_data_studio.graph_mcp.data import Data
from materials_data_studio.graph_mcp.graphs import (
    FONT,
    PALETTE,
    drawing,
    extent,
    geometry,
    layout,
    legend,
    legend_space,
    legend_width,
    limits,
    padded,
    rgb,
)
from materials_data_studio.graph_mcp.inputs import (
    Array,
    PlotError,
    Workspace,
    finite,
    paired,
    unit_key,
)
from materials_data_studio.graph_mcp.schema import (
    XY,
    CifReference,
    Limits,
    MapLongTable,
    MapMatrix,
    MapScans,
    Reference,
    XrdMap,
    XrdRietveld,
    XrdStack,
)
from materials_data_studio.modules.xrd.cif_backend import load_cif
from materials_data_studio.modules.xrd.simulation import simulate_cif
from materials_data_studio.tools.pxp_model import (
    PxpAnnotation,
    PxpAnnotationStyle,
    PxpAxis,
    PxpAxisStyle,
    PxpGraph,
    PxpImage,
    PxpTrace,
)

ANGLE_LABEL = "2θ (degree)"
INTENSITY_LABEL = "Intensity / arb. units"


def _angles(data: Data, name: str) -> Array:
    data.require_unit(name, {"degree", "degrees", "deg", "°"}, "degrees 2θ")
    values = data.numeric(name)
    finite(values, name)
    if (values < 0).any() or (values > 180).any():
        raise PlotError("invalid_angle", name, "2θ must lie between 0 and 180 degrees.")
    return values


def _scan(data: Data, spec: XY) -> tuple[Array, Array]:
    x, y = _angles(data, spec.x), data.numeric(spec.y)
    paired(x, y, spec.y)
    if len(x) < 2 or not (np.all(np.diff(x) > 0) or np.all(np.diff(x) < 0)):
        raise PlotError(
            "invalid_angle_grid",
            spec.x,
            "Each scan needs at least two strictly monotonic 2θ values.",
        )
    finite(y, spec.y)
    return x, y


def _angle_limits(requested: Limits | None, scans: list[Array]) -> Limits:
    bounds = (
        requested
        if requested is not None
        else (min(float(x.min()) for x in scans), max(float(x.max()) for x in scans))
    )
    lo, hi = limits(bounds, "plot.angle_limits_deg")
    if not 0 <= lo < hi <= 180 or any(np.count_nonzero((x >= lo) & (x <= hi)) < 2 for x in scans):
        raise PlotError(
            "invalid_angle_limits",
            "plot.angle_limits_deg",
            "Limits must be within 0–180° and include at least two measured points of every displayed scan.",
        )
    return lo, hi


def _axes(
    x_limits: Limits,
    y_limits: Limits,
    *,
    x_label: bool = True,
    y_label: str = INTENSITY_LABEL,
    strip: bool = False,
    y_ticks: bool = False,
) -> tuple[PxpAxis, PxpAxis]:
    return (
        PxpAxis(
            "bottom",
            ANGLE_LABEL if x_label else "",
            x_limits,
            style=PxpAxisStyle(
                manual_ticks=(0, 10, 0, 0),
                manual_minor=(4, 0),
                minor_enabled=True,
                no_label=None if x_label else 2,
                thickness=0 if strip and not x_label else None,
                tick=3 if strip and not x_label else None,
                mirror=0 if strip else None,
            ),
        ),
        PxpAxis(
            "left",
            y_label,
            y_limits,
            style=PxpAxisStyle(
                tick_count=None if y_ticks else 0,
                minor_enabled=y_ticks,
                tick=3 if strip else None,
                thickness=0 if strip else None,
                mirror=0 if strip else None,
            ),
        ),
    )


def _trace(
    name: str, x: str, y: str, color: str, *, mode: int = 0, offset: float = 0, width: float = 1.2
) -> PxpTrace:
    return PxpTrace(
        name,
        y,
        x,
        mode=mode,
        offset=(0, offset),
        color_igor=rgb(color),
        marker=8,
        marker_size=1.7,
        line_width=width,
    )


def _unique_labels(labels: list[str], field: str) -> None:
    if len(set(labels)) != len(labels):
        raise PlotError("duplicate_label", field, "Give each condition or phase a distinct label.")


def _reference_graphs(
    workspace: Workspace,
    data: Data,
    references: list[Reference],
    bounds: Limits,
    *,
    width: float,
    left: float,
    relative_heights: bool,
) -> list[PxpGraph]:
    _unique_labels([ref.label for ref in references], "plot.references")
    if len({ref.wavelength_angstrom for ref in references if isinstance(ref, CifReference)}) > 1:
        raise PlotError(
            "wavelength_mismatch",
            "plot.references",
            "Reference CIFs compared with the same scan require one common wavelength.",
        )
    graphs = []
    for i, ref in enumerate(references, 1):
        field = f"reference_{i}"
        note = ref.model_dump(mode="json")
        if isinstance(ref, CifReference):
            path = workspace.path(ref.path)
            if path.suffix.casefold() != ".cif":
                raise PlotError(
                    "invalid_cif", ref.path, "Provide a CIF file with the .cif extension."
                )
            with catch_warnings(record=True) as warnings:
                simplefilter("always", UserWarning)
                simulated = simulate_cif(
                    load_cif(path),
                    wavelength_a=ref.wavelength_angstrom,
                    two_theta_range=bounds,
                    occupancy_preview=False,
                )
            note["simulation_warnings"] = [
                str(warning.message)
                for warning in warnings
                if issubclass(warning.category, UserWarning)
            ]
            x, y = simulated.two_theta_deg, simulated.intensity
        else:
            x = _angles(data, ref.angles)
            if relative_heights and ref.intensity is None:
                raise PlotError(
                    "missing_peak_intensity",
                    field,
                    "For parent-structure comparison, supply calculated relative intensities or a reference CIF with wavelength.",
                )
            y = (
                data.numeric(ref.intensity)
                if ref.intensity and relative_heights
                else np.ones_like(x)
            )
        paired(x, y, field)
        inside = (x >= bounds[0]) & (x <= bounds[1])
        if not inside.any():
            raise PlotError(
                "no_reference_peaks",
                field,
                f"{ref.label} has no Bragg positions inside the requested 2θ range.",
            )
        x, y = x[inside], y[inside] if relative_heights else np.ones(np.count_nonzero(inside))
        finite(y, field)
        if (y < 0).any() or y.max() <= 0:
            raise PlotError(
                "invalid_peak_intensity",
                field,
                "Reference peak intensities must be nonnegative with a positive maximum.",
            )
        order = np.argsort(x, kind="stable")
        px = data.store(f"root:MCP:{field}_2theta", x[order], "degree", note)
        py = data.store(
            f"root:MCP:{field}_height",
            y[order] / y.max(),
            "relative" if relative_heights else "1",
            note,
        )
        last = relative_heights and i == len(references)
        color = ("#46546A", "#9E4B80", "#0072B2", "#009E73", "#B88500", "#D55E00")[i - 1]
        label = f"{ref.label} · sim." if relative_heights else ref.label
        graphs.append(
            PxpGraph(
                field,
                (_trace(field, px, py, color, mode=1, width=1),),
                _axes(bounds, (0, 1.12), x_label=last, y_label="", strip=True),
                style=geometry(
                    width,
                    28 if relative_heights else 18,
                    left=left,
                    bottom=52 if last else 3,
                    top=3,
                ),
                annotations=(
                    PxpAnnotation(
                        "phase_label",
                        label,
                        PxpAnnotationStyle(
                            anchor="RC",
                            x_percent=-101.7,
                            frame=0,
                            transparent=True,
                            font_size=9,
                            color=rgb(color),
                        ),
                    ),
                ),
            )
        )
    return graphs


def _phase_margin(refs: list[Reference], *, simulation: bool = False) -> float:
    return max(
        76, max((7.5 * (len(ref.label) + (7 if simulation else 0)) + 16 for ref in refs), default=0)
    )


def stack_graphs(workspace: Workspace, data: Data, plot: XrdStack) -> tuple[str, list[PxpGraph]]:
    labels = [spec.label for spec in plot.scans]
    _unique_labels(labels, "plot.scans")
    scans = [_scan(data, spec) for spec in plot.scans]
    bounds = _angle_limits(plot.angle_limits_deg, [x for x, _ in scans])
    if plot.offsets is not None and len(plot.offsets) != len(scans):
        raise PlotError(
            "length_mismatch",
            "plot.offsets",
            "Provide one offset in display intensity units per scan.",
        )
    if plot.normalization == "none":
        for spec in plot.scans[1:]:
            data.same_units(plot.scans[0].y, spec.y, "plot.scans")
    traces, display_ranges = [], []
    for i, (spec, (x, y)) in enumerate(zip(plot.scans, scans, strict=True)):
        y_path = data.wave(spec.y).igor_path
        if plot.normalization == "peak100":
            maximum = float(y.max())
            if maximum <= 0:
                raise PlotError(
                    "invalid_normalization",
                    spec.y,
                    "Peak normalization needs a positive scan maximum.",
                )
            y = (y / maximum) * 100
            finite(y, spec.y)
            y_path = data.store(
                f"root:MCP:scan_{i + 1}_peak100",
                y,
                "arb. units",
                {"source_wave": spec.y, "operation": "peak100", "maximum": maximum},
            )
        visible = y[(x >= bounds[0]) & (x <= bounds[1])]
        display_ranges.append(extent(visible, spec.y))
        traces.append(_trace(f"scan_{i + 1}", data.wave(spec.x).igor_path, y_path, PALETTE[i]))
    gap = max(hi - lo for lo, hi in display_ranges) * 0.15
    if gap == 0:
        gap = max(0.1, max(abs(hi) for _, hi in display_ranges) * 0.15)
    offsets = [0.0]
    for (_, prev_hi), (lo, _) in pairwise(display_ranges):
        offsets.append(offsets[-1] + prev_hi + gap - lo)
    if plot.offsets is not None:
        offsets = plot.offsets
    traces = [
        replace(trace, offset=(0, offset)) for trace, offset in zip(traces, offsets, strict=True)
    ]
    height = max(315, 75 + len(labels) * 45)
    width = max(420, legend_width(labels))
    left = _phase_margin(plot.references, simulation=True)
    displayed = [
        (lo + off, hi + off) for (lo, hi), off in zip(display_ranges, offsets, strict=True)
    ]
    y_limits = padded(
        (min(lo for lo, _ in displayed), max(hi for _, hi in displayed)),
        top_fraction=legend_space(len(labels), height),
    )
    main = PxpGraph(
        "observed",
        tuple(traces),
        _axes(bounds, y_limits, x_label=not plot.references),
        style=geometry(width, height, left=left, bottom=7 if plot.references else 52),
        annotations=legend(list(reversed(list(zip(traces, labels, strict=True))))),
    )
    if not plot.references:
        return main.name, [main]
    graphs = [
        main,
        *_reference_graphs(
            workspace, data, plot.references, bounds, width=width, left=left, relative_heights=True
        ),
    ]
    return "figure", [*graphs, layout("figure", graphs)]


def _same_grid(x: Array, other: Array, tolerance: float, field: str) -> None:
    if x.shape != other.shape or not np.allclose(x, other, atol=tolerance, rtol=0):
        raise PlotError(
            "angle_grid_mismatch",
            field,
            "Supply the same measured 2θ grid in the same order, or explicitly prepare a common grid before plotting.",
        )


def rietveld_graphs(
    workspace: Workspace, data: Data, plot: XrdRietveld
) -> tuple[str, list[PxpGraph]]:
    x, observed = _scan(data, plot.observed)
    xc, calculated = _scan(data, plot.calculated)
    _same_grid(x, xc, plot.angle_tolerance_deg, "plot.calculated.x")
    data.same_units(plot.observed.y, plot.calculated.y, "plot.calculated.y")
    bounds = _angle_limits(plot.angle_limits_deg, [x, xc])
    residual = observed - calculated
    finite(residual, "residual")
    residual_path = data.store(
        "root:MCP:observed_minus_calculated",
        residual,
        data.unit(plot.observed.y),
        {
            "observed": plot.observed.model_dump(),
            "calculated": plot.calculated.model_dump(),
            "operation": "subtract",
        },
    )
    left = _phase_margin(plot.phases)
    width, height, residual_height = 420, 310, 84
    lo, hi = bounds
    observed_range = extent(observed[(lo <= x) & (x <= hi)], plot.observed.y)
    calculated_range = extent(calculated[(lo <= xc) & (xc <= hi)], plot.calculated.y)
    profile_bounds = padded(
        (min(observed_range[0], calculated_range[0]), max(observed_range[1], calculated_range[1])),
        top_fraction=legend_space(2, height),
    )
    maximum = float(np.max(np.abs(residual[(lo <= x) & (x <= hi)])))
    span = max(profile_bounds[1] - profile_bounds[0], 2.25 * maximum * height / residual_height)
    profile_bounds = limits((profile_bounds[0], profile_bounds[0] + span), "plot.observed.y")
    half_range = span * residual_height / height / 2
    xr, xc_path = data.wave(plot.observed.x).igor_path, data.wave(plot.calculated.x).igor_path
    calc = _trace("calculated", xc_path, data.wave(plot.calculated.y).igor_path, PALETTE[1])
    obs = replace(
        _trace("observed", xr, data.wave(plot.observed.y).igor_path, PALETTE[5], mode=3),
        marker_size=1.05,
        marker_thickness=0.45,
    )
    main = PxpGraph(
        "profile",
        (calc, obs),
        _axes(bounds, profile_bounds, x_label=False),
        style=geometry(width, height, left=left, bottom=7),
        annotations=legend([(obs, "Observed"), (calc, "Supplied calculation")]),
    )
    bottom = PxpGraph(
        "residual",
        (_trace("difference", xr, residual_path, PALETTE[0], width=0.85),),
        _axes(bounds, (-half_range, half_range), y_label="Obs. − calc."),
        style=geometry(width, residual_height, left=left, top=8),
        drawings=(drawing("y", 0),),
    )
    graphs = [
        main,
        *_reference_graphs(
            workspace, data, plot.phases, bounds, width=width, left=left, relative_heights=False
        ),
        bottom,
    ]
    return "figure", [*graphs, layout("figure", graphs)]


def _map_arrays(data: Data, plot: XrdMap) -> tuple[Array, Array, Array, str]:
    source = plot.data
    if isinstance(source, MapScans):
        ordered = sorted(source.scans, key=lambda scan: scan.condition)
        x, *others = [_scan(data, scan) for scan in ordered]
        angles, first = x
        waves = [first]
        unit = data.unit(ordered[0].y)
        for scan, (grid, intensity) in zip(ordered[1:], others, strict=True):
            _same_grid(angles, grid, plot.angle_tolerance_deg, scan.x)
            data.same_units(ordered[0].y, scan.y, "plot.data")
            waves.append(intensity)
        return angles, np.asarray([row.condition for row in ordered]), np.column_stack(waves), unit

    angles, conditions, values = (
        _angles(data, source.x),
        data.numeric(source.condition),
        data.numeric(source.intensity),
    )
    if unit_key(data.unit(source.condition)) != unit_key(plot.condition_unit):
        raise PlotError(
            "units_mismatch",
            source.condition,
            "The condition wave and the plotted condition axis require the same units.",
        )
    finite(conditions, source.condition)
    finite(values, source.intensity)
    if isinstance(source, MapLongTable):
        paired(angles, conditions, source.condition)
        paired(angles, values, source.intensity)
        ordering = np.lexsort((angles, conditions))
        conditions, counts = np.unique(conditions[ordering], return_counts=True)
        if not len(conditions) or np.any(counts != counts[0]):
            raise PlotError(
                "angle_grid_mismatch",
                "plot.data",
                "Each condition in a long table must have the same number of angle points.",
            )
        grids = angles[ordering].reshape(len(conditions), -1)
        angles = grids[0]
        for grid in grids[1:]:
            _same_grid(angles, grid, plot.angle_tolerance_deg, source.x)
        values = values[ordering].reshape(len(conditions), -1).T
    else:
        assert isinstance(source, MapMatrix)
        if len(angles) * len(conditions) != len(values):
            raise PlotError(
                "length_mismatch",
                source.intensity,
                "Flat intensity length must equal #angles × #conditions.",
            )
        values = values.reshape(
            (len(angles), len(conditions)), order="F" if source.order == "scan_major" else "C"
        )
    return angles, conditions, values, data.unit(source.intensity)


def _edges(centers: Array) -> Array:
    steps = np.diff(centers) / 2
    return np.r_[centers[0] - steps[0], centers[:-1] + steps, centers[-1] + steps[-1]]


def map_graphs(data: Data, plot: XrdMap) -> tuple[str, list[PxpGraph]]:
    angles, conditions, matrix, unit = _map_arrays(data, plot)
    # Descending scan coordinates are valid. Image coordinates must be increasing.
    if len(angles) > 1 and np.all(np.diff(angles) < 0):
        angles, matrix = angles[::-1], matrix[::-1, :]
    if len(conditions) > 1 and np.all(np.diff(conditions) < 0):
        conditions, matrix = conditions[::-1], matrix[:, ::-1]
    for coordinates, name in ((angles, "2theta"), (conditions, "condition")):
        if len(coordinates) < 2 or not np.all(np.diff(coordinates) > 0):
            raise PlotError(
                "invalid_map_axis",
                name,
                "Map axes require at least two distinct, monotonic coordinates.",
            )
    bounds = _angle_limits(plot.angle_limits_deg, [angles])
    if plot.normalization == "global_max":
        maximum = float(matrix.max())
        if maximum <= 0:
            raise PlotError(
                "invalid_normalization",
                "plot.normalization",
                "Global normalization needs a positive maximum.",
            )
        matrix, unit = matrix / maximum, "arb. units"
    finite(matrix, "intensity_map")
    note = {
        "dimensions": ["2theta", "condition"],
        "input": plot.data.model_dump(mode="json"),
        "normalization": plot.normalization,
    }
    xy_paths = [
        data.store(f"root:MCP:{name}_edges", _edges(coords), axis_unit)
        for name, coords, axis_unit in (
            ("angle", angles, "degree"),
            ("condition", conditions, plot.condition_unit),
        )
    ]
    pixels = data.store("root:MCP:intensity_map", matrix, unit, note)
    color_bounds = (
        limits(plot.color_limits, "plot.color_limits")
        if plot.color_limits
        else extent(matrix, "intensity_map")
    )
    if color_bounds[0] == color_bounds[1]:
        color_bounds = padded(color_bounds)
    axis_bounds = float(conditions[0]), float(conditions[-1])
    return "condition_map", [
        PxpGraph(
            "condition_map",
            axes=_axes(bounds, axis_bounds, y_label=plot.condition_label, y_ticks=True),
            style=geometry(420, 340, right=125),
            images=(
                PxpImage(
                    pixels,
                    color_table="ColdWarm",
                    color_range=color_bounds,
                    colorbar_visible=True,
                    colorbar_label_raw=INTENSITY_LABEL,
                    x_wave=xy_paths[0],
                    y_wave=xy_paths[1],
                    colorbar_style=PxpAnnotationStyle(
                        anchor="LC",
                        x_percent=105,
                        frame=1,
                        width=13,
                        height_percent=83,
                        font_size=10,
                    ),
                    colorbar_axis=PxpAxisStyle(font_family=FONT, tick_count=5, minor_enabled=False),
                ),
            ),
        )
    ]
