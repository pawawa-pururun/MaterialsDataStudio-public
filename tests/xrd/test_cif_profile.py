"""Verify profile corrections and their live XRD controls with synthetic data."""

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox, QTabWidget

from materials_data_studio.core.models import Dataset, ModuleType
from materials_data_studio.core.project_state import ProjectState
from materials_data_studio.modules.xrd.cif_backend import CifDocument
from materials_data_studio.modules.xrd.cif_editor import CifEditorDialog
from materials_data_studio.modules.xrd.cif_profile import apply_cif_profile
from materials_data_studio.modules.xrd.simulation import SimulatedPattern
from materials_data_studio.modules.xrd.widget import XrdWidget

_CIF = """data_profile
_symmetry_space_group_name_H-M 'P 1'
_cell_length_a 5
_cell_length_b 6
_cell_length_c 7
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Na1 Na 0 0 0 0.75
"""


def test_profile_size_strain_and_orientation():
    sticks = SimulatedPattern(
        np.array([20., 40., 65.]), np.array([100., 60., 30.]),
        hkl_labels=["(1 0 0)", "(0 0 1)", "(2 1 -3 0)"],
    )
    settings = {"fwhm_deg": None, "preferred_orientation": True, "orientation_alignment": 0.7}
    cell = (5., 6., 7., 90., 90., 90.)
    plates = apply_cif_profile(sticks, settings, cell=cell)
    needles = apply_cif_profile(sticks, {**settings, "orientation_geometry": "needles"}, cell=cell)
    assert plates.intensity[1] > sticks.intensity[1] > needles.intensity[1]
    assert plates.intensity[0] < sticks.intensity[0] < needles.intensity[0]
    assert apply_cif_profile(sticks, {**settings, "preferred_orientation": False}, cell=cell) is sticks
    sigma = apply_cif_profile(sticks, {
        "fwhm_deg": 0.08, "particle_size_nm": 20, "isotropic_strain_percent": 0.1,
        "radiation": "Cu Kα1/2",
    })
    assert sigma.profile_x is not None and sigma.profile_y is not None
    assert np.all(sigma.profile_y >= 0.)
    assert sigma.profile_y[np.argmin(abs(sigma.profile_x - 20.2))] > 35.
    np.testing.assert_array_equal(sticks.intensity, [100, 60, 30])


def test_xrd_profile_controls_update_in_place_and_cursor_guides(qtbot, monkeypatch):
    state = ProjectState()
    dataset = Dataset("Synthetic", ModuleType.XRD, {
        "x": np.array([20., 40.]), "intensity": np.array([100., 60.]),
    }, metadata={
        "source_axis": "two_theta", "edited_cif": _CIF, "is_simulated_phase": True,
        "stick_two_theta_deg": [20., 40.], "stick_intensity": [100., 60.],
        "stick_hkl_labels": ["(1 0 0)", "(0 0 1)"], "stick_d_spacing_a": [5., 7.],
    })
    state.add_dataset(dataset)
    widget = XrdWidget(state)
    qtbot.addWidget(widget)
    widget.refresh()
    widget._load_selected(dataset)
    assert widget.lattice_fields["a"].singleStep() == 0.01
    assert widget.lattice_fields["alpha"].singleStep() == 0.1
    assert widget.lattice_relative_scale.singleStep() == 0.1
    assert not widget.orientation_geometry.isEnabled()
    monkeypatch.setattr(widget, "_queue_cif", lambda *args: pytest.fail("Profile must reuse reflections"))
    widget.particle_size.setValue(25.)
    assert len(dataset.processed_data["x"]) > 2
    baseline = dataset.processed_data["intensity"].copy()
    widget.orientation_enabled.setChecked(True)
    assert widget.orientation_geometry.isEnabled()
    widget.orientation_alignment.setValue(0.7)
    assert not np.allclose(baseline, dataset.processed_data["intensity"])
    widget.orientation_enabled.setChecked(False)
    np.testing.assert_allclose(dataset.processed_data["intensity"], baseline)
    header, lines = widget._cursor_readout(40., True)
    assert "2θ = 40°" in header and "d = 2.25" in header
    assert lines[0][0] == "Cu Kα2" and lines[0][1] > 40
    assert lines[1][0] == "Cu Kβ" and lines[1][1] < 40


def test_partial_occupancy_accepts_without_modal_warning(qtbot, monkeypatch):
    document = CifDocument(Path("synthetic.cif"), _CIF, _CIF)
    editor = CifEditorDialog(document)
    qtbot.addWidget(editor)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail("Unexpected occupancy dialog"))
    assert editor.site_table.rowCount() == 0
    editor.findChild(QTabWidget).setCurrentIndex(1)
    assert editor.site_table.rowCount() == 1
    editor._accept_edits()
    assert editor.result() == CifEditorDialog.DialogCode.Accepted
    assert "0.75" in document.edited_text
