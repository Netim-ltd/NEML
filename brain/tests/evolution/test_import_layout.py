# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Imported meshes are assembled, kept, or laid out so that nothing is piled up and everything is visible."""

from __future__ import annotations

import itertools
import math

import numpy as np

from neml_brain.evolution.import_layout import place, unit_factor
from neml_brain.evolution.model_scene import import_part


def mesh(i, size, center, name=None, file=None):
    return {
        "id": f"imp_aaaaaa_{i}",
        "kind": "stl",
        "name": name or f"part{i}",
        "file": file,
        "repo": "o/r",
        "license": "MIT",
        "source": "https://github.com/o/r/blob/main/x.stl",
        "urls": {"stl": f"u/{i}.stl"},
        "size": size,
        "center": center,
    }


def boxes(placements):
    return [
        (np.array(p["pos"]) - np.array(p["size"]) / 2, np.array(p["pos"]) + np.array(p["size"]) / 2)
        for p in placements
    ]


def disjoint(placements):
    for (alo, ahi), (blo, bhi) in itertools.combinations(boxes(placements), 2):
        if np.all(np.minimum(ahi, bhi) - np.maximum(alo, blo) > 1e-6):
            return False
    return True


def test_a_urdf_places_a_mesh_once_per_visual_in_millimetres_and_turns_its_centre():
    leg = mesh(
        0, [0.02, 0.02, 0.1], [0.05, 0.0, 0.0], file="leg.stl"
    )  # metres, centre 5 cm along x
    urdf = {
        "id": "imp_aaaaaa_u",
        "kind": "urdf",
        "assembly": [
            {
                "mesh": "leg.stl",
                "link": "fl",
                "pos": [100.0, 50.0, 0.0],
                "quat": [0, 0, math.sqrt(0.5), math.sqrt(0.5)],
                "factor": 1000.0,
            },
            {
                "mesh": "leg.stl",
                "link": "fr",
                "pos": [100.0, -50.0, 0.0],
                "quat": [0, 0, 0, 1],
                "factor": 1000.0,
            },
            {
                "mesh": "missing.stl",
                "link": "x",
                "pos": [0, 0, 0],
                "quat": [0, 0, 0, 1],
                "factor": 1.0,
            },
        ],
    }
    found = place([leg, urdf])
    assert [p["label"] for p in found] == ["fl · part0", "fr · part0"]
    assert [round(v, 1) for v in found[0]["pos"]] == [
        100.0,
        100.0,
        0.0,
    ]  # centre (50,0,0) turned 90 degrees
    assert [round(v, 1) for v in found[1]["pos"]] == [150.0, -50.0, 0.0]
    assert found[0]["size"] == [20.0, 20.0, 100.0]


def test_parts_piled_on_one_origin_are_laid_out_in_a_grid_on_the_ground():
    parts = [mesh(i, [40.0 + 10 * i, 30.0, 20.0], [0, 0, 0]) for i in range(6)]
    found = place(parts)
    assert len(found) == 6 and all(p.get("table") for p in found) and disjoint(found)
    assert all(abs(p["pos"][2] - p["size"][2] / 2) < 1e-6 for p in found)  # resting on the ground
    assert len({tuple(p["pos"]) for p in found}) == 6


def test_parts_that_already_form_an_assembly_keep_their_coordinates():
    parts = [mesh(i, [20.0, 20.0, 20.0], [30.0 * i, 0.0, 0.0]) for i in range(4)]
    found = place(parts)
    assert [p["pos"] for p in found] == [
        [0.0, 0.0, 0.0],
        [30.0, 0.0, 0.0],
        [60.0, 0.0, 0.0],
        [90.0, 0.0, 0.0],
    ]
    assert not any(p.get("table") for p in found)


def test_a_robot_modelled_in_metres_is_scaled_up_and_a_millimetre_one_is_not():
    metres = [mesh(0, [0.3, 0.1, 0.05], [0, 0, 0])]
    assert unit_factor(metres) == 1000.0 and place(metres)[0]["size"] == [300.0, 100.0, 50.0]
    assert unit_factor([mesh(0, [300.0, 100.0, 50.0], [0, 0, 0])]) == 1.0


def test_the_scene_part_carries_the_orientation_and_the_unit_factor_for_the_viewer():
    placement = place(
        [
            mesh(0, [0.1, 0.1, 0.1], [0, 0, 0], file="a.stl"),
            {
                "id": "u",
                "kind": "urdf",
                "assembly": [
                    {
                        "mesh": "a.stl",
                        "link": "l",
                        "pos": [1, 2, 3],
                        "quat": [0, 0, 0, 1],
                        "factor": 1000.0,
                    }
                ],
            },
        ]
    )[0]
    part = import_part(placement, 0)
    assert (
        part["quat"] == [0, 0, 0, 1]
        and part["geom"]["scale"] == 1000.0
        and part["geom"]["size"] == [100.0, 100.0, 100.0]
    )
    assert "URDF" in part["info"]["yerleşim"]


