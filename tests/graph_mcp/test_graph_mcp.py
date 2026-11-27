from __future__ import annotations

import json
import math
import runpy
import shutil
import sys
import zipfile
from pathlib import Path

import anyio
import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image
from pypdf import PdfReader

from materials_data_studio.graph_mcp import service
from materials_data_studio.graph_mcp.inputs import PlotError, Workspace, load_table
from materials_data_studio.graph_mcp.schema import Column, FigureRecipe, Source
from materials_data_studio.tools.graph_document import load_graph_document
from materials_data_studio.tools.graph_render import IgorMatplotlibRenderer

REPO = Path(__file__).resolve().parents[2]
BASELINE = Path(".test-tmp/graph-editor-baselines/solid-state-v2")
CIF = """data_NaCl
_symmetry_space_group_name_H-M 'F m -3 m'
_cell_length_a 5.6402
_cell_length_b 5.6402
_cell_length_c 5.6402
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na1 Na 0 0 0
Cl1 Cl 0.5 0.5 0.5
"""


@pytest.fixture(scope="module")
def baseline_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    workspace = tmp_path_factory.mktemp("synthetic_graph_inputs")
    generator = REPO / "docs/graph_editor_baselines/solid-state-v2/reproducibility/build_domain_baseline.py"
    suite = runpy.run_path(str(generator))
    required = {
        "d01_xrd_stacked", "d02_xrd_profile_residual", "d03_mpms_zfc_fc",
        "d07_ppms_low_t_cp", "d19_xrd_parent_comparison", "d20_xrd_temperature",
        "d21_xrd_pressure",
    }
    cases = suite["first_cases"]() + suite["additional_cases"]() + suite["xrd_condition_cases"]()
    for case in cases:
        if case.id in required:
            directory = workspace / BASELINE / "cases" / case.id
            suite["write_inputs"](case, directory)
            np.savez_compressed(directory / "independent_transform_reference.npz", **case.expected_waves)
    return workspace


def baseline_files(root: Path, baseline_workspace: Path, case: str) -> dict:
    inputs = baseline_workspace / BASELINE / "cases" / case / "inputs"
    sources = {}
    for file in inputs.glob("*.csv"):
        shutil.copyfile(file, root / file.name)
        sources[file.stem] = {"path": file.name}
    return sources


def column(source: str, index: int | str, unit: str) -> dict:
    return {"source": source, "column": index, "unit": unit}


def wave(document, path: str):
    item = document.render_source().wave(path)
    assert item is not None
    return np.asarray(item.data, dtype=float)


def render(document, graph: str) -> tuple[Figure, FigureCanvasAgg]:
    renderer = IgorMatplotlibRenderer()
    figure = Figure(figsize=renderer.export_size(document.graph(graph)), dpi=100)
    canvas = FigureCanvasAgg(figure)
    renderer.render(figure, document, graph)
    canvas.draw()
    return figure, canvas


