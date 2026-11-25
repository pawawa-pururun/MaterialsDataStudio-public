"""Normal Graph Editor actions create editable figures from files or working waves."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from materials_data_studio.tools.graph_template_dialog import GraphTemplateDialog
from materials_data_studio.tools.graph_waves import empty_document, make_wave, put_waves
from materials_data_studio.tools.graph_window import GraphEditorWindow


def test_graph_editor_template_loads_two_scans_and_undoes_one_edit(qtbot, monkeypatch, tmp_path: Path):
    first, second = tmp_path / "scan_a.csv", tmp_path / "scan_b.csv"
    first.write_bytes(b"2theta (deg),Intensity (count)\r\n10,10\r\n20,50\r\n30,20\r\n")
    second.write_bytes(b"Intensity (count),2theta (deg)\n20,10\n90,20\n40,30\n")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_a, **_k: ([str(first), str(second)], ""))
    window = GraphEditorWindow()
    qtbot.addWidget(window)
    window._discard_approved = True
    window.show()

    def complete() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GraphTemplateDialog)
        try:
            dialog.add_files.click()
            dialog.kind.setCurrentIndex(dialog.kind.findData("xrd_stack"))
            assert dialog.scan_count.value() == 2
            assert dialog.preview.rowCount() == 3
            dialog.create_button.click()
            assert dialog.result_edit is not None, dialog.status.text()
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, complete)
    window.template_action.trigger()
    assert window.editor is not None
    graph = window.graph()
    assert graph is not None and len(graph.traces) == 2
    source = window.editor.document.render_source()
    trace = graph.traces[1]
    assert trace.x_wave is not None
    x, y = source.wave(trace.x_wave), source.wave(trace.y_wave)
    assert x is not None and y is not None
    np.testing.assert_array_equal(x.data, [10, 20, 30])
    np.testing.assert_array_equal(y.data, [20, 90, 40])
    assert window.editor.history.count() == 1
    window.undo_action.trigger()
    assert not window.editor.document.current.graphs
    assert not window.editor.document.render_source().waves
    window.redo_action.trigger()
    assert window.graph() is not None


def test_template_uses_existing_waves_and_keeps_them_after_undo(qtbot, tmp_path: Path):
    window = GraphEditorWindow()
    qtbot.addWidget(window)
    window._discard_approved = True
    document = empty_document()
    x, y = make_wave("time", [1, 2, 3]), make_wave("signal", [10, 20, 30])
    document.current = put_waves(document, [x, y])
    window.bind_graph_document(document)
    window.show()

    def complete() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GraphTemplateDialog)
        try:
            assert not dialog.tables
            dialog.controls["y"].rows.setText("2:9")
            dialog.create_button.click()
            assert dialog.result_edit is None and "row range" in dialog.status.text()
            assert not document.current.graphs
            dialog.controls["y"].rows.clear()
            dialog.create_button.click()
            assert dialog.result_edit is not None, dialog.status.text()
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, complete)
    window.template_action.trigger()
    assert window.editor is not None and window.graph() is not None
    assert document.render_source().wave("root:time") is x
    window.undo_action.trigger()
    assert not document.current.graphs and document.render_source().waves == (x, y)

    path = tmp_path / "measurement.dat"
    path.write_bytes(b"[Header]\nINFO,TEST\n[Data]\nTime (s),Signal (V)\n1,50\n2,60\n3,70\n")

    def import_new_measurement() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GraphTemplateDialog)
        try:
            dialog.load_files([path])
            assert dialog.controls["y"].unit.text() == "V"
            dialog.create_button.click()
            assert dialog.result_edit is not None, dialog.status.text()
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, import_new_measurement)
    window.template_action.trigger()
    graph = window.graph()
    assert graph is not None
    result = document.render_source().wave(graph.traces[0].y_wave)
    assert result is not None
    np.testing.assert_array_equal(result.data, [50, 60, 70])
