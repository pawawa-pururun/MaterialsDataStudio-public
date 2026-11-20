"""On-demand cursor for the main-window interactive plots."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel

from materials_data_studio.ui.localization import tr


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
        self.proxy: Any = None
        self.order: dict[int, tuple[Any, Any, np.ndarray, np.ndarray]] = {}
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
            self.readout = QLabel(self.viewport)
            self.readout.setAutoFillBackground(True)
            self.readout.setTextFormat(Qt.TextFormat.PlainText)
            self.readout.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.readout.setMargin(5)
        self.viewport.installEventFilter(self)
        self.proxy = pg.SignalProxy(self.scene.sigMouseMoved, rateLimit=30, slot=self._mouse_moved)

    def hide(self) -> None:
        for line in self.lines:
            line.hide()
        if self.readout is not None:
            self.readout.hide()

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
        values = [header, *(f"{name} = {x:.5f}°" for name, x in guides)]
        if guides:
            values[0] = "Cu Kα1 · " + values[0]
        items = self.plot.listDataItems()
        live_items = {id(item) for item in items}
        for key in self.order.keys() - live_items:
            del self.order[key]
        tolerance = abs(self.view.viewPixelSize()[0]) * 4
        for index, item in enumerate(items):
            if not item.isVisible():
                continue
            value = self._nearest_y(item, mouse.x(), mouse.y(), tolerance)
            if value is not None:
                name = item.name() or (tr("Average") if item is self.plot.average_item else f"y{index + 1}")
                values.append(f"{name}: y = {float(np.power(10.0, value)) if y_log else value:.7g}")
        assert self.readout is not None
        caption = "\n".join(values)
        if self.readout.text() != caption:
            self.readout.setText(caption)
            self.readout.adjustSize()
        self.readout.move(self.widget.mapFromScene(self.view.sceneBoundingRect().topLeft()) + QPoint(6, 6))
        self.readout.show()

    def _nearest_y(self, item: Any, x: float, mouse_y: float, tolerance: float) -> float | None:
        # Use the displayed samples, including clipping, downsampling and log
        # transforms. Index once per displayed array rather than per mouse move.
        px, py = item.getData()
        if px is None or py is None or len(px) == 0:
            return None
        key = id(item)
        entry = self.order.get(key)
        if entry is None or entry[0] is not px or entry[1] is not py:
            valid = np.flatnonzero(np.isfinite(px) & np.isfinite(py))
            valid_x = px[valid]
            if np.all(valid_x[:-1] >= valid_x[1:]):
                valid = valid[::-1]
                valid_x = valid_x[::-1]
            elif not np.all(valid_x[:-1] <= valid_x[1:]):
                order = np.argsort(valid_x, kind="stable")
                valid, valid_x = valid[order], valid_x[order]
            entry = self.order[key] = (px, py, valid_x, valid)
        _, _, sorted_x, indices = entry
        if not len(indices) or not sorted_x[0] - tolerance <= x <= sorted_x[-1] + tolerance:
            return None
        right = int(np.searchsorted(sorted_x, x))
        nearest = min((max(0, right - 1), min(right, len(indices) - 1)),
                      key=lambda index: abs(sorted_x[index] - x))
        start = int(np.searchsorted(sorted_x, sorted_x[nearest], side="left"))
        stop = int(np.searchsorted(sorted_x, sorted_x[nearest], side="right"))
        values = py[indices[start:stop]]
        return float(values[np.argmin(np.abs(values - mouse_y))])
