"""Cross-platform persistence, OS capability and application-event regressions."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFileOpenEvent

from materials_data_studio.app import DocumentOpenHandler
from materials_data_studio.core import recovery
from materials_data_studio.core.capabilities import procedure_execution_available
from materials_data_studio.core.models import Dataset, ModuleType
from materials_data_studio.core.processes import process_started_at
from materials_data_studio.core.project_state import ProjectState
from materials_data_studio.core.session import load_session, save_session


@pytest.mark.parametrize("source", [
    r"C:\lab\café data\sample.xy", r"\\server\lab\sample.xy",
    "/home/example/café data/sample.xy", "/Users/example/sample.xy", "scan:12.xy",
])
def test_foreign_source_paths_survive_repeated_session_saves(tmp_path: Path, source: str) -> None:
    state = ProjectState([Dataset("synthetic", ModuleType.XRD, {"x": np.array([1., 2.])},
                                  source_filename=source, source_bytes=b"1 3\n2 4\n")])
    for name in ("first.mdss", "second.mdss"):
        save_session(state, tmp_path / name)
        state = load_session(tmp_path / name)
        assert state.datasets[0].source_filename == source
        assert state.datasets[0].source_bytes == b"1 3\n2 4\n"
        np.testing.assert_array_equal(state.datasets[0].raw_data["x"], [1., 2.])


def test_native_document_events_queue_until_window_ready(qapp, qtbot, tmp_path: Path) -> None:
    calls: list[list[Path]] = []
    handler = DocumentOpenHandler(qapp)
    first, second = tmp_path / "one.mdss", tmp_path / "two.mdsg"
    try:
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(str(first)))
        assert calls == []
        handler.open_paths([first])  # Some launches provide both argv and an event.
        handler.bind(calls.append)
        qtbot.waitUntil(lambda: bool(calls))
        assert calls == [[first]]
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(str(second)))
        qtbot.waitUntil(lambda: len(calls) == 2)
        assert calls[1] == [second]
    finally:
        qapp.removeEventFilter(handler)
        handler.deleteLater()


def test_non_windows_procedures_are_disabled_before_snapshot_or_process(qtbot) -> None:
    if procedure_execution_available():
        pytest.skip("The Windows backend has native integration coverage")
    from materials_data_studio.tools.graph_window import GraphEditorWindow
    from materials_data_studio.tools.procedure_sandbox import SandboxUnavailable, launch

    window = GraphEditorWindow()
    qtbot.addWidget(window)
    try:
        workspace = window.command_workspace
        assert not workspace.run_all.isEnabled()
        assert not workspace.run_selection.isEnabled()
        assert workspace.convert_button.isEnabled()
        workspace.start('raise RuntimeError("must never execute")')
        assert workspace.work is None and workspace.process is None
        assert "unavailable" in workspace.output.toPlainText()
        with pytest.raises(SandboxUnavailable):
            launch(Path("nonexistent-sandbox"))
    finally:
        window._discard_approved = True
        window.close()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_diagnostic_redaction_covers_native_paths_and_preserves_urls(
    tmp_path: Path, newline: bytes
) -> None:
    raw = (
        b"Windows C:\\Users\\example\\lab file.dat\n"
        b"Linux /home/example/lab file.dat\n"
        b'macOS "/Users/example/lab file.dat"\n'
        b"https://example.org/help/manual\n"
    ).replace(b"\n", newline)
    (tmp_path / "materials-data-studio.log").write_bytes(raw)
    redacted = recovery.diagnostic_logs(log_directory=tmp_path)["materials-data-studio.log"].decode()
    assert "example/lab" not in redacted and "example\\lab" not in redacted
    assert redacted.count("<local path>") == 3
    assert "https://example.org/help/manual" in redacted
    assert recovery.diagnostic_logs(redact_paths=False, log_directory=tmp_path)["materials-data-studio.log"] == raw


def test_process_creation_time_and_reused_pid_recovery(tmp_path: Path, monkeypatch) -> None:
    started = process_started_at(os.getpid())
    assert started is not None and 0 < started <= time.time()
    assert process_started_at(-1) is None
    snapshot = tmp_path / "recovery-987654-deadbeef.mdss"
    snapshot.write_bytes(b"synthetic")
    monkeypatch.setattr(recovery, "recovery_directory", lambda: tmp_path)
    monkeypatch.setattr(recovery, "_process_is_running", lambda _pid: True)
    monkeypatch.setattr(recovery, "process_started_at", lambda _pid: snapshot.stat().st_mtime + 10)
    assert [item.path for item in recovery.find_recovery_candidates()] == [snapshot]


def test_case_sensitive_inputs_cannot_silently_replace_each_other(tmp_path: Path) -> None:
    from materials_data_studio.tools.igor_input_resources import read_input_files

    first, second = tmp_path / "Sample.dat", tmp_path / "sample.dat"
    first.write_text("1 2\n", encoding="utf-8")
    second.write_text("3 4\n", encoding="utf-8")
    if first.samefile(second):
        pytest.skip("Filesystem is case-insensitive")
    with pytest.raises(ValueError, match="differ only by letter case"):
        read_input_files([first, second], [])
