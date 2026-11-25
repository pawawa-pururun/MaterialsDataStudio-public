"""Build named Graph Editor waves and retain units and derivation provenance."""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from numpy.typing import NDArray

from materials_data_studio.graph_mcp.inputs import (
    MAX_CELLS,
    Array,
    InputFiles,
    PlotError,
    finite,
    load_table,
    paired,
    unit_key,
)
from materials_data_studio.graph_mcp.schema import (
    Antisymmetrize,
    Binary,
    FigureRecipe,
    Log,
    Magnetoresistance,
    MolarCp,
    MolarSusceptibility,
    Power,
    Resistivity,
    Scale,
    Transform,
)
from materials_data_studio.modules.mpms.mt_analysis import calculate_susceptibility
from materials_data_studio.modules.ppms.heat_capacity import convert_to_molar_heat_capacity
from materials_data_studio.modules.ppms.resistivity import (
    geometry_factor,
    resistance_to_resistivity,
)
from materials_data_studio.tools.graph_waves import make_wave
from materials_data_studio.tools.pxp_model import PxpWave

_BINARY = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "divide": operator.truediv,
}


@dataclass
class Data:
    waves: dict[str, PxpWave] = field(default_factory=dict)
    values_count: int = 0
    folder: str = ""

    def store(self, name: str, values: NDArray[Any], unit: str, note: Any = None) -> str:
        if name in self.waves:
            raise PlotError("duplicate_wave", name, "Wave identifiers must be unique.")
        self.values_count += values.size
        if self.values_count > MAX_CELLS:
            raise PlotError(
                "data_too_large", name, "The figure exceeds eight million stored values."
            )
        path = f"{self.folder}:{name.removeprefix('root:')}" if self.folder else name
        wave = make_wave(path, values)
        self.waves[name] = replace(
            wave,
            data_units=unit,
            wave_note=json.dumps(note, ensure_ascii=False) if note is not None else "",
        )
        return wave.igor_path

    def wave(self, name: str) -> PxpWave:
        if name not in self.waves:
            raise PlotError(
                "unknown_wave",
                name,
                "Select an existing column or a preceding transform by its identifier.",
            )
        return self.waves[name]

    def numeric(self, name: str) -> Array:
        return np.asarray(self.wave(name).data, dtype=float)

    def unit(self, name: str) -> str:
        return self.wave(name).data_units

    def same_units(self, first: str, second: str, field_name: str) -> None:
        if unit_key(self.unit(first)) != unit_key(self.unit(second)):
            raise PlotError(
                "units_mismatch", field_name, f"{first} and {second} must use the same unit."
            )

    def require_unit(self, name: str, accepted: set[str], label: str) -> None:
        if unit_key(self.unit(name)) not in accepted:
            raise PlotError(
                "units_mismatch", name, f"Convert this wave to {label} before using it here."
            )


def load_data(workspace: InputFiles, recipe: FigureRecipe) -> Data:
    unknown = [
        (name, column.source)
        for name, column in recipe.columns.items()
        if column.source not in recipe.sources
    ]
    if unknown:
        name, source = unknown[0]
        raise PlotError(
            "unknown_source", f"columns.{name}.source", f"Source {source!r} is missing."
        )
    data = Data()
    for source_name, source in recipe.sources.items():
        bindings = [
            (name, binding)
            for name, binding in recipe.columns.items()
            if binding.source == source_name
        ]
        if not bindings:
            continue
        table = load_table(workspace, source)
        for name, binding in bindings:
            data.store(
                name,
                table.numeric(binding, name),
                binding.unit,
                {
                    "path": source.path,
                    "kind": source.kind,
                    "column": binding.column,
                    "first_data_record": table.first_record,
                    "missing": binding.missing,
                    "rows": binding.rows,
                },
            )
    for transform in recipe.transforms:
        derive(data, transform)
    return data


