# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The generated robot as a Gazebo model: its own body, its own wheels, its own masses.

Until now every design was run as the same stand-in chassis scaled to its mass, so a simulated "success" said nothing about
the design. `sdf_of(plan)` builds the real thing for the wheeled class: every non-wheel link becomes a box on one rigid body
(masses and inertia added up about the centre of mass), every wheel link a cylinder on a revolute joint, driven by the
differential-drive plugin the stand-in already uses (left wheels = +y side). A plan that cannot be driven (no wheel pair, a
vertical wheel axis, a body that drags on the floor) raises `NotDrivable` with the reason, which is a lesson, not a crash.

# ponytail: wheels only (no legs or arms moving), links that are not wheels are rigid; one wheel axis for the whole robot."""

from __future__ import annotations

import math
from typing import Any

from neml_brain.evolution.catalog import CATALOG

MM = 0.001
CASTER_MU = 0.0


class NotDrivable(ValueError):
    """Why this robot cannot be run as a wheeled vehicle."""


def _is_wheel(lk: dict[str, Any]) -> bool:
    if lk["joint"]["type"] != "revolute":
        return False
    part = CATALOG.get(str(lk.get("part", "")))
    if part is not None:
        return part["kind"] == "wheel"
    text = f"{lk['name']} {lk.get('role', '')}".lower()
    return "wheel" in text or "teker" in text


def _box_inertia(m: float, sx: float, sy: float, sz: float) -> tuple[float, float, float]:
    return m / 12 * (sy**2 + sz**2), m / 12 * (sx**2 + sz**2), m / 12 * (sx**2 + sy**2)


