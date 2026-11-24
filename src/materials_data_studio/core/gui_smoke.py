"""Exercise the real Tools launch and native cursor paths in a built app."""

from __future__ import annotations

import faulthandler
import signal
import time
import traceback
from pathlib import Path
from typing import TextIO


def _exercise_tools(log: TextIO) -> int:
    import PySide6
    from PySide6.QtCore import QCoreApplication, Qt, QTimer, qVersion
    from PySide6.QtGui import QColorSpace, QCursor, QIcon, QImage, QPixmap
    from PySide6.QtWidgets import QApplication

    from materials_data_studio.config import APP_NAME, ORGANIZATION_NAME
    from materials_data_studio.core.resources import resource_root
    from materials_data_studio.tools.launcher import TOOLS
    from materials_data_studio.ui.main_window import MainWindow
    from materials_data_studio.ui.theme import style_sheet

    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
    instance = QApplication.instance()
    application = instance if isinstance(instance, QApplication) else QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(style_sheet("light"))
    application.setWindowIcon(QIcon(str(resource_root() / "resources/icons/materials-data-studio.ico")))
    log.write(f"PySide6={PySide6.__version__}\nQt={qVersion()}\nplatform={application.platformName()}\n")
    window = MainWindow()
    window.show()
    pending = iter(TOOLS)
    completed = False

    def advance() -> None:
        nonlocal completed
        try:
            descriptor = next(pending, None)
            if descriptor is None:
                for tool in window.tool_manager.open_windows:
                    tool.close()
                window.close()
                log.write("tools_launch_and_canvas_cursors=OK\n")
                completed = True
                application.exit(0)
                return
            log.write(f"Opening Tools > {descriptor.title}\n")
            before = set(window.tool_manager.open_windows)
            started = time.perf_counter()
            window.tool_manager.actions[descriptor.tool_id].trigger()
            log.write(f"tool_launch_seconds.{descriptor.tool_id}={time.perf_counter() - started:.3f}\n")
            opened = set(window.tool_manager.open_windows) - before
            if len(opened) != 1:
                raise RuntimeError(f"Tools action did not open a window: {descriptor.tool_id}")
            tool = opened.pop()
            if descriptor.tool_id == "pxp_viewer":
                from materials_data_studio.tools.graph_window import GraphEditorWindow

                if not isinstance(tool, GraphEditorWindow):
                    raise RuntimeError("Graph Editor action opened the wrong window")
                tool._discard_approved = True
                # Explicitly exercise the custom CGColorSpaceRef lifetime fixed
                # by QTBUG-147602, as well as Matplotlib's normal wait cursor.
                log.write("Rendering Graph Editor and setting custom-color-space cursor\n")
                image = QImage(24, 24, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.blue)
                image.setColorSpace(QColorSpace(QColorSpace.Primaries.DciP3D65,
                                               QColorSpace.TransferFunction.Gamma, 2.2))
                tool.canvas.setCursor(QCursor(QPixmap.fromImage(image)))
                for cursor in (Qt.CursorShape.WaitCursor, Qt.CursorShape.OpenHandCursor,
                               Qt.CursorShape.CrossCursor, Qt.CursorShape.ArrowCursor):
                    tool.canvas.setCursor(QCursor(cursor))
                tool.canvas.draw()
                tool.canvas.repaint()
                if tool.canvas.grab().isNull():
                    raise RuntimeError("Graph Editor canvas did not render")
            # Return to the native event loop between Tools windows so expose,
            # paint and cursor events run through the actual platform plugin.
            QTimer.singleShot(100, advance)
        except Exception:
            traceback.print_exc(file=log)
            application.exit(1)

    QTimer.singleShot(100, advance)
    exit_code = application.exec()
    return 0 if exit_code == 0 and completed else 1


def run_gui_smoke_test(report_path: Path) -> bool:
    """Keep progress and a Python stack even if native Cocoa raises SIGTRAP."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", buffering=1) as log:
        log.write("RUNNING\n")
        faulthandler.enable(file=log, all_threads=True)
        trap = getattr(signal, "SIGTRAP", None)
        if trap is not None:
            faulthandler.register(trap, file=log, all_threads=True, chain=True)
        try:
            success = _exercise_tools(log) == 0
        except Exception:
            traceback.print_exc(file=log)
            success = False
        finally:
            if trap is not None:
                faulthandler.unregister(trap)
            faulthandler.disable()
    details = report_path.read_text(encoding="utf-8").removeprefix("RUNNING\n")
    report_path.write_text(("OK\n" if success else "ERROR\n") + details, encoding="utf-8")
    return success