def derive(data: Data, transform: Transform) -> None:
    raw = data.numeric(transform.wave)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        result, unit, required = _compute(data, transform, raw)
    # Missing values already declared as gaps may propagate. A divide by zero
    # or an out-of-domain log/power on a supplied point is a failed request.
    if np.isinf(result).any() or not np.isfinite(result[required]).all():
        raise PlotError(
            "invalid_transform",
            transform.name,
            "The operation is undefined or overflowed at a measured point.",
        )
    result = np.where(required, result, np.nan)
    data.store(transform.name, result, unit, transform.model_dump(mode="json"))


def _compute(
    data: Data,
    transform: Transform,
    raw: Array,
) -> tuple[Array, str, NDArray[np.bool_]]:
    valid = np.isfinite(raw)
    if isinstance(transform, Scale):
        return raw * transform.factor + transform.offset, transform.unit, valid
    if isinstance(transform, Power):
        return raw**transform.exponent, transform.unit, valid
    if isinstance(transform, Log):
        return np.log(raw / transform.reference), "1", valid
    if isinstance(transform, Binary):
        other = data.numeric(transform.other)
        paired(raw, other, transform.name)
        if transform.op in {"add", "subtract"}:
            data.same_units(transform.wave, transform.other, transform.name)
            if unit_key(transform.unit) != unit_key(data.unit(transform.wave)):
                raise PlotError(
                    "units_mismatch",
                    transform.name,
                    "Addition and subtraction retain the inputs' unit.",
                )
        return _BINARY[transform.op](raw, other), transform.unit, valid & np.isfinite(other)
    if isinstance(transform, Resistivity):
        data.require_unit(transform.wave, {"ohm"}, "Ω")
        factor = geometry_factor(
            "width_thickness_length",
            width_cm=transform.width_cm,
            thickness_cm=transform.thickness_cm,
            length_cm=transform.voltage_spacing_cm,
        )
        return resistance_to_resistivity(raw, factor), "ohm cm", valid
    if isinstance(transform, MolarCp):
        data.require_unit(transform.wave, {"uJ/K", "uJK^-1", "uJK−1", "uJK⁻¹", "uj/k"}, "µJ/K")
        converted, _ = convert_to_molar_heat_capacity(
            raw,
            raw,
            sample_mass_mg=transform.sample_mass_mg,
            molar_mass_g_mol=transform.molar_mass_g_mol,
        )
        return converted, "J/(mol K)", valid
    field_values = data.numeric(transform.field)
    paired(raw, field_values, transform.name)
    if isinstance(transform, MolarSusceptibility):
        data.require_unit(transform.wave, {"emu"}, "emu")
        data.require_unit(transform.field, {"Oe", "oe", "oersted"}, "Oe")
        result, _ = calculate_susceptibility(
            raw,
            field_values,
            sample_weight_mg=transform.sample_mass_mg,
            molar_mass_g_mol=transform.molar_mass_g_mol,
        )
        return result, "emu/(Oe mol)", valid & np.isfinite(field_values)
    finite(field_values, transform.field)
    if isinstance(transform, Magnetoresistance):
        zero = np.flatnonzero(np.abs(field_values) <= transform.zero_tolerance)
        if len(zero) != 1 or not np.isfinite(raw[zero[0]]) or raw[zero[0]] <= 0:
            raise PlotError(
                "zero_field_reference",
                transform.name,
                "Select a sweep with one finite positive R(0) inside the specified tolerance.",
            )
        reference = raw[zero[0]]
        return 100 * (raw - reference) / reference, "%", valid
    assert isinstance(transform, Antisymmetrize)
    other = data.numeric(transform.other)
    opposite_field = data.numeric(transform.opposite_field)
    paired(raw, other, transform.name)
    paired(raw, opposite_field, transform.name)
    data.same_units(transform.wave, transform.other, transform.name)
    data.same_units(transform.field, transform.opposite_field, transform.name)
    finite(opposite_field, transform.opposite_field)
    if not np.allclose(field_values, -opposite_field, atol=transform.tolerance, rtol=0):
        raise PlotError(
            "field_pairing",
            transform.name,
            "The field columns must match H and −H row by row within the specified tolerance.",
        )
    return (raw - other) / 2, data.unit(transform.wave), valid & np.isfinite(other)