def sdf_of(plan: dict[str, Any], camera: bool = False) -> tuple[str, dict[str, Any]]:
    """(SDF text, facts about it); raises NotDrivable."""
    from neml_brain.evolution.generative import layout

    centre, size, _ = layout(plan)
    from neml_brain.evolution.generative import slug

    names = {slug(str(lk["name"])): lk for lk in plan["links"]}
    wheels = [n for n, lk in names.items() if _is_wheel(lk)]
    if len(wheels) < 2:
        raise NotDrivable(f"{len(wheels)} tekerlek var; sürüş için en az bir tekerlek çifti gerekir")
    axes = {names[n]["joint"]["axis"] for n in wheels}
    if len(axes) > 1 or "z" in axes:
        raise NotDrivable(f"tekerlek eksenleri {sorted(axes)}: hepsi aynı yatay eksende (x ya da y) olmalı")
    if "x" in axes:  # turn the plan a quarter turn so the wheels spin about y and the robot drives along +x
        centre = {n: [c[1], -c[0], c[2]] for n, c in centre.items()}
        size = {n: [s[1], s[0], s[2]] for n, s in size.items()}

    def m(n: str) -> float:
        return float(names[n]["mass_g"]) / 1000

    yc = sum(centre[n][1] for n in wheels) / len(wheels)
    left = [n for n in wheels if centre[n][1] > yc]
    right = [n for n in wheels if centre[n][1] <= yc]
    if not left or not right:
        raise NotDrivable("tekerlekler gövdenin tek yanında; sol ve sağ tekerlek gerekir")

    rad = {n: max(size[n][0], size[n][2]) / 2 * MM for n in wheels}
    width = {n: size[n][1] * MM for n in wheels}
    z0 = min(centre[n][2] * MM - rad[n] for n in wheels)  # wheel bottoms on the floor
    body = [n for n in names if n not in wheels]
    bm = sum(m(n) for n in body)
    if bm <= 0:
        raise NotDrivable("gövde kütlesi yok")
    com = [sum(m(n) * centre[n][k] * MM for n in body) / bm for k in range(3)]
    ixx = iyy = izz = 0.0
    for n in body:
        a, b, c = _box_inertia(m(n), *(v * MM for v in size[n]))
        d = [centre[n][k] * MM - com[k] for k in range(3)]
        ixx += a + m(n) * (d[1] ** 2 + d[2] ** 2)
        iyy += b + m(n) * (d[0] ** 2 + d[2] ** 2)
        izz += c + m(n) * (d[0] ** 2 + d[1] ** 2)
    low = min((centre[n][2] - size[n][2] / 2) * MM for n in body)
    clearance = low - z0
    if clearance < -0.002:
        raise NotDrivable(f"gövde tekerlek tabanından {-clearance * 1000:.0f} mm aşağıda: zemine sürtünür; tekerlekleri büyüt ya da gövdeyi yükselt")
    if clearance > 0.25:
        raise NotDrivable(f"gövde zeminden {clearance * 1000:.0f} mm yukarıda: devrilir; tekerlekleri büyüt ya da gövdeyi alçalt")

    def pose(x: float, y: float, z: float, r: float = 0.0, p: float = 0.0, w: float = 0.0) -> str:
        return f"<pose>{x:.5f} {y:.5f} {z - z0:.5f} {r:.5f} {p:.5f} {w:.5f}</pose>"

    parts = []
    for n in body:
        sx, sy, sz = (v * MM for v in size[n])
        c = centre[n]
        geom = f"<geometry><box><size>{sx:.5f} {sy:.5f} {sz:.5f}</size></box></geometry>"
        parts.append(f'<collision name="c_{n}">{pose(c[0] * MM, c[1] * MM, c[2] * MM)}{geom}</collision><visual name="v_{n}">{pose(c[0] * MM, c[1] * MM, c[2] * MM)}{geom}</visual>')
    xs = [centre[n][0] * MM for n in body]
    xmin = min(c - size[n][0] / 2 * MM for n, c in zip(body, xs, strict=True))
    xmax = max(c + size[n][0] / 2 * MM for n, c in zip(body, xs, strict=True))
    wx = [centre[n][0] * MM for n in wheels]
    casters = 0
    if len(wheels) < 4 and (max(wx) - min(wx)) < 0.5 * (xmax - xmin):  # two wheels near the middle: ball casters keep it level
        rc = 0.3 * sum(rad.values()) / len(rad)
        for x in (xmin + rc, xmax - rc):
            parts.append(
                f'<collision name="caster_{casters}">{pose(x, com[1], z0 + rc)}<geometry><sphere><radius>{rc:.4f}</radius></sphere></geometry>'
                f"<surface><friction><ode><mu>{CASTER_MU}</mu><mu2>{CASTER_MU}</mu2></ode></friction></surface></collision>"
            )
            casters += 1
    cam = (
        f'<sensor name="cam" type="camera"><pose>{xmin - 0.55:.3f} {com[1]:.3f} {com[2] - z0 + 0.4:.3f} 0 0.5 0</pose><update_rate>10</update_rate>'
        "<always_on>true</always_on><camera><horizontal_fov>1.3</horizontal_fov><image><width>320</width><height>240</height></image>"
        "<clip><near>0.05</near><far>30</far></clip></camera></sensor>"
        if camera
        else ""
    )
    links = [
        f'<link name="base_link"><inertial><pose>{com[0]:.5f} {com[1]:.5f} {com[2] - z0:.5f} 0 0 0</pose><mass>{bm:.4f}</mass>'
        f"<inertia><ixx>{ixx:.6f}</ixx><iyy>{iyy:.6f}</iyy><izz>{izz:.6f}</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>{''.join(parts)}{cam}</link>"
    ]
    joints = []
    for n in wheels:
        r, w, mass = rad[n], width[n], m(n)
        c = centre[n]
        cyl = f"<geometry><cylinder><radius>{r:.5f}</radius><length>{w:.5f}</length></cylinder></geometry>"
        links.append(
            f'<link name="{n}">{pose(c[0] * MM, c[1] * MM, c[2] * MM, -math.pi / 2)}'
            f"<inertial><mass>{mass:.4f}</mass><inertia><ixx>{mass / 12 * (3 * r * r + w * w):.7f}</ixx><iyy>{mass / 12 * (3 * r * r + w * w):.7f}</iyy>"
            f"<izz>{mass * r * r / 2:.7f}</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>"
            f'<collision name="c">{cyl}<surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface></collision><visual name="v">{cyl}</visual></link>'
        )
        joints.append(
            f'<joint name="{n}_joint" type="revolute"><parent>base_link</parent><child>{n}</child>'
            "<axis><xyz>0 0 1</xyz><limit><lower>-1e16</lower><upper>1e16</upper></limit></axis></joint>"
        )
    sep = (sum(centre[n][1] for n in left) / len(left) - sum(centre[n][1] for n in right) / len(right)) * MM
    mean_r = sum(rad.values()) / len(rad)
    plugin = (
        '<plugin filename="gz-sim-diff-drive-system" name="gz::sim::systems::DiffDrive">'
        + "".join(f"<left_joint>{n}_joint</left_joint>" for n in left)
        + "".join(f"<right_joint>{n}_joint</right_joint>" for n in right)
        + f"<wheel_separation>{sep:.4f}</wheel_separation><wheel_radius>{mean_r:.4f}</wheel_radius></plugin>"
    )
    sdf = f'<?xml version="1.0"?><sdf version="1.10"><model name="evo_chassis">{"".join(links)}{"".join(joints)}{plugin}</model></sdf>'
    mass_all = bm + sum(m(n) for n in wheels)
    info = {"wheels": len(wheels), "casters": casters, "mass_kg": round(mass_all, 3), "clearance_mm": round(clearance * 1000), "track_mm": round(sep * 1000), "wheel_radius_mm": round(mean_r * 1000)}
    return sdf, info
