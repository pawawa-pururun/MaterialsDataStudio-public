"""Viewport invalidation and graph-list operations use synthetic graph documents."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox
from tests.tools.test_graph_document import source  # noqa: F401
from tests.tools.test_graph_interaction import editor_window  # noqa: F401

from materials_data_studio.tools.graph_actions import graph_list_action
from materials_data_studio.tools.graph_document import load_graph_document, save_graph_document
from materials_data_studio.tools.graph_render import IgorMatplotlibRenderer
from materials_data_studio.tools.graph_window import GraphEditorWindow
from materials_data_studio.tools.pxp_model import PxpGraph, PxpLayoutItem
from materials_data_studio.ui.localization import translate_tree


def assert_current_geometry(window):
    expected = Figure(figsize=window.figure.get_size_inches(), dpi=window.figure.dpi)
    FigureCanvasAgg(expected)
    IgorMatplotlibRenderer().render(expected, window.editor.document, window.graph().name)
    expected.canvas.draw()
    for actual, reference in zip(window.figure.axes, expected.axes, strict=True):
        np.testing.assert_allclose(actual.get_position().bounds, reference.get_position().bounds)
        assert actual.xaxis.label.get_fontsize() == pytest.approx(reference.xaxis.label.get_fontsize())
        assert actual.yaxis.label.get_fontsize() == pytest.approx(reference.yaxis.label.get_fontsize())
    assert window._rendered_geometry == (*window.figure.get_size_inches(), window.figure.dpi)


@pytest.mark.parametrize("name", ["XY", "Map"])
def test_resize_updates_geometry_fonts_and_retains_zoom(window, qtbot, name):
    window.tree.setCurrentItem(graph_item(window, name))
    qtbot.waitUntil(lambda: not window._resize_timer.isActive())
    before = window.editor.document.current.clone()
    ax = window.figure.axes[0]
    original_font = ax.xaxis.label.get_fontsize()
    ax.set_xlim(1., 3.)
    ax.set_ylim(2., 4.)
    window.resize(1080, 690)
    qtbot.waitUntil(lambda: not window._resize_timer.isActive())
    window.canvas.draw()
    assert_current_geometry(window)
    assert window.figure.axes[0].xaxis.label.get_fontsize() != pytest.approx(original_font)
    np.testing.assert_allclose(window.figure.axes[0].get_xlim(), (1, 3))
    np.testing.assert_allclose(window.figure.axes[0].get_ylim(), (2, 4))
    assert window.editor.document.current == before
    assert window.editor.history.count() == 0


def test_open_before_show_uses_final_canvas_size(window, qtbot, tmp_path):
    path = tmp_path / "synthetic.mdsg"
    save_graph_document(path, window.editor.document)
    other = GraphEditorWindow()
    qtbot.addWidget(other)
    other._discard_approved = True
    other.bind_graph_document(load_graph_document(path), path)
    other.resize(1100, 710)
    other.show()
    qtbot.waitUntil(lambda: not other._resize_timer.isActive())
    other.canvas.draw()
    assert_current_geometry(other)
    assert not other.editor.dirty


def test_resize_burst_is_coalesced_and_dpi_invalidates_fast_path(window, qtbot, monkeypatch):
    qtbot.waitUntil(lambda: not window._resize_timer.isActive())
    calls = []
    render = window.renderer.render
    def tracked(*args, **kwargs):
        calls.append(True)
        return render(*args, **kwargs)
    monkeypatch.setattr(window.renderer, "render", tracked)
    for _ in range(20):
        window._canvas_resized(None)
    assert not calls
    qtbot.waitUntil(lambda: not window._resize_timer.isActive())
    assert len(calls) == 1
    window.figure.set_dpi(window.figure.dpi * 1.25)
    window._draw_graph(window.graph())
    assert len(calls) == 2
    assert_current_geometry(window)


def graph_item(window, name):
    return next(item for item in window.tree.findItems(name, Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive)
                if item.data(0, Qt.ItemDataRole.UserRole) == ("graph", name))


def test_tree_menu_acts_on_clicked_graph(window, qtbot):
    qtbot.waitUntil(lambda: not window._resize_timer.isActive())
    assert window.graph().name == "XY"
    item = graph_item(window, "Map")
    window.tree.scrollToItem(item)
    point = window.tree.visualItemRect(item).center()
    window.tree.customContextMenuRequested.emit(point)
    actions = {a.text(): a for a in window.context_menu.actions()}
    assert set(actions) == {"Duplicate Graph", "Rename Graph…", "Delete Graph…"}
    window.context_menu.close()
    actions["Duplicate Graph"].trigger()
    assert window.graph().name == "Map_copy"
    assert window.graph().images == window.editor.document.graph("Map").images
    window.undo_action.trigger()
    assert "Map_copy" not in [g.name for g in window.editor.document.current.graphs]


def test_graph_list_menu_is_translated(window):
    item = graph_item(window, "XY")
    window.tree.customContextMenuRequested.emit(window.tree.visualItemRect(item).center())
    translate_tree(window.context_menu, "ja")
    assert {a.text() for a in window.context_menu.actions()} == {"グラフを複製", "グラフ名を変更…", "グラフを削除…"}
    window.context_menu.close()


def install_references(window):
    editor = window.editor
    before = editor.document.current.clone()
    after = before.clone()
    graph = editor.document.graph("XY")
    after.graphs += (replace(graph, name="Inset", host="XY", host_rect=(.2, .2, .5, .5)),
                    replace(graph, name="Nested", host="Inset", host_rect=(.2, .2, .5, .5)),
                    PxpGraph("Page", window_kind="Layout", layout_items=(PxpLayoutItem("XY", (.1, .1, .8, .8)), PxpLayoutItem("Map", (.1, .1, .4, .4)))))
    after.layout["XY"] = {"labels": {"bottom": {"offset_points": 12., "lateral": .5}}}
    editor.commit(before, after, "Synthetic references")
    return graph


def test_rename_updates_host_layout_and_persistence(window, monkeypatch, tmp_path):
    install_references(window)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("Renamed graph", True))
    graph_list_action(window, "rename", "XY")
    editor = window.editor
    assert window.graph().name == "Renamed graph"
    assert editor.document.graph("Inset").host == "Renamed graph"
    assert editor.document.graph("Page").layout_items[0].graph == "Renamed graph"
    assert "XY" not in editor.document.current.layout
    assert "Renamed graph" in editor.document.current.layout
    path = tmp_path / "renamed.mdsg"
    save_graph_document(path, editor.document)
    assert load_graph_document(path).current.graphs == editor.document.current.graphs
    window.undo_action.trigger()
    assert editor.document.graph("Inset").host == "XY"
    assert editor.document.graph("Page").layout_items[0].graph == "XY"
    window.redo_action.trigger()
    assert editor.document.graph("Inset").host == "Renamed graph"


@pytest.mark.parametrize("name", ["", "Map", "bad;command", "bad\nname"])
def test_invalid_rename_is_transactional(window, monkeypatch, name):
    before = window.editor.document.current.clone()
    warnings = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: (name, True))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a))
    graph_list_action(window, "rename", "XY")
    assert warnings
    assert window.editor.document.current == before
    assert window.editor.history.count() == 0


@pytest.mark.parametrize("operation", ["duplicate", "rename", "delete"])
def test_pending_properties_can_cancel_graph_management(window, monkeypatch, operation):
    edit = window.property_widgets["axis"]["widgets"]["major_length"][0]
    edit.setText("12.5")
    before = window.editor.document.current.clone()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("Renamed", True))
    questions = []
    def ask(*args):
        questions.append(args[1])
        return QMessageBox.StandardButton.Yes if args[1] == "Delete Graph" else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", ask)
    graph_list_action(window, operation, "XY")
    assert window.editor.document.current == before
    assert window.graph().name == "XY" and edit.text() == "12.5"
    assert questions.count("Unapplied property edits") == 1
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    graph_list_action(window, operation, "XY")
    assert window.editor.document.current != before
    assert window.graph() is not None


def test_delete_confirmation_descendants_layouts_and_undo(window, monkeypatch):
    install_references(window)
    editor = window.editor
    before = editor.document.current.clone()
    waves = editor.document.render_source().waves
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    graph_list_action(window, "delete", "XY")
    assert editor.document.current == before
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    graph_list_action(window, "delete", "XY")
    assert {g.name for g in editor.document.current.graphs} == {"Map", "Page"}
    assert [item.graph for item in editor.document.graph("Page").layout_items] == ["Map"]
    assert "XY" not in editor.document.current.layout
    assert all(a is b for a, b in zip(waves, editor.document.render_source().waves, strict=True))
    window.undo_action.trigger()
    assert editor.document.current.graphs == before.graphs
    assert editor.document.current.layout == before.layout
    window.redo_action.trigger()
    assert window.graph().name == "Map"
    graph_list_action(window, "delete", "Page")
    assert window.graph().name == "Map"
    graph_list_action(window, "delete", "Map")
    assert not editor.document.current.graphs