def test_xrd_parent_cif_preserves_scan_data_and_aligned_plot(tmp_path: Path, baseline_workspace: Path) -> None:
    sources = baseline_files(tmp_path, baseline_workspace, "d19_xrd_parent_comparison")
    (tmp_path / "reference.cif").write_text(CIF, encoding="utf-8")
    recipe = FigureRecipe.model_validate(
        {
            "sources": {name: sources[name] for name in ("input", "parent_A_simulation")},
            "columns": {
                "angle": column("input", 0, "degree"),
                **{f"counts{i}": column("input", i + 1, "count") for i in range(3)},
                "peak_angles": column("parent_A_simulation", 0, "degree"),
                "peak_heights": column("parent_A_simulation", 1, "relative"),
            },
            "plot": {
                "kind": "xrd_stack",
                "angle_limits_deg": [10, 80],
                "normalization": "peak100",
                "offsets": [0, 120, 240],
                "scans": [
                    {"x": "angle", "y": f"counts{i}", "label": f"Annealed at {t} K"}
                    for i, t in enumerate((700, 800, 900))
                ],
                "references": [
                    {
                        "kind": "peaks",
                        "label": "Parent A",
                        "angles": "peak_angles",
                        "intensity": "peak_heights",
                    },
                    {
                        "kind": "cif",
                        "label": "NaCl reference",
                        "path": "reference.cif",
                        "wavelength_angstrom": 1.5406,
                    },
                ],
            },
        }
    )
    result = service.create_figure(
        Workspace(tmp_path),
        recipe,
        output_dir="stack",
        formats=["png", "svg", "pdf"],
        dpi=100,
        validate_only=False,
    )
    document = load_graph_document(tmp_path / result["files"]["document"])
    assert document.current.graphs[0].name == "figure"
    assert [item.graph for item in document.graph("figure").layout_items] == [
        "observed",
        "reference_1",
        "reference_2",
    ]
    observed = document.graph("observed")
    assert [t.offset[1] for t in observed.traces] == [0, 120, 240]
    assert len({t.color_igor for t in observed.traces}) == 3
    np.testing.assert_array_equal(
        wave(document, "root:counts0"),
        np.loadtxt(tmp_path / "input.csv", delimiter=",", skiprows=1)[:, 1],
    )
    assert np.max(wave(document, "root:MCP:scan_1_peak100")) == 100
    predicted = math.degrees(2 * math.asin(1.5406 * math.sqrt(3) / (2 * 5.6402)))
    assert np.min(np.abs(wave(document, "root:MCP:reference_2_2theta") - predicted)) < 0.002
    assert np.max(wave(document, "root:MCP:reference_2_height")) == 1
    assert all(not graph.drawings for graph in document.current.graphs)
    figure, canvas = render(document, "figure")
    main, first, last = figure.axes
    assert len(main.get_yticks()) == 0 and len(main.get_yticks(minor=True)) == 0
    assert [ax.get_ylabel() for ax in figure.axes] == ["Intensity / arb. units", "", ""]
    assert all(not ax.get_title() for ax in figure.axes)
    np.testing.assert_allclose(
        [tick for tick in last.get_xticks() if 10 <= tick <= 80], np.arange(10, 81, 10)
    )
    np.testing.assert_allclose(
        [tick for tick in last.get_xticks(minor=True) if 10 <= tick <= 80],
        [x for x in range(10, 81, 2) if x % 10],
    )
    for strip in (first, last):
        assert strip.bbox.x0 == pytest.approx(main.bbox.x0)
        assert strip.bbox.x1 == pytest.approx(main.bbox.x1)
    legend = next(a for a in main.artists if a.get_gid() == "annotation:legend")
    box = legend.get_window_extent(canvas.get_renderer())
    assert main.bbox.contains(box.x0, box.y0) and main.bbox.contains(box.x1, box.y1)
    assert box.y0 > max(
        main.transData.transform((10, line.get_ydata().max()))[1] for line in main.lines
    )
    assert set(p.suffix for p in (tmp_path / "stack").iterdir()) == {
        ".mdsg",
        ".pdf",
        ".svg",
        ".png",
        ".json",
    }


