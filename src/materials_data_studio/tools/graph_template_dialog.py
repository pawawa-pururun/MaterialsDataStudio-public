"""Choose a figure recipe and bind it to data inside Graph Editor."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import cast

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from materials_data_studio.graph_mcp.inputs import MAX_CELLS
from materials_data_studio.tools.graph_document import EditableGraphDocument, GraphState
from materials_data_studio.tools.graph_templates import (
    TEMPLATE_NAMES,
    Binding,
    InputColumn,
    LoadedTable,
    Phase,
    Slot,
    TemplateKind,
    TemplateRequest,
    add_template,
    clean_label,
    heading_parts,
    read_template_table,
    template_slots,
)
from materials_data_studio.tools.pxp_model import PxpWave
from materials_data_studio.ui.localization import tr, translate_tree
from materials_data_studio.ui.tasks import blocking_task

DATA_FILES = "Measurement files (*.csv *.tsv *.txt *.dat *.xy *.rasx);;All files (*)"
DESCRIPTIONS: dict[TemplateKind, str] = {
    "xy": "Select X and Y. Blank values can appear as gaps.",
    "xrd_stack": "Scans are stacked from bottom to top in the listed order.",
    "xrd_map": "Use a long table with angle, condition and intensity columns on a common angle grid.",
    "xrd_rietveld": "Use supplied calculations and at least one phase. The template plots the residual.",
    "mpms_zfc_fc": "Enter the sample conditions. For separate sweeps, select the FC temperature and field too.",
    "ppms_cp": "Enter the sample conditions. Uncertainty and a supplied model are optional.",
}


@dataclass
class ColumnControls:
    slot: Slot
    column: QComboBox
    unit: QLineEdit
    rows: QLineEdit
    legend: QLineEdit | None = None
    edited: bool = False

    def mark_edited(self, *_args) -> None:
        self.edited = True


class PhaseControls(QWidget):
    def __init__(self, number: int, changed: Callable[[], None], parent: QWidget) -> None:
        super().__init__(parent)
        self.cif: Path | None = None
        self.label = QLineEdit(f"Phase {number}")
        self.label.setPlaceholderText(tr("Phase label"))
        self.wavelength = QLineEdit()
        self.wavelength.setPlaceholderText(tr("Wavelength (Å)"))
        self.wavelength.setMaximumWidth(120)
        self.wavelength.hide()
        self.choose = QPushButton(tr("Select CIF…"))
        self.clear = QPushButton(tr("Use peak columns"))
        self.clear.hide()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        for control in (self.label, self.choose, self.wavelength, self.clear):
            row.addWidget(control)
        self.choose.clicked.connect(self.choose_cif)
        self.clear.clicked.connect(lambda: self.set_cif(None))
        self.changed = changed

    def choose_cif(self) -> None:
        name, _filter = QFileDialog.getOpenFileName(self, tr("Select reference CIF"), "", "CIF (*.cif)")
        if name:
            self.set_cif(Path(name).resolve())

    def set_cif(self, path: Path | None) -> None:
        self.cif = path
        self.choose.setText(path.name if path else tr("Select CIF…"))
        self.wavelength.setVisible(path is not None)
        self.clear.setVisible(path is not None)
        self.changed()

    def value(self) -> Phase:
        wave = self.wavelength.text().strip()
        wavelength = None
        if self.cif is not None:
            try:
                wavelength = float(wave)
            except ValueError as error:
                raise ValueError(tr("Enter the measured X-ray wavelength in Å.")) from error
            if not np.isfinite(wavelength) or wavelength <= 0:
                raise ValueError(tr("Enter the measured X-ray wavelength in Å."))
        return Phase(self.label.text().strip(), self.cif, wavelength)


def _key(column: InputColumn) -> tuple[Path | str, int]:
    source = column.source
    return (source.id if isinstance(source, PxpWave) else source.path, column.index)


def _heading_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold().replace("θ", "theta")).strip("_")


def _match_column(slot: Slot, candidates: list[tuple[int, InputColumn]]) -> int:
    names = [(i, _heading_key(column.title)) for i, column in candidates]
    for hint in map(_heading_key, slot.hints):
        exact = [i for i, name in names if name == hint]
        matches = exact or [i for i, name in names if name.endswith("_" + hint)]
        if matches:
            return matches[0] if len(matches) == 1 else 0
    return 0


class GraphTemplateDialog(QDialog):
    def __init__(self, document: EditableGraphDocument, parent: QWidget) -> None:
        super().__init__(parent)
        self.document = document
        self.tables: list[LoadedTable] = []
        self.columns: list[InputColumn] = []
        self.controls: dict[str, ColumnControls] = {}
        self.phase_rows: list[PhaseControls] = []
        self.result_edit: tuple[str, GraphState] | None = None
        self.busy = False
        self.custom_scan_count = False
        self.setWindowTitle(tr("Create Graph from Template"))
        self.setAcceptDrops(True)
        self.resize(1010, 695)

        layout = QVBoxLayout(self)
        filters = QFormLayout()
        self.kind = QComboBox()
        for key, title in TEMPLATE_NAMES.items():
            self.kind.addItem(tr(title), key)
        filters.addRow(tr("Graph template"), self.kind)
        layout.addLayout(filters)

        inputs = QHBoxLayout()
        self.add_files = QPushButton(tr("Add data files…"))
        self.source = QComboBox()
        self.source.setMinimumContentsLength(16)
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.remove_file = QPushButton(tr("Remove file"))
        inputs.addWidget(self.add_files)
        inputs.addWidget(self.source, 1)
        inputs.addWidget(self.remove_file)
        layout.addLayout(inputs)

        self.preview = QTableWidget()
        self.preview.setProperty("mdsLiteralData", True)
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.setMaximumHeight(163)
        self.preview.horizontalHeader().setMaximumSectionSize(320)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.preview)
        self.preview_caption = QLabel()
        layout.addWidget(self.preview_caption)

        options = QHBoxLayout()
        self.scans_label, self.phases_label = QLabel(tr("Scans")), QLabel(tr("Reference phases"))
        self.scan_count, self.phase_count = QSpinBox(), QSpinBox()
        self.scan_count.setRange(1, 8)
        self.phase_count.setRange(0, 6)
        self.normalize = QCheckBox()
        self.mass_label = QLabel(tr("Sample mass (mg)"))
        self.molar_label = QLabel(tr("Molar mass (g/mol)"))
        self.mass, self.molar = QLineEdit(), QLineEdit()
        for widget in (self.scans_label, self.scan_count, self.phases_label, self.phase_count,
                       self.normalize, self.mass_label, self.mass, self.molar_label, self.molar):
            options.addWidget(widget)
        options.addStretch()
        layout.addLayout(options)

        self.phase_panel = QWidget()
        self.phase_layout = QVBoxLayout(self.phase_panel)
        self.phase_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.phase_panel)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        self.binding_table = QTableWidget(0, 5)
        self.binding_table.setHorizontalHeaderLabels([tr(text) for text in (
            "Role in figure", "Input column / wave", "Unit", "Data rows", "Legend label",
        )])
        self.binding_table.verticalHeader().hide()
        self.binding_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.binding_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.binding_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.binding_table.setColumnWidth(2, 110)
        self.binding_table.setColumnWidth(3, 95)
        self.binding_table.setColumnWidth(4, 140)
        rows_header = self.binding_table.horizontalHeaderItem(3)
        if rows_header is not None:
            rows_header.setToolTip(tr("Optional range of measurement rows, starting at 1, e.g. 1:50."))
        layout.addWidget(self.binding_table, 1)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(self.buttons)
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.create_button.setText(tr("Create Graph"))
        self.create_button.setProperty("primary", True)
        self.buttons.accepted.connect(self.make_graph)
        self.buttons.rejected.connect(self.reject)

        self.input_model = QStandardItemModel(self)
        self.source.currentIndexChanged.connect(self.show_preview)
        self.add_files.clicked.connect(self.choose_files)
        self.remove_file.clicked.connect(self.remove_selected_file)
        self.kind.currentIndexChanged.connect(self.change_template)
        self.scan_count.valueChanged.connect(self.count_changed)
        self.phase_count.valueChanged.connect(self.resize_phases)
        self.refresh_sources()
        self.change_template()
        translate_tree(self)

    def current_kind(self) -> TemplateKind:
        return cast(TemplateKind, self.kind.currentData())

    def choose_files(self) -> None:
        names, _filter = QFileDialog.getOpenFileNames(self, tr("Select measurement files"), "", DATA_FILES)
        if names:
            self.load_files([Path(name) for name in names])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not self.busy and event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if self.busy or not event.mimeData().hasUrls() or not all(url.isLocalFile() for url in event.mimeData().urls()):
            event.ignore()
            return
        event.acceptProposedAction()
        self.load_files([Path(url.toLocalFile()) for url in event.mimeData().urls()])

    def load_files(self, paths: list[Path]) -> None:
        if self.busy:
            return
        self.busy = True
        self.status.clear()
        self.create_button.setEnabled(False)
        stop = Event()
        existing = {item.path for item in self.tables}
        cells = sum(table.cells for table in self.tables)

        def read() -> list[LoadedTable]:
            total = cells
            items: list[LoadedTable] = []
            seen = set(existing)
            for path in paths:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                item = read_template_table(resolved, stop)
                total += item.cells
                if total > MAX_CELLS:
                    raise ValueError("Select fewer data files. The combined tables exceed eight million cells.")
                items.append(item)
                seen.add(resolved)
            return items

        try:
            self.tables.extend(blocking_task(self, tr("Read template data"), read, cancelled=stop))
            self.refresh_sources(select_last=True)
        except InterruptedError:
            pass
        except (OSError, RuntimeError, ValueError) as error:
            self.status.setText(str(error))
        finally:
            self.busy = False
            if isValid(self):
                self.create_button.setEnabled(bool(self.columns))

    def remove_selected_file(self) -> None:
        if self.busy:
            return
        source = self.source.currentData()
        if isinstance(source, LoadedTable):
            self.tables = [item for item in self.tables if item.path != source.path]
            self.refresh_sources()

    def refresh_sources(self, *, select_last: bool = False) -> None:
        self.source.blockSignals(True)
        self.source.clear()
        self.columns.clear()
        waves = [wave for wave in self.document.render_source().waves
                 if len(wave.shape) == 1 and np.dtype(wave.dtype).kind in "biuf"]
        if waves:
            self.source.addItem(tr("Waves in this document"))
            self.columns.extend(
                InputColumn(clean_label(wave.name), wave.data_units, wave) for wave in waves
            )
        for item in self.tables:
            self.source.addItem(item.path.name, item)
            for i, heading in enumerate(item.table.headings):
                name, unit = heading_parts(heading)
                if i == 0 and not unit:
                    unit = item.table.metadata.get("two_theta_unit", "")
                self.columns.append(InputColumn(name, unit, item, i))
        if not self.columns:
            self.source.addItem(tr("No data loaded"))
        if select_last:
            self.source.setCurrentIndex(self.source.count() - 1)
        self.source.blockSignals(False)
        self.show_preview()
        self.set_scan_defaults()
        self.rebuild_bindings(prefer_files=select_last)

    def show_preview(self, *_args) -> None:
        source = self.source.currentData()
        selected = isinstance(source, LoadedTable)
        self.remove_file.setEnabled(selected)
        self.preview.setVisible(selected)
        self.preview_caption.setVisible(selected)
        if not selected:
            return
        headings = source.table.headings[:12]
        values = source.table.preview(list(range(len(headings))), 0, 5)
        self.preview.clear()
        self.preview.setColumnCount(len(headings))
        self.preview.setRowCount(len(values))
        self.preview.setHorizontalHeaderLabels([name or str(i) for i, name in enumerate(headings, 1)])
        for row, cells in enumerate(values):
            for col, cell in enumerate(cells):
                self.preview.setItem(row, col, QTableWidgetItem("" if cell is None else str(cell)))
        self.preview_caption.setText(tr("{rows} data rows · {columns} columns").format(
            rows=source.count, columns=len(source.table.headings)
        ))

    def change_template(self, *_args) -> None:
        kind = self.current_kind()
        stacked, rietveld = kind == "xrd_stack", kind == "xrd_rietveld"
        for widget in (self.scans_label, self.scan_count):
            widget.setVisible(stacked)
        for widget in (self.phases_label, self.phase_count):
            widget.setVisible(stacked or rietveld)
        for widget in (self.mass_label, self.mass, self.molar_label, self.molar):
            widget.setVisible(kind in {"mpms_zfc_fc", "ppms_cp"})
        self.normalize.setVisible(stacked or kind == "xrd_map")
        self.normalize.setText(tr("Normalize each scan to 100" if stacked else "Normalize to global maximum"))
        self.normalize.setChecked(False)
        self.phase_count.blockSignals(True)
        self.phase_count.setRange(1 if rietveld else 0, 6 if rietveld else 5)
        self.phase_count.setValue(1 if rietveld else 0)
        self.phase_count.blockSignals(False)
        self.description.setText(tr(DESCRIPTIONS[kind]))
        self.status.clear()
        self.controls.clear()
        self.custom_scan_count = False
        self.set_scan_defaults()
        self.resize_phases()

    def uses_separate_scans(self) -> bool:
        return 1 < len(self.tables) <= 8 and all(len(item.table.headings) == 2 for item in self.tables)

    def set_scan_defaults(self) -> None:
        if self.current_kind() != "xrd_stack" or self.custom_scan_count:
            return
        count = 1
        if self.uses_separate_scans():
            count = len(self.tables)
        elif self.tables:
            titles = [_heading_key(column.title) for column in self.columns if column.source is self.tables[0]]
            # Numbered scan headers in the baseline table have an explicit
            # ordering. Other columns can be assigned by increasing Scans.
            for index in range(1, 9):
                if not any(re.search(rf"(?:^|_)(?:counts{index - 1}|scan_?{index})$", title) for title in titles):
                    break
                count = index
        self.scan_count.blockSignals(True)
        self.scan_count.setValue(count)
        self.scan_count.blockSignals(False)

    def count_changed(self, *_args) -> None:
        self.custom_scan_count = True
        self.rebuild_bindings()

    def resize_phases(self, *_args) -> None:
        count = self.phase_count.value()
        while len(self.phase_rows) > count:
            row = self.phase_rows.pop()
            self.phase_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        while len(self.phase_rows) < count:
            row = PhaseControls(len(self.phase_rows) + 1, self.rebuild_bindings, self.phase_panel)
            self.phase_rows.append(row)
            self.phase_layout.addWidget(row)
        self.phase_panel.setVisible(bool(count))
        self.rebuild_bindings()

    def suggested_index(self, slot: Slot) -> int:
        candidates = list(enumerate(self.columns, 1))
        if self.tables:
            candidates = [(i, source) for i, source in candidates if isinstance(source.source, LoadedTable)]
        if self.current_kind() == "xrd_stack" and self.uses_separate_scans():
            scan = re.fullmatch(r"(angle|scan)_([1-8])", slot.key)
            if slot.key == "angle" or scan is not None:
                index = int(scan[2]) - 1 if scan else 0
                if index < len(self.tables):
                    selected = [(i, column) for i, column in candidates if column.source is self.tables[index]]
                    is_angle = scan is None or scan[1] == "angle"
                    angle_slot, intensity_slot = template_slots("xrd_stack")
                    angle = _match_column(angle_slot, selected) or selected[0][0]
                    return angle if is_angle else _match_column(intensity_slot, [
                        (i, column) for i, column in selected if i != angle
                    ]) or next(i for i, _column in selected if i != angle)
        chosen = _match_column(slot, candidates)
        if chosen:
            return chosen
        if len(candidates) == 2:
            (first, x), (second, y) = candidates
            if self.current_kind() == "xy" or x.source is y.source:
                return {"x": first, "y": second, "angle": first, "scan_1": second}.get(slot.key, 0)
        return 0

    def rebuild_bindings(self, *, prefer_files: bool = False) -> None:
        retained = {}
        for key, row in self.controls.items():
            chosen = row.column.currentData()
            if isinstance(chosen, InputColumn):
                if prefer_files and not row.edited and isinstance(chosen.source, PxpWave):
                    continue
                retained[key] = (_key(chosen), row.unit.text(), row.rows.text(),
                                 row.legend.text() if row.legend else "", row.edited)
        self.controls.clear()
        self.binding_table.setRowCount(0)
        self.input_model.clear()
        self.input_model.appendRow(QStandardItem(tr("Select column or wave…")))
        indices = {}
        for i, choice in enumerate(self.columns, 1):
            item = QStandardItem(choice.display)
            item.setData(choice, Qt.ItemDataRole.UserRole)
            self.input_model.appendRow(item)
            indices[_key(choice)] = i
        kind = self.current_kind()
        slots = template_slots(kind, self.scan_count.value(),
                               tuple(i for i, phase in enumerate(self.phase_rows, 1) if phase.cif is None))
        self.binding_table.setColumnHidden(4, kind != "xrd_stack")
        self.binding_table.setRowCount(len(slots))
        for index, slot in enumerate(slots):
            combo = QComboBox()
            combo.setModel(self.input_model)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
            role = tr(slot.label)
            if not slot.required:
                role += " " + tr("(optional)")
            self.binding_table.setItem(index, 0, QTableWidgetItem(role))
            unit, rows = QLineEdit(), QLineEdit()
            unit.setPlaceholderText(tr("Unit"))
            rows.setPlaceholderText(tr("All / 1:50"))
            self.binding_table.setCellWidget(index, 1, combo)
            self.binding_table.setCellWidget(index, 2, unit)
            self.binding_table.setCellWidget(index, 3, rows)
            legend = None
            if slot.key.startswith("scan_"):
                legend = QLineEdit()
                legend.setPlaceholderText(tr("From input"))
                self.binding_table.setCellWidget(index, 4, legend)
            controls = ColumnControls(slot, combo, unit, rows, legend)
            self.controls[slot.key] = controls
            previous = retained.get(slot.key)
            if previous and previous[0] in indices:
                combo.setCurrentIndex(indices[previous[0]])
                unit.setText(previous[1])
                rows.setText(previous[2])
                if legend:
                    legend.setText(previous[3])
                controls.edited = previous[4]
            else:
                combo.setCurrentIndex(self.suggested_index(slot))
                self.set_default_unit(controls)
            combo.currentIndexChanged.connect(lambda _index, row=controls: self.set_default_unit(row))
            combo.activated.connect(controls.mark_edited)
            for field in (unit, rows, legend):
                if field is not None:
                    field.textEdited.connect(controls.mark_edited)
        self.create_button.setEnabled(bool(self.columns) and not self.busy)

    def set_default_unit(self, controls: ColumnControls) -> None:
        # Rebuilding the shared model can notify combos pending deletion.
        if self.controls.get(controls.slot.key) is not controls:
            return
        chosen = controls.column.currentData()
        if not isinstance(chosen, InputColumn):
            controls.unit.clear()
            return
        unit = chosen.unit or controls.slot.unit
        if not unit and self.current_kind() == "xy":
            unit = self.controls["y"].unit.text() if controls.slot.key == "sigma" else "1"
        controls.unit.setText(unit)

    def request(self) -> TemplateRequest:
        bindings: dict[str, Binding] = {}
        labels: list[str] = []
        for key, row in self.controls.items():
            chosen = row.column.currentData()
            if not isinstance(chosen, InputColumn):
                if row.slot.required:
                    raise ValueError(tr("Select a column or wave for {role}.").format(role=tr(row.slot.label)))
                continue
            unit = row.unit.text().strip()
            if not unit:
                raise ValueError(tr("Enter a unit for {role}. Use 1 for dimensionless values.").format(role=tr(row.slot.label)))
            rows = None
            if span := row.rows.text().strip():
                match = re.fullmatch(r"([1-9][0-9]{0,8})\s*:\s*([1-9][0-9]{0,8})", span)
                if not match or int(match[1]) > int(match[2]):
                    raise ValueError(tr("Use a row range such as 1:50 for {role}.").format(role=tr(row.slot.label)))
                rows = int(match[1]) - 1, int(match[2])
            bindings[key] = Binding(chosen, unit, rows)
            if row.legend is not None:
                title = chosen.title
                if not title and isinstance(chosen.source, LoadedTable):
                    title = chosen.source.path.stem
                if title in labels and isinstance(chosen.source, LoadedTable):
                    title = chosen.source.path.stem
                if title in labels or not title:
                    title = f"Scan {len(labels) + 1}"
                labels.append(row.legend.text().strip() or clean_label(title))
        mass = molar = None
        if self.current_kind() in {"mpms_zfc_fc", "ppms_cp"}:
            try:
                mass, molar = float(self.mass.text()), float(self.molar.text())
            except ValueError as error:
                raise ValueError(tr("Enter the sample mass in mg and molar mass in g/mol.")) from error
            if not (np.isfinite(mass) and mass > 0 and np.isfinite(molar) and molar > 0):
                raise ValueError(tr("Enter positive sample and molar masses."))
        return TemplateRequest(self.current_kind(), bindings, tuple(labels),
                               tuple(phase.value() for phase in self.phase_rows),
                               self.normalize.isChecked(), mass, molar)

    def make_graph(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.status.clear()
        self.create_button.setEnabled(False)
        try:
            request = self.request()
            stop = Event()
            self.result_edit = blocking_task(self, tr("Create template figure"),
                                             lambda: add_template(self.document, request, stop), cancelled=stop)
        except InterruptedError:
            return
        except (ValueError, RuntimeError) as error:
            self.status.setText(tr(str(error)))
            return
        finally:
            self.busy = False
            if isValid(self):
                self.create_button.setEnabled(bool(self.columns))
        self.accept()
