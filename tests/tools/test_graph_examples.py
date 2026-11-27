"""Reproduce documented figures from their fixed synthetic inputs."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from matplotlib.figure import Figure

from materials_data_studio.tools.graph_document import (
    EditableGraphDocument,
    load_graph_document,
    save_graph_document,
)
from materials_data_studio.tools.graph_waves import empty_document, put_waves, validate_references

BASELINES = Path(__file__).resolve().parents[2] / "docs" / "graph_editor_baselines"


@pytest.fixture(scope="module")
def solid_state_suite() -> dict:
    script = BASELINES / "solid-state-v2" / "reproducibility" / "build_domain_baseline.py"
    return runpy.run_path(str(script))


def rendered_pixels(
    render: Callable[[EditableGraphDocument, str], Figure],
    document: EditableGraphDocument,
    name: str,
) -> np.ndarray:
    figure = render(document, name)
    try:
        assert any(axis.has_data() for axis in figure.axes), f"{name} rendered no data"
        return np.asarray(figure.canvas.buffer_rgba()).copy()
    finally:
        figure.clear()


def assert_same_figure(
    render: Callable[[EditableGraphDocument, str], Figure],
    name: str,
    first: EditableGraphDocument,
    repeated: EditableGraphDocument,
    restored: EditableGraphDocument,
) -> None:
    expected = rendered_pixels(render, first, name)
    for stage, document in [("fresh replay", repeated), ("save and reload", restored)]:
        np.testing.assert_array_equal(
            expected, rendered_pixels(render, document, name),
            err_msg=f"{name} changed pixels after {stage}",
        )


def test_solid_state_examples_reproduce_from_fixed_inputs(
    tmp_path: Path, solid_state_suite: dict,
) -> None:
    suite = solid_state_suite
    cases = suite["first_cases"]() + suite["additional_cases"]() + suite["xrd_condition_cases"]()
    assert cases
    for case in cases:
        directory = tmp_path / case.id
        bindings, _ = suite["write_inputs"](case, directory)
        task = {"id": case.id, "input_bindings": bindings}
        first, _ = suite["replay"](directory, task)
        repeated, _ = suite["replay"](directory, task)
        suite["verify_expected"](case, first)

        path = directory / "document.mdsg"
        save_graph_document(path, repeated)
        restored = load_graph_document(path)
        expected_state = suite["state_projection"](first)
        assert suite["state_projection"](repeated) == expected_state, case.id
        assert suite["state_projection"](restored) == expected_state, case.id
        assert_same_figure(suite["render"], case.main, first, repeated, restored)


def test_exploratory_examples_reproduce_from_fixed_seed(
    tmp_path: Path, solid_state_suite: dict,
) -> None:
    script = BASELINES / "exploratory-v1" / "reproducibility" / "build_suite.py"

    def build() -> tuple[dict, EditableGraphDocument]:
        suite = runpy.run_path(str(script))
        suite["make_suite"]()
        document = empty_document()
        document.current = put_waves(document, suite["WAVES"])
        document.current.graphs = tuple(suite["GRAPHS"])
        validate_references(document, document.current)
        return suite, document

    suite, first = build()
    _, repeated = build()
    path = tmp_path / "all_examples.mdsg"
    save_graph_document(path, repeated)
    restored = load_graph_document(path)
    project = solid_state_suite["state_projection"]
    assert project(first) == project(repeated) == project(restored)

    assert suite["CASES"]
    for case in suite["CASES"]:
        name = case["id"]
        assert_same_figure(suite["native_render"], name, first, repeated, restored)