def test_rietveld_residual_reuses_intensity_scale(tmp_path: Path, baseline_workspace: Path) -> None:
    sources = baseline_files(tmp_path, baseline_workspace, "d02_xrd_profile_residual")
    recipe = FigureRecipe.model_validate(
        {
            "sources": sources,
            "columns": {
                "angle": column("input", 0, "degree"),
                "obs": column("input", 1, "count"),
                "calc": column("input", 2, "count"),
                **{f"phase{i}": column(f"phase_{i}_positions", 0, "degree") for i in range(1, 4)},
            },
            "plot": {
                "kind": "xrd_rietveld",
                "observed": {"x": "angle", "y": "obs"},
                "calculated": {"x": "angle", "y": "calc"},
                "phases": [
                    {"kind": "peaks", "angles": f"phase{i}", "label": f"Phase {i}"}
                    for i in range(1, 4)
                ],
            },
        }
    )
    name, document = service.build_figure(Workspace(tmp_path), recipe)
    graphs = document.graph(name).layout_items
    assert [layout.graph for layout in graphs] == [
        "profile",
        "reference_1",
        "reference_2",
        "reference_3",
        "residual",
    ]
    np.testing.assert_array_equal(
        wave(document, "root:MCP:observed_minus_calculated"),
        wave(document, "root:obs") - wave(document, "root:calc"),
    )
    figure, _ = render(document, name)
    top, *phases, bottom = figure.axes
    assert top.get_xlim() == bottom.get_xlim()
    assert top.transData.transform((10, 1))[1] - top.transData.transform((10, 0))[
        1
    ] == pytest.approx(
        bottom.transData.transform((10, 1))[1] - bottom.transData.transform((10, 0))[1]
    )
    for i, phase in enumerate(phases, 1):
        assert phase.get_xlim() == top.get_xlim()
        assert np.all(wave(document, f"root:MCP:reference_{i}_height") == 1)


@pytest.mark.parametrize(
    ("case", "unit", "label"),
    [
        ("d20_xrd_temperature", "K", "Temperature / K"),
        ("d21_xrd_pressure", "GPa", "Pressure / GPa"),
    ],
)
def test_xrd_map_orientation_and_color(
    tmp_path: Path, baseline_workspace: Path, case: str, unit: str, label: str,
) -> None:
    sources = baseline_files(tmp_path, baseline_workspace, case)
    recipe = FigureRecipe.model_validate(
        {
            "sources": sources,
            "columns": {
                "angle": column("angle_axis", 0, "degree"),
                "condition": column("condition_axis", 0, unit),
                "intensity": column("intensity_column_major", 0, "arb. units"),
            },
            "plot": {
                "kind": "xrd_map",
                "condition_label": label,
                "condition_unit": unit,
                "data": {
                    "kind": "flat_matrix",
                    "order": "scan_major",
                    "x": "angle",
                    "condition": "condition",
                    "intensity": "intensity",
                },
            },
        }
    )
    name, document = service.build_figure(Workspace(tmp_path), recipe)
    angle, condition = wave(document, "root:angle"), wave(document, "root:condition")
    values = wave(document, "root:intensity")
    np.testing.assert_array_equal(
        wave(document, "root:MCP:intensity_map"),
        values.reshape(len(angle), len(condition), order="F"),
    )
    figure, _ = render(document, name)
    main, colorbar = figure.axes
    assert main.get_xlabel() == "2θ (degree)" and main.get_ylabel() == label
    assert main.get_yticks().size and colorbar.get_ylabel() == "Intensity / arb. units"
    mesh = main.collections[0]
    low, high = mesh.cmap(0.0), mesh.cmap(1.0)
    assert low[2] > low[0] and high[0] > high[2]
    assert main.bbox.x1 < colorbar.bbox.x0 < figure.bbox.x1


def test_quantum_design_rasx_and_table_values_are_explicit(tmp_path: Path) -> None:
    root = Workspace(tmp_path)
    (tmp_path / "mpms.dat").write_text(
        "[Header]\nINFO, WEIGHT, 10\n\n[Data]\nTemperature (K),Long Moment (emu)\n10,0.25\n20,\n",
        encoding="utf-8",
    )
    table = load_table(root, Source(path="mpms.dat", kind="quantum_design"))
    assert table.describe()["metadata"]["weight_header_values"] == ["10"]
    assert table.preview([1], 1, 1) == [[""]]
    moment = Column(source="mpms", column=1, unit="emu")
    with pytest.raises(PlotError, match="Expected a number"):
        table.numeric(moment, "moment")
    np.testing.assert_array_equal(
        table.numeric(moment.model_copy(update={"rows": (0, 1)}), "moment"), [0.25]
    )
    np.testing.assert_array_equal(
        table.numeric(moment.model_copy(update={"missing": "gap"}), "moment"), [0.25, np.nan]
    )
    (tmp_path / "positions.txt").write_text(
        "# measured 2theta\n 10  24.2\n 20  14.2\n", encoding="utf-8"
    )
    assert load_table(root, Source(path="positions.txt", header=False)).describe()["rows"] == 2
    with zipfile.ZipFile(tmp_path / "scan.rasx", "w") as archive:
        archive.writestr("Data0/Profile0.txt", "10\t11.1\t0.1\n20\t42.1\t0.1\n")
    info = load_table(root, Source(path="scan.rasx", kind="rasx")).describe()
    assert info["rows"] == 2 and info["invalid_rows"] == 0
    assert info["columns"][0]["header"] == "two_theta"


