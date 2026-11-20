"""Display controls operate on full synthetic arrays without changing datasets."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QMenu

from materials_data_studio.core.models import PlotStyle
from materials_data_studio.plotting.interactive_options import average_curves
from materials_data_studio.plotting.plot_spec import CurveSpec, PlotSpec
from materials_data_studio.plotting.pyqtgraph_backend import (
    add_interactive_plot_actions,
    apply_plot_theme,
    create_plot_widget,
    render_plot,
    update_rendered_plot_data,
)
from materials_data_studio.ui.localization import set_language, translate_tree


@pytest.fixture
def widget(qtbot):
    widget = create_plot_widget()
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    widget.show()
    return widget


def curves():
    x = np.linspace(0, 10, 2000)
    return [CurveSpec(x, np.sin(x), "A"), CurveSpec(x, np.cos(x), "B")]


def test_view_actions_share_plot_menu_and_cursor_reads_visible_samples(widget, qtbot):
    spec = PlotSpec("x", "y", curves(), y_log_scale=True)
    render_plot(widget, spec)
    qtbot.wait(30)
    cursor = widget._materials_cursor
    assert not cursor.action.isChecked() and cursor.proxy is None
    menu = QMenu(widget)
    add_interactive_plot_actions(menu, widget)
    plot = widget.getPlotItem()
    assert plot.getMenu().menuAction() in menu.actions()
    assert cursor.action in plot.getMenu().actions()
    assert plot.getViewBox().menu.viewAll in menu.actions()
    assert widget.scene().contextMenu[0] in menu.actions()
    cursor.action.trigger()
    position = plot.getViewBox().mapViewToScene(QPointF(1, -0.1))
    cursor._mouse_moved((position,))
    assert cursor.lines[0].isVisible()
    assert "x = 1" in cursor.readout.text() and "A: y = 0.84" in cursor.readout.text()
    plot.getViewBox().disableAutoRange()
    cursor.action.trigger()
    assert cursor.proxy is None and cursor.readout.isHidden()
    assert all(not line.isVisible() for line in cursor.lines)
    plot.getViewBox().menu.viewAll.trigger()
    assert plot.getViewBox().autoRangeEnabled() == [True, True]


def test_grid_draws_across_plot_and_survives_updates(widget, qtbot):
    spec = PlotSpec("x", "y", curves())
    render_plot(widget, spec)
    plot = widget.getPlotItem()
    plot.ctrl.xGridCheck.setChecked(True)
    plot.ctrl.yGridCheck.setChecked(True)
    qtbot.wait(30)
    image = QImage(800, 500, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        for name in ("bottom", "left"):
            axis = plot.getAxis(name)
            result = axis.generateDrawSpecs(painter)
            assert result is not None
            segments = result[1]
            assert any((end - start).manhattanLength() > 100 for _pen, start, end in segments)
    finally:
        painter.end()
    render_plot(widget, replace(spec, title="Rebuild"))
    apply_plot_theme(widget, "dark")
    assert plot.ctrl.xGridCheck.isChecked() and plot.ctrl.yGridCheck.isChecked()
    plot.ctrl.yGridCheck.setChecked(False)
    render_plot(widget, replace(spec, title="Again"))
    assert plot.getAxis("bottom").grid
    assert not plot.getAxis("left").grid


@pytest.mark.parametrize("method", ["subsample", "mean", "peak"])
def test_downsample_menu_persists_and_preserves_sources(widget, method):
    source = curves()
    spec = PlotSpec("x", "y", source)
    render_plot(widget, spec)
    plot = widget.getPlotItem()
    plot.setDownsampling(ds=10, auto=False, mode=method)
    item = widget._materials_curve_items[0]
    assert item.opts["downsample"] == 10 and item.opts["downsampleMethod"] == method
    assert len(item.getData()[0]) < len(source[0].x)
    render_plot(widget, replace(spec, title="Force full rebuild"))
    item = widget._materials_curve_items[0]
    assert item.opts["downsample"] == 10 and item.opts["downsampleMethod"] == method
    changed = replace(spec, title="Force full rebuild", curves=curves())
    assert update_rendered_plot_data(widget, changed)
    assert item.opts["downsample"] == 10
    np.testing.assert_array_equal(item.xData, source[0].x)
    np.testing.assert_array_equal(source[0].y, np.sin(source[0].x))
    plot.ctrl.downsampleCheck.setChecked(False)
    assert item.opts["downsample"] == 1 and not item.opts["autoDownsample"]


def test_reduction_protects_marker_arrays_and_nonmonotonic_curves(widget):
    source = curves()
    source += [CurveSpec(np.arange(20.), np.arange(20.), "Markers", PlotStyle(line_style="none", marker="o"), marker_sizes=np.ones(20))]
    source += [CurveSpec(np.arange(20.)[::-1], np.arange(20.), "Cooling")]
    spec = PlotSpec("x", "y", source)
    render_plot(widget, spec)
    plot = widget.getPlotItem()
    plot.setDownsampling(ds=50, auto=True, mode="peak")
    markers, cooling = widget._materials_curve_items[-2:]
    assert markers.opts["downsample"] == 1 and not markers.opts["autoDownsample"]
    assert not cooling.opts["clipToView"] and not cooling.opts["autoDownsample"]
    source[2] = replace(source[2], x=np.arange(30.), y=np.arange(30.), marker_sizes=np.ones(30))
    assert update_rendered_plot_data(widget, replace(spec, curves=source))
    assert len(markers.getData()[0]) == len(markers.opts["symbolSize"]) == 30
    render_plot(widget, replace(spec, title="Rebuild", curves=source))
    assert len(widget._materials_curve_items[2].getData()[0]) == 30


def test_average_interpolates_common_range_and_ignores_marker_overlays():
    a = CurveSpec(np.array([0., 1, 2, 3, 4]), np.array([0., 2, 4, 6, 8]), "A")
    b = CurveSpec(np.array([4., 2, 2, 1]), np.array([12., 6, 6, 3]), "B")
    markers = replace(a, style=PlotStyle(line_style="none", marker="o"))
    result = average_curves([a, b, markers])
    assert result is not None
    np.testing.assert_array_equal(result[0], [1, 2, 3, 4])
    np.testing.assert_allclose(result[1], [2.5, 5, 7.5, 10])
    assert average_curves([a, replace(b, x=b.x + 100)]) is None
    assert average_curves([a, replace(b, x=np.array([1., 4, 2, 3]))]) is None
    gap = replace(a, y=np.array([0., 2, np.nan, 6, 8]))
    result = average_curves([a, gap])
    assert result is not None and np.isnan(result[1][2])


def test_average_menu_refreshes_without_duplicate_items(widget, monkeypatch):
    source = curves()
    for curve in source:
        curve.x.setflags(write=False)
        curve.y.setflags(write=False)
    spec = PlotSpec("x", "y", source)
    render_plot(widget, spec)
    plot = widget.getPlotItem()
    plot.ctrl.averageGroup.setChecked(True)
    mean = plot.average_item
    assert mean is not None and mean.isVisible()
    np.testing.assert_allclose(mean.yData, (source[0].y + source[1].y) / 2)
    with monkeypatch.context() as context:
        context.setattr("materials_data_studio.plotting.interactive_options.average_curves", lambda _curves: pytest.fail("Recomputed unchanged data"))
        render_plot(widget, spec)
        assert plot.average_item is mean
    assert mean in plot.items
    render_plot(widget, replace(spec, title="Rebuild"))
    assert plot.average_item in plot.items and plot.average_item.isVisible()
    assert len(plot.listDataItems()) == 3
    plot.ctrl.averageGroup.setChecked(False)
    assert not plot.average_item.isVisible()
    assert update_rendered_plot_data(widget, replace(spec, title="Rebuild", curves=source[:1])) is False
    render_plot(widget, replace(spec, curves=source[:1]))
    plot.ctrl.averageGroup.setChecked(True)
    assert plot.average_item is None
    assert "two" in plot.average_status.text()


def test_menu_and_live_status_translate_both_ways(widget):
    render_plot(widget, PlotSpec("x", "y", curves()))
    plot = widget.getPlotItem()
    set_language("ja")
    translate_tree(plot.ctrlMenu, "ja")
    translate_tree(plot.ctrl.averageGroup, "ja")
    translate_tree(plot.ctrl.gridGroup, "ja")
    assert plot.ctrl.averageGroup.title() == "曲線の平均"
    assert plot.ctrl.xGridCheck.text() == "Xグリッドを表示"
    plot.ctrl.averageGroup.setChecked(True)
    assert "共通範囲" in plot.average_status.text()
    set_language("en")
    translate_tree(plot.ctrl.averageGroup, "en")
    assert plot.ctrl.averageGroup.title() == "Average"
    assert plot.average_status.text() == "Average line curves over their common X range"