def urdf(i, assembly, rig=None):
    return {
        "id": f"imp_aaaaaa_u{i}",
        "kind": "urdf",
        "name": f"u{i}",
        "assembly": assembly,
        "rig": rig,
    }


def ident(**extra):
    return {
        "vpos": [0, 0, 0],
        "vquat": [0, 0, 0, 1],
        "pos": [0, 0, 0],
        "quat": [0, 0, 0, 1],
        "link": "l",
        **extra,
    }


def test_primitives_colours_and_non_uniform_scale_come_through_with_their_link_pose():
    leg = mesh(0, [10.0, 10.0, 10.0], [1.0, 2.0, 3.0], file="leg.stl")
    found = place(
        [
            leg,
            urdf(
                0,
                [
                    ident(
                        shape={"type": "cylinder", "radius": 20.0, "length": 50.0},
                        color="#ff0000",
                        link="wheel",
                    ),
                    ident(shape={"type": "sphere", "radius": 5.0}),
                    ident(mesh="leg.stl", factor=1.0, scale3=[1.0, 2.0, 1.0]),
                ],
            ),
        ]
    )
    cyl, sph, leg_part = found
    assert (
        cyl["size"] == [40.0, 40.0, 50.0]
        and cyl["color"] == "#ff0000"
        and cyl["local_pos"] == [0, 0, 0]
    )
    assert sph["size"] == [10.0, 10.0, 10.0]
    assert leg_part["size"] == [10.0, 20.0, 10.0] and leg_part["local_pos"] == [
        1.0,
        4.0,
        3.0,
    ]  # centre scaled per axis
    part = import_part(cyl, 0)
    assert part["geom"] == {
        "type": "cylinder",
        "size": [40.0, 40.0, 50.0],
        "radius": 20.0,
        "length": 50.0,
    }
    assert part["color"] == "#ff0000" and part["link"] == "wheel" and "files" not in part


def test_a_dae_in_the_urdf_finds_the_stl_of_the_same_name_and_unmatched_meshes_are_listed():
    from neml_brain.evolution.imports import unmatched_meshes

    stl = mesh(0, [10.0, 10.0, 10.0], [0, 0, 0], file="arm.stl")
    assembly = [ident(mesh="arm.dae", factor=1.0), ident(mesh="gone.dae", factor=1.0)]
    found = place([stl, urdf(0, assembly)])
    assert [p["id"] for p in found] == ["imp_aaaaaa_0_p0"]
    assert unmatched_meshes(assembly, [stl]) == ["gone.dae"]


def test_of_several_urdfs_the_one_that_explains_the_most_parts_is_used_and_it_provides_the_rig():
    from neml_brain.evolution.import_layout import chosen_urdf, rig_of_imports

    a, b = mesh(0, [1, 1, 1], [0, 0, 0], file="a.stl"), mesh(1, [1, 1, 1], [0, 0, 0], file="b.stl")
    small = urdf(0, [ident(mesh="a.stl", factor=1.0)], {"root": "r", "joints": [{"name": "x"}]})
    big = urdf(
        1,
        [ident(mesh="a.stl", factor=1.0), ident(mesh="b.stl", factor=1.0)],
        {"root": "r", "joints": [{"name": "y"}]},
    )
    assert chosen_urdf([a, b, small, big]) is big
    assert rig_of_imports([a, b, small, big])["joints"] == [{"name": "y"}]
    assert (
        chosen_urdf([a, urdf(2, [ident(mesh="zzz.stl", factor=1.0)])]) is None
    )  # explains nothing: not used
    assert rig_of_imports([a]) is None


def test_equally_good_urdfs_are_told_apart_by_how_much_they_can_move():
    from neml_brain.evolution.import_layout import chosen_urdf

    still = {
        **urdf(0, [ident(shape={"type": "sphere", "radius": 1.0})]),
        "urdf": {"movable_joints": 0},
    }
    moving = {
        **urdf(1, [ident(shape={"type": "sphere", "radius": 1.0})]),
        "urdf": {"movable_joints": 3},
    }
    assert chosen_urdf([still, moving]) is moving and chosen_urdf([moving, still]) is moving


def test_then_the_urdf_with_link_masses_wins_so_balance_can_be_computed():
    from neml_brain.evolution.import_layout import chosen_urdf

    bare = {
        **urdf(0, [ident(shape={"type": "sphere", "radius": 1.0})]),
        "urdf": {"movable_joints": 2},
        "rig": {"links": {}},
    }
    heavy = {
        **urdf(1, [ident(shape={"type": "sphere", "radius": 1.0})]),
        "urdf": {"movable_joints": 2},
        "rig": {"links": {"a": {"mass": 1, "com": [0, 0, 0]}}},
    }
    assert chosen_urdf([bare, heavy]) is heavy
