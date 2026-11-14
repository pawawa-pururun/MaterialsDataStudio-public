"""Safe display reduction and interpolation-based averages for plot menus."""
from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg
from pyqtgraph.graphicsItems.PlotItem import PlotItem
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QGridLayout, QLabel

from materials_data_studio.plotting.plot_spec import CurveSpec
from materials_data_studio.ui.localization import tr


def average_curves(curves: list[CurveSpec]) -> tuple[np.ndarray, np.ndarray] | None:
    """Average finite, monotonic line curves on the first curve's overlap grid."""
    samples = []
    for curve in curves:
        if curve.style.line_style.lower() == "none" or curve.marker_sizes is not None or curve.point_labels:
            continue
        valid = np.isfinite(curve.x)
        x, y = curve.x[valid], curve.y[valid]
        if len(x) < 2:
            continue
        if np.all(x[1:] <= x[:-1]):
            x, y = x[::-1], y[::-1]
        if not np.all(x[1:] >= x[:-1]):
            continue
        unique, inverse = np.unique(x, return_inverse=True)
        finite = np.isfinite(y)
        counts = np.bincount(inverse, weights=finite, minlength=len(unique))
        sums = np.bincount(inverse, weights=np.where(finite, y, 0.), minlength=len(unique))
        y = np.divide(sums, counts, out=np.full(len(unique), np.nan), where=counts > 0)
        if len(unique) > 1:
            samples.append((unique, y))
    if len(samples) < 2:
        return None
    low, high = max(x[0] for x, _y in samples), min(x[-1] for x, _y in samples)
    reference = samples[0][0]
    x = reference[(reference >= low) & (reference <= high)]
    if len(x) < 2:
        return None
    total = np.zeros(len(x))
    for source_x, source_y in samples:
        # NaN gaps remain gaps, including the intervals on either side.
        total += np.interp(x, source_x, source_y)
    return x, total / len(samples)


class ScientificPlotItem(PlotItem):
    """Keep the stock controls connected to safe, persistent display behavior."""

    def __init__(self, **kwargs: Any) -> None:
        self.source_curves: list[CurveSpec] = []
        self.average_item: Any = None
        self.average_revision: tuple[Any, ...] | None = None
        super().__init__(**kwargs)
        self.ctrl.downsampleCheck.setChecked(True)
        self.ctrl.clipToViewCheck.setChecked(True)
        self.ctrl.avgParamList.hide()
        self.average_status = QLabel()
        self._set_average_status("Average line curves over their common X range")
        self.average_status.setWordWrap(True)
        layout = self.ctrl.averageGroup.layout()
        assert isinstance(layout, QGridLayout)
        layout.addWidget(self.average_status, 0, 0)

    def addItem(self, item: Any, *args: Any, **kwargs: Any) -> None:
        if not isinstance(item, pg.PlotDataItem):
            super().addItem(item, *args, **kwargs)
            return
        # PlotItem applies menu defaults before the renderer can classify the
        # curve. Admit it without reduction so point-size arrays stay paired.
        downsample, clip = self.ctrl.downsampleCheck, self.ctrl.clipToViewCheck
        enabled, clipped = downsample.isChecked(), clip.isChecked()
        with QSignalBlocker(downsample), QSignalBlocker(clip):
            downsample.setChecked(False)
            clip.setChecked(False)
            try:
                super().addItem(item, *args, **kwargs)
            finally:
                downsample.setChecked(enabled)
                clip.setChecked(clipped)

    def updateDownsampling(self) -> None:
        ds, auto, method = self.downsampleMode()
        clip = self.ctrl.clipToViewCheck.isChecked()
        for item in self.curves:
            can_auto = getattr(item, "_materials_auto_reduce", False)
            can_manual = getattr(item, "_materials_manual_reduce", False)
            length = len(item.xData) if item.xData is not None else 0
            factor = min(ds, max(1, length // 2)) if can_manual else 1
            item.setClipToView(clip and can_auto)
            item.setDownsampling(factor, auto and can_auto, method)

    def addAvgCurve(self, curve: Any) -> None:
        # PlotItem calls this while adding each item. Average full source arrays
        # once, after the complete scene has been supplied by the renderer.
        pass

    def avgToggled(self, b: bool) -> None:
        self.recomputeAverages()

    def _set_average_status(self, message: str) -> None:
        rendered = tr(message)
        self.average_status.setProperty("mdsCaptionSource", message)
        self.average_status.setProperty("mdsCaptionRendered", rendered)
        self.average_status.setText(rendered)

    def recomputeAverages(self) -> None:
        if self.average_item is not None:
            self.average_item.setVisible(False)
        if not self.ctrl.averageGroup.isChecked() or not hasattr(self, "average_status"):
            self.average_revision = None
            return
        immutable = all(not c.x.flags.writeable and not c.y.flags.writeable for c in self.source_curves)
        revision = tuple((id(c.x), id(c.y), c.style.line_style, c.marker_sizes is None, bool(c.point_labels)) for c in self.source_curves)
        if immutable and revision == self.average_revision and self.average_item is not None and self.average_item in self.items:
            self.average_item.setVisible(True)
            self._set_average_status("Average line curves over their common X range")
            return
        result = average_curves(self.source_curves)
        if result is None:
            self._set_average_status("Average needs two monotonic line curves with overlapping X ranges")
            self.average_revision = None
            return
        x, y = result
        if self.average_item not in self.items:
            self.average_item = pg.PlotDataItem(pen=pg.mkPen("#e07022", width=2.5))
            self.average_item._materials_auto_reduce = True
            self.average_item._materials_manual_reduce = True
            self.addItem(self.average_item, skipAverage=True)
            self.average_item.setZValue(50)
        assert self.average_item is not None
        self.average_item.setData(x, y)
        self.average_item.setVisible(True)
        self.updateDownsampling()
        self._set_average_status("Average line curves over their common X range")
        self.average_revision = revision if immutable else None

    def set_source_curves(self, curves: list[CurveSpec], items: list[Any], auto_reduce: list[bool]) -> None:
        self.source_curves = curves
        if self.average_item not in self.items:
            self.average_item = None
            self.average_revision = None
        for curve, item, automatic in zip(curves, items, auto_reduce, strict=True):
            manual = curve.marker_sizes is None and not curve.point_labels
            item._materials_manual_reduce = manual
            item._materials_auto_reduce = automatic
        self.updateDownsampling()
        self.recomputeAverages()
