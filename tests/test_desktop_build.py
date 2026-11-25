"""Native bundle gates must reject stale Qt and use the real Cocoa plugin."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6 import QtCore
from scripts import build_desktop


@pytest.mark.parametrize("version", ["6.8.3", "6.11.1"])
def test_build_rejects_qt_without_colorspace_fix(monkeypatch, version: str) -> None:
    monkeypatch.setattr(QtCore, "qVersion", lambda: version)
    with pytest.raises(RuntimeError, match=r"Qt >= 6\.11\.2.*uv sync --frozen"):
        build_desktop.check_qt_runtime()


def test_build_reports_fixed_qt_runtime(capsys) -> None:
    build_desktop.check_qt_runtime()
    assert f"Qt {QtCore.qVersion()}" in capsys.readouterr().out


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_smoke_uses_cocoa_only_for_mac(monkeypatch, tmp_path: Path, platform: str) -> None:
    calls = []

    def run(arguments, *, env, timeout):
        calls.append((arguments, env, timeout))
        Path(arguments[-1]).write_text("OK\n", encoding="utf-8")

    monkeypatch.setattr(build_desktop, "run", run)
    monkeypatch.setattr(build_desktop.sys, "platform", platform)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    build_desktop.run_smoke_tests(tmp_path / "MaterialsDataStudio", tmp_path)
    assert [call[0][1] for call in calls] == (
        ["--packaging-smoke-test", "--native-gui-smoke-test"]
        if platform == "darwin" else ["--packaging-smoke-test"]
    )
    assert [call[1]["QT_QPA_PLATFORM"] for call in calls] == (
        ["offscreen", "cocoa"] if platform == "darwin" else ["offscreen"]
    )
    for _arguments, env, timeout in calls:
        assert Path(env["MDS_SETTINGS_DIRECTORY"]).is_relative_to(tmp_path)
        assert Path(env["MDS_RECOVERY_DIRECTORY"]).is_relative_to(tmp_path)
        assert Path(env["MPLCONFIGDIR"]).is_relative_to(tmp_path)
        assert env["MDS_MATPLOTLIB_CACHE_DIRECTORY"] == env["MPLCONFIGDIR"]
        assert timeout == 300


def test_native_crash_stops_build_and_prints_progress(monkeypatch, tmp_path: Path, capsys) -> None:
    def run(arguments, *, env, timeout):
        report = Path(arguments[-1])
        if arguments[1] == "--native-gui-smoke-test":
            report.write_text("RUNNING\nOpening Graph Editor\n", encoding="utf-8")
            raise subprocess.CalledProcessError(-5, arguments)
        report.write_text("OK\n", encoding="utf-8")

    monkeypatch.setattr(build_desktop, "run", run)
    monkeypatch.setattr(build_desktop.sys, "platform", "darwin")
    with pytest.raises(subprocess.CalledProcessError):
        build_desktop.run_smoke_tests(tmp_path / "MaterialsDataStudio", tmp_path)
    assert "Opening Graph Editor" in capsys.readouterr().err


@pytest.mark.parametrize("ci,option,expected", [
    (False, None, True), (True, None, False),
    (False, "--no-prepare-user-cache", False), (True, "--prepare-user-cache", True),
])
def test_only_local_builds_prepare_user_cache_by_default(monkeypatch, tmp_path: Path, ci, option, expected):
    seen = []
    monkeypatch.setenv("CI", "true" if ci else "")
    monkeypatch.setattr(build_desktop, "build", lambda *args, **kwargs: seen.append(kwargs))
    monkeypatch.setattr(build_desktop.sys, "argv", ["build_desktop.py", *([option] if option else [])])
    build_desktop.main()
    assert seen[0]["warm_user_cache"] is expected


def test_user_cache_is_prepared_by_the_built_executable(monkeypatch, tmp_path: Path):
    seen = []

    def run(arguments, *, timeout):
        seen.append(arguments)
        Path(arguments[-1]).write_text("OK\ncache_directory=prepared\n", encoding="utf-8")

    monkeypatch.setattr(build_desktop, "run", run)
    executable = tmp_path / "MDS.app/Contents/MacOS/MaterialsDataStudio"
    assert build_desktop.prepare_user_cache(executable, tmp_path)
    assert seen[0][:2] == [str(executable), "--prepare-runtime-cache"]


def test_user_cache_preparation_failure_is_visible(monkeypatch, tmp_path: Path, capsys):
    def run(arguments, *, timeout):
        Path(arguments[-1]).write_text("ERROR\nA persistent user font cache is unavailable\n", encoding="utf-8")
        raise subprocess.CalledProcessError(1, arguments)

    monkeypatch.setattr(build_desktop, "run", run)
    assert not build_desktop.prepare_user_cache(tmp_path / "MaterialsDataStudio", tmp_path)
    assert "persistent user font cache is unavailable" in capsys.readouterr().err