@pytest.mark.parametrize(
    ("example", "case", "derived"),
    [
        ("mpms-zfc-fc", "d03_mpms_zfc_fc", {"chi_zfc": "d03_chi_zfc", "chi_fc": "d03_chi_fc"}),
        (
            "ppms-cp",
            "d07_ppms_low_t_cp",
            {
                "temperature_sq": "d07_T2",
                "cp_display": "d07_cp_over_t",
                "sigma_display": "d07_cp_over_t_error",
            },
        ),
    ],
)
def test_mpms_ppms_examples_match_independent_values(
    baseline_workspace: Path, example: str, case: str, derived: dict[str, str],
) -> None:
    request = json.loads(
        (REPO / f"docs/graph_mcp/examples/{example}.json").read_text(encoding="utf-8")
    )
    name, document = service.build_figure(
        Workspace(baseline_workspace), FigureRecipe.model_validate(request["recipe"])
    )
    reference_file = baseline_workspace / BASELINE / "cases" / case / "independent_transform_reference.npz"
    with np.load(reference_file) as expected:
        for actual, reference in derived.items():
            np.testing.assert_allclose(
                wave(document, f"root:{actual}"), expected[reference], rtol=1e-9
            )
    figure, _ = render(document, name)
    assert not figure.axes[0].get_title()
    if example == "ppms-cp":
        assert document.graph(name).traces[1].error_high == "root:sigma_display"
        assert figure.axes[0].containers


@pytest.mark.parametrize(
    "example", ["xrd-parent-comparison", "xrd-pressure-map", "xrd-stack", "mpms-zfc-fc", "ppms-cp"],
)
def test_documented_recipes_export_identical_plots(
    tmp_path: Path, baseline_workspace: Path, example: str,
) -> None:
    request = json.loads(
        (REPO / f"docs/graph_mcp/examples/{example}.json").read_text(encoding="utf-8")
    )
    recipe = FigureRecipe.model_validate(request["recipe"])
    if example in {"xrd-parent-comparison", "xrd-pressure-map"}:
        shutil.copytree(REPO / "docs/graph_examples/data", tmp_path / "data")
    else:
        for source in recipe.sources.values():
            target = tmp_path / source.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(baseline_workspace / source.path, target)
    workspace = Workspace(tmp_path)

    first, repeated = [
        service.create_figure(
            workspace, recipe, output_dir=directory, formats=["png"], dpi=100, validate_only=False,
        )
        for directory in (request["output_dir"], "repeated")
    ]
    assert first["graph"] == repeated["graph"]
    with (
        Image.open(tmp_path / first["files"]["png"]) as original,
        Image.open(tmp_path / repeated["files"]["png"]) as replay,
    ):
        pixels = np.asarray(original.convert("RGBA"))
        assert np.any(pixels != pixels[0, 0]), f"{example} exported a blank image"
        np.testing.assert_array_equal(pixels, np.asarray(replay.convert("RGBA")))


