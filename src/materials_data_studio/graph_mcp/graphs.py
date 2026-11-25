"""Compose the same native waves, axes, and layouts that Graph Editor edits."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from materials_data_studio.graph_mcp.data import Data
from materials_data_studio.graph_mcp.inputs import Array, PlotError, paired
from materials_data_studio.graph_mcp.schema import Axis, Limits, Panel, XYPlot
from materials_data_studio.tools.pxp_model import (
    PxpAnnotation,
    PxpAnnotationStyle,
    PxpAxis,
    PxpAxisStyle,
    PxpDrawing,
    PxpGraph,
    PxpGraphStyle,
    PxpLayoutItem,
    PxpTrace,
)

PALETTE = ("#0072B2", "#D55E00", "#009E73", "#9E4B80", "#B88500", "#46546A", "#00878F", "#774C29")
FONT = "DejaVu Sans"
MODES = {"line": 0, "points": 3, "line_points": 4, "sticks": 1}
DASHES = {"solid": 0, "dashed": 3, "dotted": 2}


def rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16) * 257, int(color[3:5], 16) * 257, int(color[5:7], 16) * 257


def extent(values: Array, field: str) -> Limits:
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise PlotError("empty_data", field, "No finite data to display.")
    return float(finite.min()), float(finite.max())


def limits(values: Limits, field: str, *, logarithmic: bool = False) -> Limits:
    lo, hi = values
    if lo >= hi or not np.isfinite(hi - lo) or (logarithmic and lo <= 0):
        raise PlotError(
            "invalid_limits",
            field,
            "Provide increasing finite limits, both positive for a log axis.",
        )
    return lo, hi


def padded(values: Limits, *, top_fraction: float = 0.06, logarithmic: bool = False) -> Limits:
    lo, hi = values
    if logarithmic:
        if lo <= 0:
            raise PlotError(
                "nonpositive_log_axis", "plot", "All plotted values must be positive on log axes."
            )
        lo, hi = float(np.log10(lo)), float(np.log10(hi))
    span = hi - lo or 0.1 * max(abs(lo), 1)
    lo, hi = lo - 0.045 * span, hi + top_fraction / (1 - top_fraction) * span
    if logarithmic:
        lo, hi = float(np.power(10.0, lo)), float(np.power(10.0, hi))
    return limits((lo, hi), "plot", logarithmic=logarithmic)


def geometry(
    width: float = 420,
    height: float = 280,
    *,
    left: float = 74,
    bottom: float = 52,
    top: float = 16,
    right: float = 20,
    font_size: float = 11,
    tick_count: int = 5,
) -> PxpGraphStyle:
    return PxpGraphStyle(
        width_points=width,
        height_points=height,
        window_size=(width + left + right, height + bottom + top),
        margins=(("left", left), ("bottom", bottom), ("top", top), ("right", right)),
        font_family=FONT,
        font_size=font_size,
        axis_defaults=PxpAxisStyle(
            font_family=FONT,
            font_size=font_size,
            tick=2,
            mirror=1,
            thickness=0.8,
            major_length=4.5,
            minor_length=2.5,
            minor_enabled=True,
            tick_count=tick_count,
        ),
    )


def legend(
    entries: list[tuple[PxpTrace, str]], *, notes: list[str] | None = None
) -> tuple[PxpAnnotation, ...]:
    if not entries and not notes:
        return ()
    raw = "\n".join([*(f"\\s({trace.name}) {label}" for trace, label in entries), *(notes or [])])
    return (
        PxpAnnotation(
            "legend",
            raw,
            PxpAnnotationStyle(
                anchor="RT",
                x_percent=-3,
                y_percent=-4,
                frame=0,
                transparent=True,
                font_size=10,
            ),
        ),
    )


def legend_width(labels: list[str]) -> float:
    return max((40 + 10 * len(label) for label in labels), default=0)


def legend_space(count: int, height: float) -> float:
    return 0.06 + count * 13 / height if count else 0.06


def drawing(axis: str, value: float) -> PxpDrawing:
    return PxpDrawing(
        "line",
        (value, 0, value, 1) if axis == "x" else (0, value, 1, value),
        xcoord="bottom" if axis == "x" else "prel",
        ycoord="left" if axis == "y" else "prel",
        layer="UserBack",
        color=rgb("#B4BDC7"),
        line_width=0.75,
        line_style=1,
    )


def layout(
    name: str,
    graphs: list[PxpGraph],
    *,
    direction: str = "vertical",
    gap: float = 0,
    padding: float = 5,
) -> PxpGraph:
    items = []
    x, y = padding, padding
    for graph in graphs:
        assert graph.style.window_size is not None
        width, height = graph.style.window_size
        items.append(PxpLayoutItem(graph.name, (x, y, x + width, y + height)))
        if direction == "vertical":
            y += height + gap
        else:
            x += width + gap
    width = max(item.rect[2] for item in items) + padding
    height = max(item.rect[3] for item in items) + padding
    return PxpGraph(
        name,
        window_kind="Layout",
        layout_items=tuple(items),
        style=PxpGraphStyle(
            width_points=width,
            height_points=height,
            window_size=(width, height),
            margins=(("all", -1),),
        ),
    )


def _axis(data: Data, name: str, axis: Axis, side: str, bounds: Limits) -> PxpAxis:
    ticks = None
    if axis.ticks:
        tick_values = np.array([tick.value for tick in axis.ticks])
        if not np.all(np.diff(tick_values) > 0):
            raise PlotError("invalid_ticks", name, "Tick positions must be strictly increasing.")
        ticks = (
            data.store(f"root:MCP:{name}_{side}_tick_values", tick_values, ""),
            data.store(
                f"root:MCP:{name}_{side}_tick_labels",
                np.array([tick.label for tick in axis.ticks]),
                "",
            ),
        )
    return PxpAxis(
        side,
        axis.label,
        bounds,
        style=PxpAxisStyle(log=int(axis.scale == "log"), reverse=axis.reverse, user_ticks=ticks),
    )


def _panel(
    data: Data,
    panel: Panel,
    *,
    width: float,
    height: float,
    inset: bool = False,
    show_x: bool = True,
) -> PxpGraph:
    if inset and (panel.legend_notes or any(trace.label for trace in panel.traces)):
        raise PlotError(
            "inset_legend",
            panel.name,
            "Keep series labels in the host legend; omit trace labels in its inset.",
        )
    if len({trace.name for trace in panel.traces}) != len(panel.traces):
        raise PlotError(
            "duplicate_trace", panel.name, "Use unique trace identifiers within a panel."
        )
    traces, entries = [], []
    x_spans, y_spans = [], []
    for i, spec in enumerate(panel.traces):
        data.same_units(panel.traces[0].x, spec.x, panel.name)
        data.same_units(panel.traces[0].y, spec.y, panel.name)
        if panel.equal_units:
            data.same_units(spec.x, spec.y, panel.name)
        x, y = data.numeric(spec.x), data.numeric(spec.y)
        paired(x, y, spec.name)
        valid = np.isfinite(x) & np.isfinite(y)
        errors = None
        if spec.error_y is not None:
            data.same_units(spec.y, spec.error_y, spec.name)
            errors = data.numeric(spec.error_y)
            paired(y, errors, spec.name)
            if not np.isfinite(errors[valid]).all() or np.any(errors[np.isfinite(errors)] < 0):
                raise PlotError(
                    "invalid_uncertainty",
                    spec.name,
                    "Each plotted point needs a nonnegative Y uncertainty in the Y wave's units.",
                )
        xmin, xmax = extent(x[valid], spec.name)
        error = errors[valid] if errors is not None else 0
        low = y[valid] + spec.offset_y - error
        high = y[valid] + spec.offset_y + error
        ymin, ymax = float(low.min()), float(high.max())
        if spec.style == "sticks":
            ymin, ymax = min(0.0, ymin), max(0.0, ymax)
        if (panel.x.scale == "log" and xmin <= 0) or (panel.y.scale == "log" and ymin <= 0):
            raise PlotError(
                "nonpositive_log_axis",
                spec.name,
                "A log axis requires positive coordinates, including error-bar ends.",
            )
        x_spans.append((xmin, xmax))
        y_spans.append((ymin, ymax))
        error_path = data.wave(spec.error_y).igor_path if spec.error_y else None
        trace = PxpTrace(
            spec.name,
            data.wave(spec.y).igor_path,
            data.wave(spec.x).igor_path,
            mode=MODES[spec.style],
            marker=8,
            marker_size=2.3,
            line_width=1.45,
            color_igor=rgb(spec.color or PALETTE[i % len(PALETTE)]),
            line_style=DASHES[spec.dash],
            offset=(0, spec.offset_y),
            error_low=error_path,
            error_high=error_path,
        )
        traces.append(trace)
        if spec.label is not None:
            entries.append((trace, spec.label))

    count = len(entries) + len(panel.legend_notes)
    if count > 12:
        raise PlotError(
            "legend_too_long",
            panel.name,
            "Use up to 12 legend lines per panel or split the figure into panels.",
        )
    height = max(height, count * 27)
    x_bounds = (
        limits(panel.x.limits, panel.name, logarithmic=panel.x.scale == "log")
        if panel.x.limits
        else padded(
            (min(lo for lo, _ in x_spans), max(hi for _, hi in x_spans)),
            logarithmic=panel.x.scale == "log",
        )
    )
    y_data = (min(lo for lo, _ in y_spans), max(hi for _, hi in y_spans))
    log_y = panel.y.scale == "log"
    if panel.y.limits:
        y_bounds = limits(panel.y.limits, panel.name, logarithmic=log_y)
    else:
        if panel.y.reverse and not log_y:
            upper, lower = padded(
                (-y_data[1], -y_data[0]), top_fraction=legend_space(count, height)
            )
            y_bounds = -lower, -upper
        elif panel.y.reverse:
            lower, upper = padded(
                (1 / y_data[1], 1 / y_data[0]),
                logarithmic=True,
                top_fraction=legend_space(count, height),
            )
            y_bounds = 1 / upper, 1 / lower
        else:
            y_bounds = padded(y_data, top_fraction=legend_space(count, height), logarithmic=log_y)
    if panel.equal_units:
        if panel.x.scale != "linear" or panel.y.scale != "linear" or inset:
            raise PlotError(
                "invalid_aspect",
                panel.name,
                "Equal-unit scale requires two linear axes on a main panel.",
            )
        height = width * (y_bounds[1] - y_bounds[0]) / (x_bounds[1] - x_bounds[0])
        if not 65 <= height <= 1200:
            raise PlotError(
                "invalid_aspect",
                panel.name,
                "The limits yield an impractical plot height at equal-unit scale. Adjust the axis limits.",
            )
    style = (
        geometry(width, height, bottom=52 if show_x else 8)
        if not inset
        else geometry(width, height, left=35, bottom=31, top=7, right=9, font_size=8, tick_count=3)
    )
    x_axis = _axis(data, panel.name, panel.x, "bottom", x_bounds)
    if not show_x:
        x_axis = replace(x_axis, label_raw="", style=replace(x_axis.style, no_label=2))
    return PxpGraph(
        panel.name,
        tuple(traces),
        (
            x_axis,
            _axis(data, panel.name, panel.y, "left", y_bounds),
        ),
        style=style,
        annotations=legend(entries, notes=panel.legend_notes),
        drawings=tuple(drawing(g.axis, g.value) for g in panel.guides),
    )


def xy_graphs(data: Data, plot: XYPlot) -> tuple[str, list[PxpGraph]]:
    names = [panel.name for panel in plot.panels] + [inset.panel.name for inset in plot.insets]
    if len(set(names)) != len(names) or (len(plot.panels) > 1 and "figure" in names):
        raise PlotError(
            "duplicate_graph",
            "plot",
            "Use distinct panel and inset identifiers, reserving 'figure' for multi-panel layouts.",
        )
    if len(plot.panels) > 1 and any(panel.equal_units for panel in plot.panels):
        raise PlotError(
            "invalid_aspect", "plot", "Equal-unit scale is available for single-panel graphs."
        )
    widths = [
        max(
            panel.plot_width_pt
            or (250 if plot.layout == "horizontal" and len(plot.panels) > 1 else 420),
            legend_width(
                [*(trace.label for trace in panel.traces if trace.label), *panel.legend_notes]
            ),
        )
        for panel in plot.panels
    ]
    shared = plot.share_axis
    if shared:
        first = getattr(plot.panels[0].traces[0], shared)
        for panel in plot.panels[1:]:
            data.same_units(first, getattr(panel.traces[0], shared), "plot.share_axis")
        axes = [getattr(panel, shared) for panel in plot.panels]
        if any(
            axis.limits is None
            or axis.limits != axes[0].limits
            or axis.reverse != axes[0].reverse
            or axis.scale != axes[0].scale
            for axis in axes
        ):
            raise PlotError(
                "shared_axis_limits",
                "plot.share_axis",
                "Supply matching limits, scale, and direction on all shared axes.",
            )
        if (shared, plot.layout) not in {("x", "vertical"), ("y", "horizontal")}:
            raise PlotError(
                "shared_axis_layout",
                "plot.share_axis",
                "Use a shared X axis with vertical panels or a shared Y axis with horizontal panels.",
            )
    heights = [
        max(
            panel.plot_height_pt or 280,
            27 * (len(panel.legend_notes) + sum(t.label is not None for t in panel.traces)),
        )
        for panel in plot.panels
    ]
    if plot.layout == "vertical":
        widths = [max(widths)] * len(widths)
    else:
        heights = [max(heights)] * len(heights)
    panels = [
        _panel(
            data,
            panel,
            width=width,
            height=height,
            show_x=shared != "x" or index == len(plot.panels) - 1,
        )
        for index, (panel, width, height) in enumerate(
            zip(plot.panels, widths, heights, strict=True)
        )
    ]
    children = []
    for inset in plot.insets:
        if inset.panel.plot_width_pt is not None or inset.panel.plot_height_pt is not None:
            raise PlotError(
                "invalid_inset",
                inset.panel.name,
                "Inset dimensions come from its rect in the host plot area.",
            )
        host = next((p for p in panels if p.name == inset.host), None)
        x0, y0, x1, y1 = inset.rect
        if host is None or not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise PlotError(
                "invalid_inset",
                inset.panel.name,
                "Select a host panel and a nonempty box within its plot area.",
            )
        w, h = host.style.width_points, host.style.height_points
        assert w is not None and h is not None
        width, height = (x1 - x0) * w - 44, (y1 - y0) * h - 38
        if width < 45 or height < 35:
            raise PlotError(
                "invalid_inset",
                inset.panel.name,
                "Increase the inset rectangle to fit both axes and labels.",
            )
        margins = dict(host.style.margins)
        rect = (
            margins["left"] + x0 * w,
            margins["top"] + (1 - y1) * h,
            margins["left"] + x1 * w,
            margins["top"] + (1 - y0) * h,
        )
        children.append(
            replace(
                _panel(data, inset.panel, width=width, height=height, inset=True),
                host=host.name,
                host_rect=rect,
            )
        )
    if len(panels) == 1:
        return panels[0].name, panels + children
    return "figure", panels + children + [layout("figure", panels, direction=plot.layout, gap=3)]
