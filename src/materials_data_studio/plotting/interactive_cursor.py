"""On-demand cursor for the main-window interactive plots."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel


class PlotCursor(QObject):
    def __init__(self, widget: pg.PlotWidget, action: QAction) -> None:
        super().__init__(widget)
        self.widget = widget
        self.action = action
        self.plot = cast(Any, widget.getPlotItem())
        self.view = self.plot.getViewBox()
        self.scene = cast(Any, widget.scene())
        self.viewport = widget.viewport()
        assert self.viewport is not None
        self.xrd_readout: Callable[[float, bool], tuple[str, list[tuple[str, float]]]] | None = None
        self.radiation_action: QAction | None = None
        self.lines: list[Any] = []
        self.readout: QLabel | None = None
        self.value_labels: list[QLabel] = []
        self.markers: Any = None
        self.proxy: Any = None
        self.order: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, bool]] = {}
        action.toggled.connect(self.set_enabled)

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            if self.proxy is not None:
                self.proxy.disconnect()
                self.proxy.deleteLater()
                self.proxy = None
            self.viewport.removeEventFilter(self)
            self.order.clear()
            self.hide()
            return
        if self.readout is None:
            self.readout = self._new_label()
            self.markers = pg.ScatterPlotItem(size=7, brush="#3b82f6", pen=pg.mkPen("#ffffff", width=1))
            self.markers.setZValue(1101)
            self.view.addItem(self.markers, ignoreBounds=True)
            self.markers.hide()
        self.viewport.installEventFilter(self)
        self.proxy = pg.SignalProxy(self.scene.sigMouseMoved, rateLimit=30, slot=self._mouse_moved)

    def hide(self) -> None:
        for line in self.lines:
            line.hide()
        if self.readout is not None:
            self.readout.hide()
        if self.markers is not None:
            self.markers.hide()
        for label in self.value_labels:
            label.hide()

    def _new_label(self) -> QLabel:
        label = QLabel(self.viewport)
        label.setAutoFillBackground(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.setMargin(2)
        return label

    def _place_label(self, label: QLabel, caption: str, x: int, y: int, *, center: bool = False) -> None:
        if caption != label.text():
            label.setText(caption)
            label.adjustSize()
        if x + 7 + label.width() <= self.viewport.width():
            left = x + 7
        else:
            left = max(0, x - 7 - label.width())
        top = y - label.height() // 2 if center else y
        label.move(left, max(0, min(top, self.viewport.height() - label.height())))
        label.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
            self.hide()
        return False

    def _mouse_moved(self, args: tuple[QPointF]) -> None:
        if not self.action.isChecked() or not self.view.sceneBoundingRect().contains(args[0]):
            self.hide()
            return
        mouse = self.view.mapSceneToView(args[0])
        x_log, y_log = self.plot.ctrl.logXCheck.isChecked(), self.plot.ctrl.logYCheck.isChecked()
        x_value = float(np.power(10.0, mouse.x())) if x_log else mouse.x()
        if not math.isfinite(x_value):
            self.hide()
            return
        header = f"x = {x_value:.7g}"
        guides = []
        if self.xrd_readout is not None:
            header, guides = self.xrd_readout(
                x_value, self.radiation_action is not None and self.radiation_action.isChecked()
            )
            # Keep the XRD caption narrow enough to sit beside the cursor.
            header = header.replace(" · ", "\n")
        positions = [mouse.x(), *(math.log10(x) if x_log else x for _, x in guides)]
        colors = ("#3b82f6", "#e38b21", "#aa63db")
        styles = (Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine, Qt.PenStyle.DashDotLine)
        for index, position in enumerate(positions):
            if index == len(self.lines):
                line = pg.InfiniteLine(pen=pg.mkPen(colors[index], width=1.5, style=styles[index]))
                line.setZValue(1100)
                self.view.addItem(line, ignoreBounds=True)
                self.lines.append(line)
            self.lines[index].setPos(position)
            self.lines[index].show()
        for line in self.lines[len(positions):]:
            line.hide()
        if guides:
            header = "Cu Kα1\n" + header
            header += "".join(f"\n{name} = {angle:.5f}°" for name, angle in guides)
        assert self.readout is not None
        top = self.widget.mapFromScene(QPointF(args[0].x(), self.view.sceneBoundingRect().top()))
        self._place_label(self.readout, header, top.x(), top.y() + 4)

        items = self.plot.listDataItems()
        live_items = {id(item) for item in items}
        for key in self.order.keys() - live_items:
            del self.order[key]
        tolerance = abs(self.view.viewPixelSize()[0]) * 4
        low, high = self.view.viewRange()[1]
        values = sorted({
            value for item in items if item.isVisible()
            for value in self._intersection_y(item, mouse.x(), mouse.y(), tolerance)
            if low <= value <= high
        })
        self.markers.setData(x=np.full(len(values), mouse.x()), y=np.asarray(values))
        self.markers.setVisible(bool(values))
        occupied_rows: set[int] = set()
        count = 0
        for value in values:
            point = self.widget.mapFromScene(self.view.mapViewToScene(QPointF(mouse.x(), value)))
            if point.y() in occupied_rows:
                continue
            occupied_rows.add(point.y())
            if count == len(self.value_labels):
                self.value_labels.append(self._new_label())
            display_value = float(np.power(10.0, value)) if y_log else value
            self._place_label(self.value_labels[count], f"{display_value:.7g}", point.x(), point.y(), center=True)
            count += 1
        for label in self.value_labels[count:]:
            label.hide()

    def _intersection_y(self, item: Any, x: float, mouse_y: float, tolerance: float) -> list[float]:
        # Interpolate in the displayed coordinate system so log plots and
        # downsampled curves intersect the same segments the user sees.
        px, py = item.getData()
        if px is None or py is None or len(px) == 0:
            return []
        key = id(item)
        entry = self.order.get(key)
        if entry is None or entry[0] is not px or entry[1] is not py:
            valid = np.flatnonzero(np.isfinite(px) & np.isfinite(py))
            valid_x = px[valid]
            descending = bool(np.all(valid_x[:-1] >= valid_x[1:]))
            monotonic = descending or bool(np.all(valid_x[:-1] <= valid_x[1:]))
            if descending:
                valid = valid[::-1]
                valid_x = valid_x[::-1]
            elif not monotonic:
                order = np.argsort(valid_x, kind="stable")
                valid, valid_x = valid[order], valid_x[order]
            entry = self.order[key] = (px, py, valid_x, valid, monotonic)
        _, _, sorted_x, indices, monotonic = entry
        if not len(indices) or not sorted_x[0] - tolerance <= x <= sorted_x[-1] + tolerance:
            return []
        right = int(np.searchsorted(sorted_x, x))
        pen = item.curve.opts["pen"]
        if not item.curve.isVisible() or pen is None or pen.style() == Qt.PenStyle.NoPen:
            if item.opts["symbol"] is None:
                return []
            start = int(np.searchsorted(sorted_x, x - tolerance))
            stop = int(np.searchsorted(sorted_x, x + tolerance, side="right"))
            return py[indices[start:stop]].tolist()
        if monotonic:
            stop = int(np.searchsorted(sorted_x, x, side="right"))
            nearby = indices[max(0, right - 1):stop + 1]
            adjacent = np.abs(np.diff(nearby)) == 1
            left, right_indices = nearby[:-1][adjacent], nearby[1:][adjacent]
        else:
            crosses = ((px[:-1] <= x) & (x <= px[1:])) | ((px[1:] <= x) & (x <= px[:-1]))
            left = np.flatnonzero(crosses & np.isfinite(py[:-1]) & np.isfinite(py[1:]))
            right_indices = left + 1
        x0, x1 = px[left], px[right_indices]
        y0, y1 = py[left], py[right_indices]
        regular = x0 != x1
        fraction = np.divide(x - x0, x1 - x0, out=np.zeros_like(x0, dtype=float), where=regular)
        values = np.where(regular, y0 + fraction * (y1 - y0), np.clip(mouse_y, np.minimum(y0, y1), np.maximum(y0, y1)))
        return values.tolist()