def xy_recipe(csv: str = "measurements.csv") -> dict:
    return {
        "sources": {"scan": {"path": csv}},
        "columns": {"x": column("scan", 0, "K"), "y": column("scan", 1, "J/K")},
        "plot": {
            "kind": "xy",
            "panels": [
                {
                    "name": "profile",
                    "x": {"label": "Temperature (K)"},
                    "y": {"label": "Heat capacity (J/K)"},
                    "traces": [{"name": "data", "x": "x", "y": "y", "label": "Observed"}],
                }
            ],
        },
    }


def test_xrd_long_table_preserves_nonuniform_coordinates(tmp_path: Path) -> None:
    (tmp_path / "pressure.csv").write_text(
        "angle,pressure,intensity\n40,5,50\n10,1,1\n40,1,3\n10,0,4\n40,0,7\n10,5,20\n",
        encoding="utf-8",
    )
    raw = {
        "sources": {"run": {"path": "pressure.csv"}},
        "columns": {
            "angle": column("run", 0, "degree"),
            "pressure": column("run", 1, "GPa"),
            "intensity": column("run", 2, "count"),
        },
        "plot": {
            "kind": "xrd_map",
            "condition_label": "Pressure / GPa",
            "condition_unit": "GPa",
            "data": {
                "kind": "long_table",
                "x": "angle",
                "condition": "pressure",
                "intensity": "intensity",
            },
        },
    }
    recipe = FigureRecipe.model_validate(raw)
    _, document = service.build_figure(Workspace(tmp_path), recipe)
    np.testing.assert_array_equal(
        wave(document, "root:MCP:intensity_map"), [[4, 1, 20], [7, 3, 50]]
    )
    np.testing.assert_array_equal(wave(document, "root:MCP:condition_edges"), [-0.5, 0.5, 3, 7])
    path = tmp_path / "pressure.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace("40,5,50", "39,5,50"), encoding="utf-8"
    )
    with pytest.raises(PlotError, match="common grid"):
        service.build_figure(Workspace(tmp_path), recipe)


def test_transport_pairing_and_unit_prefixes_are_checked(tmp_path: Path) -> None:
    (tmp_path / "transport.csv").write_text(
        "H,opposite_H,R,raw,opposite\n-2,2,11,0.4,0.8\n0,0,10,0.3,0.3\n2,-2,11,0.8,0.4\n",
        encoding="utf-8",
    )
    raw = xy_recipe()
    raw["sources"]["scan"]["path"] = "transport.csv"
    raw["columns"] = {
        name: column("scan", i, unit)
        for i, (name, unit) in enumerate(
            [
                ("field", "T"),
                ("opposite_field", "T"),
                ("resistance", "Ω"),
                ("raw", "mΩ cm"),
                ("opposite", "mΩ cm"),
            ]
        )
    }
    raw["transforms"] = [
        {"op": "magnetoresistance", "name": "mr", "wave": "resistance", "field": "field"},
        {
            "op": "hall_antisymmetrize",
            "name": "hall",
            "wave": "raw",
            "other": "opposite",
            "field": "field",
            "opposite_field": "opposite_field",
            "tolerance": 0,
        },
    ]
    raw["plot"]["panels"][0].update(
        {
            "x": {"label": "Magnetic field (T)"},
            "y": {"label": "MR (%)"},
            "traces": [{"name": "mr", "x": "field", "y": "mr"}],
        }
    )
    _, document = service.build_figure(Workspace(tmp_path), FigureRecipe.model_validate(raw))
    np.testing.assert_array_equal(wave(document, "root:mr"), [10, 0, 10])
    np.testing.assert_allclose(wave(document, "root:hall"), [-0.2, 0, 0.2])
    raw["transforms"][1]["opposite_field"] = "field"
    with pytest.raises(PlotError, match="row by row"):
        service.build_figure(Workspace(tmp_path), FigureRecipe.model_validate(raw))
    raw["columns"]["opposite"]["unit"] = "MΩ cm"
    with pytest.raises(PlotError, match="same unit"):
        service.build_figure(Workspace(tmp_path), FigureRecipe.model_validate(raw))


