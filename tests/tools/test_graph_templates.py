"""Template data binding, scientific transforms and structurally safe graph insertion."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from materials_data_studio.core.packaging_smoke import _SMOKE_CIF
from materials_data_studio.tools.graph_document import load_graph_document, save_graph_document
from materials_data_studio.tools.graph_templates import (
    Binding,
    InputColumn,
    Phase,
    TemplateRequest,
    add_template,
    read_template_table,
)
from materials_data_studio.tools.graph_waves import empty_document, make_wave


def binding(name, values, unit):
    return Binding(InputColumn(name, unit, make_wave(name, values)), unit)


def test_stacks_keep_source_scans_and_use_common_mcp_styling():
    document = empty_document()
    request = TemplateRequest("xrd_stack", {
        "angle": binding("angle", [10, 20, 30], "degree"),
        "scan_1": binding("counts_a", [20, 40, 35], "count"),
        "scan_2": binding("counts_b", [30, 60, 45], "count"),
    }, scan_labels=("Condition A", "Condition B"), normalize=True)
    name, after = add_template(document, request, Event())
    result = replace(document, current=after)
    graph = result.graph(name)
    waves = result.render_source()
    assert graph.axes[0].style.manual_ticks == (0, 10, 0, 0)
    assert graph.axes[1].style.tick_count == 0
    assert graph.traces[1].offset[1] > graph.traces[0].offset[1]
    for trace in graph.traces:
        wave = waves.wave(trace.y_wave)
        assert wave is not None and max(wave.data) == 100
    raw = waves.wave("root:Templates:Figure_1:scan_1")
    assert raw is not None
    np.testing.assert_array_equal(raw.data, [20, 40, 35])
    assert not document.current.graphs and not document.render_source().waves


def test_long_table_condition_map_keeps_the_input_grid(tmp_path: Path):
    path = tmp_path / "condition-map.tsv"
    path.write_bytes(
        b"2theta (deg)\tTemperature (K)\tIntensity (count)\r\n"
        b"10\t200\t1\r\n20\t200\t2\r\n10\t250\t3\r\n20\t250\t4\r\n"
    )
    source = read_template_table(path, Event())
    document = empty_document()
    bindings = {
        name: Binding(InputColumn(title, unit, source, index), unit)
        for index, (name, title, unit) in enumerate((
            ("angle", "2theta", "deg"), ("condition", "Temperature", "K"), ("intensity", "Intensity", "count"),
        ))
    }
    name, state = add_template(document, TemplateRequest("xrd_map", bindings), Event())
    result = replace(document, current=state)
    graph = result.graph(name)
    assert graph.axes[1].label_raw == "Temperature (K)"
    image = graph.images[0]
    assert image.color_table == "ColdWarm" and image.colorbar_visible
    wave = result.render_source().wave(image.wave)
    assert wave is not None
    np.testing.assert_array_equal(wave.data, [[1, 3], [2, 4]])


def test_xrd_reference_cif_uses_selected_file_and_wavelength(tmp_path: Path):
    path = tmp_path / "synthetic.cif"
    path.write_text(_SMOKE_CIF, encoding="utf-8")
    document = empty_document()
    phase = Phase("Synthetic phase", path)
    request = TemplateRequest("xrd_stack", {
        "angle": binding("angle", [10, 40, 80], "deg"),
        "scan_1": binding("counts", [20, 40, 30], "count"),
    }, scan_labels=("Measurement",), phases=(phase,))
    with pytest.raises(ValueError, match="wavelength"):
        add_template(document, request, Event())
    request = replace(request, phases=(replace(phase, wavelength=1.540598),))
    name, document.current = add_template(document, request, Event())
    assert document.graph(name).layout_items[-1].graph == "reference_1"
    trace = document.graph("reference_1").traces[0]
    assert trace.x_wave is not None
    peaks = document.render_source().wave(trace.x_wave)
    assert peaks is not None
    angles = np.asarray(peaks.data, dtype=float)
    assert np.all((angles > 10) & (angles < 80))
    assert path.name in peaks.wave_note and str(path.parent) not in peaks.wave_note


def test_rietveld_layout_and_residual_roundtrip_when_added_twice(tmp_path: Path):
    request = TemplateRequest("xrd_rietveld", {
        "angle": binding("angle", [10, 20, 30], "deg"),
        "observed": binding("observed", [20, 60, 35], "count"),
        "calculated": binding("calculated", [18, 65, 35], "count"),
        "phase_1_angle": binding("bragg", [15, 25], "deg"),
    }, phases=(Phase("Synthetic phase"),))
    document = empty_document()
    first, document.current = add_template(document, request, Event())
    before = document.current
    name, after = add_template(document, request, Event())
    assert name != first and before is document.current
    document.current = after
    path = tmp_path / "profiles.mdsg"
    save_graph_document(path, document)
    restored = load_graph_document(path)
    assert len(restored.current.graphs) == 8
    layout = restored.graph(name)
    assert [item.graph for item in layout.layout_items] == ["profile_2", "reference_1_2", "residual_2"]
    trace = restored.graph("residual_2").traces[0]
    values = restored.render_source().wave(trace.y_wave)
    assert values is not None
    np.testing.assert_array_equal(values.data, [2, -5, 0])


def test_mpms_uses_confirmed_masses_and_independent_fc_coordinates():
    document = empty_document()
    request = TemplateRequest("mpms_zfc_fc", {
        "temperature": binding("temperature", [5, 10], "K"),
        "field": binding("field", [1000, 1000], "Oe"),
        "zfc": binding("zfc", [.02, .03], "emu"),
        "fc_temperature": binding("fc_temperature", [5, 10, 15], "K"),
        "fc_field": binding("fc_field", [500, 500, 500], "Oe"),
        "fc": binding("fc", [.01, .02, .03], "emu"),
    })
    with pytest.raises(ValueError, match="sample mass"):
        add_template(document, request, Event())
    name, state = add_template(document, replace(request, sample_mass_mg=10, molar_mass_g_mol=100), Event())
    document.current = state
    catalog = document.render_source()
    traces = document.graph(name).traces
    assert len(traces) == 2
    zfc, fc = [catalog.wave(trace.y_wave) for trace in traces]
    assert zfc is not None and fc is not None
    np.testing.assert_allclose(zfc.data, [.2, .3])
    np.testing.assert_allclose(fc.data, [.2, .4, .6])


def test_ppms_squares_temperature_and_applies_same_conversion_to_errors():
    document = empty_document()
    request = TemplateRequest("ppms_cp", {
        "temperature": binding("t", [2, 4], "K"),
        "capacity": binding("capacity", [2, 8], "µJ/K"),
        "sigma": binding("sigma", [.2, .8], "µJ/K"),
        "model": binding("model", [10, 20], "mJ/(mol K²)"),
    }, sample_mass_mg=10, molar_mass_g_mol=100)
    name, document.current = add_template(document, request, Event())
    traces = document.graph(name).traces
    assert len(traces) == 2
    observed = traces[1]
    assert observed.x_wave is not None and observed.error_high is not None
    catalog = document.render_source()
    x, y, error = (
        catalog.wave(observed.x_wave),
        catalog.wave(observed.y_wave),
        catalog.wave(observed.error_high),
    )
    assert x is not None and y is not None and error is not None
    np.testing.assert_allclose(x.data, [4, 16])
    np.testing.assert_allclose(y.data, [10, 20])
    np.testing.assert_allclose(error.data, [1, 2])
    assert y.data_units == error.data_units == "mJ/(mol K²)"
