"""Display corrections for a simulated powder pattern."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from functools import lru_cache
from typing import Any

import numpy as np

from materials_data_studio.modules.xrd.simulation import SimulatedPattern, broaden_pattern

_REFLECTION = re.compile(r"\(([+-]?\d+(?:\s+[+-]?\d+){2,3})\)")


@lru_cache(maxsize=4)
def _orientation_geometry(
    labels: tuple[str, ...], cell: tuple[float, ...], space_group: str, hkl: tuple[int, ...]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cache angles of equivalent planes for the whole pattern."""
    import gemmi

    alpha, beta, gamma = np.deg2rad(cell[3:])
    a, b, c = cell[:3]
    metric = np.linalg.inv([
        [a*a, a*b*np.cos(gamma), a*c*np.cos(beta)],
        [a*b*np.cos(gamma), b*b, b*c*np.cos(alpha)],
        [a*c*np.cos(beta), b*c*np.cos(alpha), c*c],
    ])
    group = gemmi.find_spacegroup_by_name(space_group)
    operations = list(group.operations()) if group is not None else []
    axis = np.asarray(hkl)
    norm = float(axis @ metric @ axis)
    angles, indices = [], []
    for index, label in enumerate(labels):
        equivalents = set()
        for match in _REFLECTION.findall(label):
            values = [int(value) for value in match.split()]
            plane = (values[0], values[1], values[-1])
            orbit = {tuple(op.apply_to_hkl(list(plane))) for op in operations} or {plane}
            equivalents.update(orbit)
            equivalents.update(tuple(-v for v in reflection) for reflection in orbit)
        if equivalents:
            reflections = np.asarray(sorted(equivalents))
            cosine = (reflections @ metric @ axis) ** 2
            cosine /= norm * np.sum((reflections @ metric) * reflections, axis=1)
            angles.extend(np.clip(cosine, 0, 1))
            indices.extend([index] * len(reflections))
    peak_index = np.asarray(indices, dtype=np.intp)
    return np.asarray(angles), peak_index, np.bincount(peak_index, minlength=len(labels))


def apply_cif_profile(
    sticks: SimulatedPattern, settings: Mapping[str, Any], *, cell: tuple[float, ...] = (),
) -> SimulatedPattern:
    """Apply March–Dollase intensities and Gaussian size/strain widths."""
    wavelength = float(settings.get("wavelength_a", 1.540598))
    size = float(settings.get("particle_size_nm", 0.0))
    strain = float(settings.get("isotropic_strain_percent", 0.0)) / 100.0
    orientation = tuple(settings.get("orientation_hkl", (0, 0, 1)))
    alignment = float(settings.get("orientation_alignment", 1.0))
    pattern = sticks
    if (settings.get("preferred_orientation") and 0.1 <= alignment < 1.0 and any(orientation)
            and len(cell) == 6 and sticks.hkl_labels):
        cos_sq, indices, counts = _orientation_geometry(
            tuple(sticks.hkl_labels), cell, str(settings.get("space_group_name", "")), orientation
        )
        r = 1.0 / alignment if settings.get("orientation_geometry") == "needles" else alignment
        weights = (r*r*cos_sq + (1 - cos_sq)/r) ** -1.5
        sums = np.bincount(indices, weights=weights, minlength=len(counts))
        factor = np.divide(sums, counts, out=np.ones(len(counts)), where=counts > 0)
        pattern = replace(sticks, intensity=sticks.intensity * factor, profile_x=None, profile_y=None)
    fwhm = settings.get("fwhm_deg", 0.15)
    if fwhm is None and size <= 0 and strain <= 0:
        return pattern
    low, high = settings.get("two_theta_range", (1.0, 90.0))
    step = float(settings.get("profile_step_deg", 0.01))
    return broaden_pattern(
        pattern, two_theta_range=(float(low), float(high)),
        fwhm_deg=float(fwhm) if fwhm is not None else step,
        profile_step_deg=step, radiation=str(settings.get("radiation", "Custom")),
        wavelength_a=wavelength, particle_size_nm=size, strain=strain,
    )
