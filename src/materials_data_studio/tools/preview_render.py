"""Qt-free reference rendering for generated previews and custom styles."""

from __future__ import annotations

import numpy as np
from matplotlib import colormaps
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from materials_data_studio.tools.pxp_markers import marker_path
from materials_data_studio.tools.pxp_render import _DASH_PATTERNS
from materials_data_studio.tools.pxp_style import colormap


def style_pixels(kind: str, number: int, dark: bool = False,
                 pattern: tuple[float, ...] | None = None, scale: int = 1) -> np.ndarray:
    figure = Figure(figsize=(.96, .28), dpi=100 * scale)
    figure.patch.set_alpha(0)
    ax = figure.add_axes((0, 0, 1, 1))
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    color = "#e2e8f0" if dark else "#334155"
    if kind == "marker":
        filled = number in {14, 15, 16, 17, 18, 19, 23, 26, 29, 46, 49, 52, 55, 58, 60, 62} or number in range(32, 39, 2)
        ax.plot([.5], [.5], marker=marker_path(number), markersize=11,
                markerfacecolor=color if filled else "none", markeredgecolor=color, markeredgewidth=1.2)
    else:
        line, = ax.plot([.07, .93], [.5, .5], color=color, linewidth=1.6)
        if number:
            line.set_linestyle((0, pattern or _DASH_PATTERNS.get(number, (4, 4))))
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    return np.asarray(canvas.buffer_rgba()).copy()


def colormap_pixels(name: str, scale: int = 1) -> np.ndarray:
    colors = np.rint(colormaps[colormap(name)](np.linspace(0, 1, 90)) * 255).astype(np.uint8)
    row = np.repeat(colors, scale, axis=0)
    return np.repeat(row[np.newaxis, :, :], 16 * scale, axis=0)
