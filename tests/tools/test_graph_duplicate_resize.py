"""Synthetic regressions for graph copies and drawing corner gestures."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog
from tests.tools.test_graph_document import source  # noqa: F401
from tests.tools.test_graph_interaction import editor_window  # noqa: F401

from materials_data_studio.tools.graph_document import load_graph_document, save_graph_document
from materials_data_studio.tools.graph_drawing import DrawingDialog
from materials_data_studio.tools.graph_handles import drawing_corners
from materials_data_studio.tools.graph_window import GraphEditorWindow
from materials_data_studio.tools.pxp_model import PxpDrawing
from materials_data_studio.ui.localization import translate_tree


def test_duplicate_graph_menu_shortcut_and_independent_layout(window: GraphEditorWindow, qtbot, tmp_path: Path):
    editor = window.editor
    assert editor is not None
    original = window.graph()
    assert original is not None
    editor.document.current.layout[original.name] = {"custom": {"position": [1, 2]}}
    waves = editor.document.current.waves
    window.canvas.setFocus()
    qtbot.keyClick(window.canvas, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    copied = window.graph()
    assert copied is not None and copied.name == original.name + "_copy"
    assert replace(copied, name=original.name) == original
    assert editor.document.current.waves is waves
    copied_layout = editor.document.current.layout[copied.name]
    assert copied_layout == editor.document.current.layout[original.name]
    assert copied_layout is not editor.document.current.layout[original.name]
    copied_layout["custom"]["position"][0] = 42
    assert editor.document.current.layout[original.name]["custom"]["position"] == [1, 2]
    path = tmp_path / "duplicates.mdsg"
    save_graph_document(path, editor.document)
    restored = load_graph_document(path)
    assert restored.current.graphs == editor.document.current.graphs
    window.undo_action.trigger()
    assert len(editor.document.current.graphs) == 2
    window.redo_action.trigger()
    assert len(editor.document.current.graphs) == 3
    window._selection = "graph", original.name
    window._show_selection()
    window.duplicate_graph_action.trigger()
    assert window.graph().name == original.name + "_copy_2"


def test_duplicate_copies_subwindows_and_rebinds_action(window: GraphEditorWindow):
    editor = window.editor
    assert editor is not None
    graph = window.graph()
    assert graph is not None
    before = editor.document.current.clone()
    after = before.clone()
    child = replace(graph, name="Inset", host=graph.name, host_rect=(.2, .2, .5, .5))
    after.graphs += (child,)
    editor.commit(before, after, "Inset")
    window.duplicate_graph_action.trigger()
    graphs = {g.name: g for g in editor.document.current.graphs}
    assert graphs["Inset_copy"].host == graph.name + "_copy"
    assert graphs["Inset_copy"].host_rect == child.host_rect
    assert graphs[graph.name + "_copy"].host == ""
    window.bind_document(editor.document.source)
    assert sum(a.shortcut().toString() == "Ctrl+D" for a in window.edit_menu.actions()) == 1
    window._selection = "wave", "x"
    window._show_selection()
    assert not window.duplicate_graph_action.isEnabled()
    translate_tree(window.edit_menu, "ja")
    assert window.duplicate_graph_action.text() == "グラフを複製"
    translate_tree(window.edit_menu, "en")
    assert window.duplicate_graph_action.text() == "Duplicate Graph"


@pytest.mark.parametrize("coordinates", [(.2, .2, .2, .6), (.2, .2, .6, .2), (.2, .2, .2, .2)])
def test_zero_extent_arc_render_insert_and_save(window: GraphEditorWindow, monkeypatch, tmp_path: Path, coordinates):
    assert window.editor is not None
    graph = window.graph()
    assert graph is not None
    window.editor.edit_graph(replace(graph, drawings=(PxpDrawing("DrawArc", coordinates),)), "Arc")
    window.canvas.draw()
    window.figure.savefig(tmp_path / "arc.png")
    path = tmp_path / "arc.mdsg"
    save_graph_document(path, window.editor.document)
    assert load_graph_document(path).graph(graph.name).drawings[0].coordinates == coordinates

    def accept(dialog):
        dialog.apply()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DrawingDialog, "exec", accept)
    ax = window.figure.axes[0]
    start, end = ax.transAxes.transform([(coordinates[0], coordinates[1]), (coordinates[2], coordinates[3])])
    window.drawing_actions["Arc"].trigger()
    window.pointer_press(SimpleNamespace(button=1, dblclick=False, x=start[0], y=start[1], inaxes=ax))
    window.pointer_move(SimpleNamespace(x=end[0], y=end[1]))
    window._paint_drag()
    window.pointer_release(SimpleNamespace(x=end[0], y=end[1]))
    window.canvas.draw()


@pytest.mark.parametrize("kind", ["DrawLine", "DrawRect", "DrawRRect", "DrawOval", "DrawArc", "DrawPoly", "DrawBezier"])
@pytest.mark.parametrize("corner", range(4))
def test_corner_resize_blit_undo_and_snap(window: GraphEditorWindow, monkeypatch, kind: str, corner: int):
    editor = window.editor
    graph = window.graph()
    assert editor is not None and graph is not None
    coords = (.2, .2, .3, .7, .5, .1, .7, .6) if kind == "DrawBezier" else (.2, .2, .6, .6)
    if kind == "DrawArc":
        coords += (30., 270.)
    drawing = PxpDrawing(kind, coords)
    editor.edit_graph(replace(graph, drawings=(drawing,)), "Shape")
    window.drawing_selected = 0
    window.select_target("drawing", "0")
    artist = next(a for a, t in window.artist_targets.items() if t == ("drawing", "0"))
    initial = drawing_corners(artist)
    point = initial[corner]
    window.pointer_press(SimpleNamespace(button=1, dblclick=False, x=point[0], y=point[1], inaxes=artist.axes))
    assert window._bezier_drag is not None and window._bezier_drag["corner"] == corner
    draw = window.canvas.draw
    monkeypatch.setattr(window.canvas, "draw", lambda: pytest.fail("Full draw during resize"))
    destination = point + np.array([23, 17])
    for _ in range(3):
        window.pointer_move(SimpleNamespace(x=destination[0], y=destination[1], key="shift"))
        window._paint_drag()
    assert editor.history.count() == 1
    changed = drawing_corners(artist)
    np.testing.assert_allclose(changed[3 - corner], initial[3 - corner], atol=1e-8)
    ratio, height = window.canvas.device_pixel_ratio, window.figure.bbox.height
    assert changed[corner, 0] / (10 * ratio) == pytest.approx(round(destination[0] / (10 * ratio)))
    assert (height - changed[corner, 1]) / (10 * ratio) == pytest.approx(round((height - destination[1]) / (10 * ratio)))
    monkeypatch.setattr(window.canvas, "draw", draw)
    window.pointer_release(SimpleNamespace(x=destination[0], y=destination[1], key="shift"))
    assert editor.history.count() == 2
    if kind == "DrawArc":
        assert window.graph().drawings[0].coordinates[4:] == (30., 270.)
    window.undo_action.trigger()
    assert window.graph().drawings == (drawing,)
    window.redo_action.trigger()
    assert window.graph().drawings != (drawing,)


@pytest.mark.parametrize("coordinates", [(.2, .2, .2, .6), (.2, .2, .6, .2), (.2, .2, .2, .2)])
def test_degenerate_resize_can_expand_and_escape(window: GraphEditorWindow, coordinates):
    editor, graph = window.editor, window.graph()
    assert editor is not None and graph is not None
    drawing = PxpDrawing("DrawArc", coordinates)
    editor.edit_graph(replace(graph, drawings=(drawing,)), "Arc")
    window.drawing_selected = 0
    window.select_target("drawing", "0")
    artist = next(a for a, t in window.artist_targets.items() if t == ("drawing", "0"))
    x, y = drawing_corners(artist)[0]
    window.pointer_press(SimpleNamespace(button=1, dblclick=False, x=x, y=y, inaxes=artist.axes))
    window.pointer_move(SimpleNamespace(x=x - 20, y=y - 20))
    window._paint_drag()
    assert window._bezier_drag is not None
    assert np.isfinite(window._bezier_drag["draft"].coordinates).all()
    window.pointer_key(SimpleNamespace(key="escape"))
    assert window._bezier_drag is None
    assert window.graph().drawings == (drawing,)
    assert editor.history.count() == 1


@pytest.mark.parametrize("coordinate", ["abs", "prel", "bottom"])
@pytest.mark.parametrize("ratio", [1., 2.])
def test_resize_coordinate_systems_log_axes_and_crossed_corners(window: GraphEditorWindow, coordinate, ratio):
    editor, graph = window.editor, window.graph()
    assert editor is not None and graph is not None
    axes = tuple(replace(a, limits=(100., 1.), style=replace(a.style, log=1, manual_ticks=None))
                 if a.name == "bottom" else a for a in graph.axes)
    coordinates = (100., 80., 180., 140.) if coordinate == "abs" else (2., .2, 10., .6) if coordinate == "bottom" else (.2, .2, .6, .6)
    drawing = PxpDrawing("DrawRect", coordinates, xcoord=coordinate, ycoord="abs" if coordinate == "abs" else "prel")
    window.canvas._set_device_pixel_ratio(ratio)
    editor.edit_graph(replace(graph, axes=axes, drawings=(drawing,)), "Shape")
    window.drawing_selected = 0
    window.select_target("drawing", "0")
    window.canvas.draw()
    artist = next(a for a, t in window.artist_targets.items() if t == ("drawing", "0"))
    initial = drawing_corners(artist)
    x, y = initial[0]
    destination = initial[3] + np.array([25., 35.])
    window.pointer_press(SimpleNamespace(button=1, dblclick=False, x=x, y=y, inaxes=artist.axes))
    window.pointer_release(SimpleNamespace(x=destination[0], y=destination[1]))
    artist = next(a for a, t in window.artist_targets.items() if t == ("drawing", "0"))
    final = drawing_corners(artist)
    np.testing.assert_allclose(final[0], initial[3], atol=1e-7)
    np.testing.assert_allclose(final[3], destination, atol=1e-7)
    window.undo_action.trigger()
    assert window.graph().drawings == (drawing,)


def test_handle_grab_offset_is_preserved_and_click_is_a_noop(window: GraphEditorWindow):
    editor, graph = window.editor, window.graph()
    assert editor is not None and graph is not None
    drawing = PxpDrawing("DrawRect", (.2, .2, .6, .6))
    editor.edit_graph(replace(graph, drawings=(drawing,)), "Shape")
    window.drawing_selected = 0
    window.select_target("drawing", "0")
    artist = next(a for a, t in window.artist_targets.items() if t == ("drawing", "0"))
    initial = drawing_corners(artist)
    x, y = initial[0] + np.array([3., 2.])
    event = SimpleNamespace(button=1, dblclick=False, x=x, y=y, inaxes=artist.axes)
    window.pointer_press(event)
    window.pointer_release(event)
    assert editor.history.count() == 1
    assert window.graph().drawings == (drawing,)
    window.pointer_press(event)
    window.pointer_move(SimpleNamespace(x=x + 19., y=y + 15.))
    window._paint_drag()
    np.testing.assert_allclose(drawing_corners(artist)[0], initial[0] + np.array([19., 15.]), atol=1e-8)
    window.pointer_move(SimpleNamespace(x=x, y=y, key="shift"))
    window.pointer_release(SimpleNamespace(x=x, y=y, key="shift"))
    assert editor.history.count() == 1
    assert window.graph().drawings == (drawing,)
    assert artist.drawing == drawing
    np.testing.assert_allclose(drawing_corners(artist), initial, atol=1e-8)