def test_failed_export_leaves_nothing_and_new_paths_cannot_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    (tmp_path / "measurements.csv").write_text("t,cp\n10,0.3\n20,0.5\n", encoding="utf-8")
    recipe = FigureRecipe.model_validate(xy_recipe())

    def error(*_args):
        raise OSError("export failed")

    monkeypatch.setattr(service, "save_graphics", error)
    with pytest.raises(OSError, match="export failed"):
        service.create_figure(
            workspace, recipe, output_dir="failed", formats=["png"], dpi=100, validate_only=False
        )
    assert {file.name for file in tmp_path.iterdir()} == {"measurements.csv"}
    with pytest.raises(PlotError, match="inside the configured workspace"):
        service.create_figure(
            workspace, recipe, output_dir="../escaped", formats=[], dpi=100, validate_only=False
        )


def test_stdio_figures_round_trip_and_review_pdf_titles(tmp_path: Path) -> None:
    (tmp_path / "measurements.csv").write_text("t,cp\n10,0.3\n20,0.5\n", encoding="utf-8")

    async def exercise() -> None:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "materials_data_studio.graph_mcp.server", "--workspace", str(tmp_path)],
        )
        async with (
            stdio_client(server) as (incoming, outgoing),
            ClientSession(incoming, outgoing) as session,
        ):
            await session.initialize()
            tool_list = await session.list_tools()
            assert {tool.name for tool in tool_list.tools} == {
                "inspect_input",
                "create_figure",
                "inspect_document",
                "create_review_pdf",
            }
            peek = await session.call_tool(
                "inspect_input", {"source": {"path": "measurements.csv"}}
            )
            assert not peek.isError and peek.structuredContent is not None
            assert peek.structuredContent["columns"][1]["header"] == "cp"
            invalid = xy_recipe()
            invalid["columns"]["x"].pop("unit")
            failure = await session.call_tool(
                "create_figure", {"recipe": invalid, "output_dir": "invalid"}
            )
            assert failure.isError and failure.structuredContent is not None
            assert failure.structuredContent["errors"][0]["field"] == "recipe.columns.x.unit"
            assert not (tmp_path / "invalid").exists()
            preview = await session.call_tool(
                "create_figure", {"recipe": xy_recipe(), "validate_only": True}
            )
            assert not preview.isError and preview.structuredContent is not None
            assert (
                preview.structuredContent["validated_only"]
                and "files" not in preview.structuredContent
            )
            request = {"recipe": xy_recipe(), "output_dir": "complete"}
            result = await session.call_tool("create_figure", request)
            assert not result.isError
            state = await session.call_tool(
                "inspect_document", {"path": "complete/figure.mdsg", "wave": "root:y"}
            )
            assert state.structuredContent is not None and state.structuredContent["values"] == [
                0.3,
                0.5,
            ]
            serialized = (tmp_path / "complete/manifest.json").read_text(encoding="utf-8")
            duplicate = await session.call_tool("create_figure", request)
            assert duplicate.isError and duplicate.structuredContent is not None
            assert duplicate.structuredContent["errors"][0]["code"] == "output_exists"
            assert (tmp_path / "complete/manifest.json").read_text(encoding="utf-8") == serialized
            assert (
                json.loads(serialized)["state"]["document_id"]
                == state.structuredContent["document_id"]
            )
            review = await session.call_tool(
                "create_review_pdf",
                {
                    "output_pdf": "review.pdf",
                    "pages": [
                        {"pdf": "complete/figure.pdf", "title": "PPMS heat capacity review"},
                    ],
                },
            )
            assert not review.isError, review

    anyio.run(exercise)
    written = PdfReader(tmp_path / "review.pdf")
    title = "PPMS heat capacity review"
    assert written.outline[0].title == title
    assert title in written.pages[0].extract_text()
    assert title not in PdfReader(tmp_path / "complete/figure.pdf").pages[0].extract_text()
