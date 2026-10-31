# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from neml_brain.evolution.bench import CASES, score
from neml_brain.evolution.judges import recipe_issues

GOOD = {
    "solids": [{"id": "a", "t": "box"}, {"id": "b", "t": "cyl"}],
    "steps": [{"op": "cut", "a": "a", "b": "b", "out": "c"}],
    "result": "c",
}


def test_a_sensible_recipe_passes_and_nonsense_is_named():
    assert recipe_issues(GOOD) == []
    self_fuse = {"solids": [{"id": "a"}], "steps": [{"op": "fuse", "a": "a", "b": "a", "out": "a2"}], "result": "a2"}
    assert "kendisiyle" in recipe_issues(self_fuse)[0]
    loose = {**GOOD, "solids": [*GOOD["solids"], {"id": "z"}]}
    assert "z" in recipe_issues(loose)[0]
    assert any("geçersiz" in i for i in recipe_issues({"solids": [{"id": "x块"}], "steps": [], "result": "x块"}))


def test_right_numbers_from_a_nonsense_recipe_do_not_pass_a_benchmark_case():
    case = CASES[0]
    x, y, z = case["dims"]
    built = {"bbox": [0, 0, 0, x, y, z], "volume_mm3": case["volume"], "recipe": GOOD}
    assert score(case, built)["passed"]
    bad = {**built, "recipe": {"solids": [{"id": "a"}], "steps": [{"op": "fuse", "a": "a", "b": "a", "out": "a2"}], "result": "a2"}}
    assert not score(case, bad)["passed"]


def _robot(**over):
    joint = {"type": "fixed", "x": 0, "y": 0, "z": 0, "axis": "z"}

    def link(name, parent, part=None, role="", src="bought", at=(0, 0, 0), revolute=False, dims=(10, 10, 10), mass=10):
        j = {**joint, "x": at[0], "y": at[1], "z": at[2], **({"type": "revolute", "axis": "y"} if revolute else {})}
        return {"name": name, "parent": parent, "role": role or name, "source": src, "part": part, "dims_mm": list(dims), "mass_g": mass, "joint": j}

    links = [
        link("base", "", None, "gövde", "designed", dims=(160, 100, 20), mass=300),
        link("kart", "base", "esp32_devkit", at=(0, 0, 15)),
        link("pil", "base", "cell_18650", at=(30, 0, 15)),
        link("estop", "base", "estop_22mm", at=(-50, 0, 20)),
        link("motor_l", "base", "tt_motor", at=(0, 40, 0)),
        link("motor_r", "base", "tt_motor", at=(0, -40, 0)),
        link("tekerlek_l", "base", "tt_wheel", "sol tekerlek", at=(0, 70, 0), revolute=True),
        link("tekerlek_r", "base", "tt_wheel", "sağ tekerlek", at=(0, -70, 0), revolute=True),
    ]
    from neml_brain.evolution.catalog import apply

    return apply({"name": "r", "links": links, **over})


def test_a_robot_with_catalog_parts_a_motor_per_wheel_a_battery_and_a_stop_passes():
    from neml_brain.evolution.judges import robot_issues

    assert robot_issues(_robot()) == []


def test_missing_parts_a_weak_motor_and_a_part_outside_the_catalog_are_each_named():
    from neml_brain.evolution.judges import robot_issues

    plan = _robot()
    plan["links"] = [lk for lk in plan["links"] if lk["name"] not in ("pil", "estop", "motor_r")]
    text = "; ".join(robot_issues(plan))
    assert "batarya yok" in text and "acil durdurma" in text and "2 tekerlek döner ama yalnızca 1" in text
    odd = _robot()
    odd["links"][1]["part"] = "diger"
    assert any("katalogda yok" in i for i in robot_issues(odd))


def test_a_long_heavy_arm_on_a_small_servo_is_flagged_with_the_numbers():
    from neml_brain.evolution.judges import robot_issues

    plan = _robot()
    plan["links"] += [
        {"name": "kol", "parent": "base", "role": "kol", "source": "designed", "dims_mm": [120, 10, 10], "mass_g": 200, "joint": {"type": "revolute", "x": 0, "y": 0, "z": 30, "axis": "y"}},
        {"name": "servo", "parent": "base", "role": "servo", "source": "bought", "part": "sg90", "dims_mm": [1, 1, 1], "mass_g": 1, "joint": {"type": "fixed", "x": 0, "y": 0, "z": 30, "axis": "z"}},
    ]
    assert any("kol: gereken tork" in i for i in robot_issues(plan))


def test_the_build_pack_lists_parts_prints_steps_and_wiring_and_names_what_blocks():
    from neml_brain.evolution.buildpack import build_pack

    pack = build_pack(_robot(), {"base": {"volume_mm3": 50000}}, [])
    assert pack["ready"] and {b["part"]: b["qty"] for b in pack["bom"]}["tt_motor"] == 2
    assert pack["print"][0]["file"] == "base.stl" and any("tt_motor" in w or "motor_l" in w for w in pack["wiring"])
    assert "doğrulanmadı" in pack["markdown"] and "Montaj sırası" in pack["markdown"]
    blocked = build_pack(_robot(), {}, ["devrilme"])
    assert not blocked["ready"] and "devrilme" in blocked["markdown"]


def test_tidy_mends_a_self_fuse_and_dead_solids_and_leaves_real_work_alone():
    from neml_brain.evolution.judges import tidy

    noisy = {"solids": [{"id": "a"}, {"id": "dead"}], "steps": [{"op": "fuse", "a": "a", "b": "a", "out": "a2"}], "result": "a2"}
    fixed = tidy(noisy)
    assert fixed["result"] == "a" and fixed["steps"] == [] and [s["id"] for s in fixed["solids"]] == ["a"] and recipe_issues(fixed) == []
    assert tidy(GOOD) == GOOD
    chain = {"solids": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "steps": [{"op": "fuse", "a": "a", "b": "b", "out": "ab"}, {"op": "cut", "a": "ab", "b": "c", "out": "r"}], "result": "r"}
    assert tidy(chain) == chain


def test_equip_completes_a_moving_robot_from_the_catalog():
    from neml_brain.evolution.judges import equip, robot_issues

    def link(name, parent, role, x, **kw):
        return {"name": name, "parent": parent, "role": role, "source": "designed", "dims_mm": [60, 20, 60], "mass_g": 30,
                "joint": {"type": kw.pop("jt", "fixed"), "x": x, "y": 0, "z": 0, "axis": "y"}, **kw}

    plan = {"links": [link("root", "", "gövde", 0, dims_mm=[200, 120, 40], mass_g=500)]
            + [link(f"tekerlek_{i}", "root", "tekerlek", 80 * (i - 1.5), jt="revolute", dims_mm=[65, 65, 26]) for i in range(4)]}
    assert any("batarya" in x for x in robot_issues(plan))
    done = equip(plan)
    assert not any(k in x for x in robot_issues(done) for k in ("batarya", "kontrolcü", "acil", "yalnızca"))
    assert len(plan["links"]) == 5  # the input is untouched


def test_without_cuts_drops_one_cut_and_follows_its_output():
    from neml_brain.evolution.judges import without_cuts

    r = {"solids": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "result": "y",
         "steps": [{"op": "cut", "a": "a", "b": "b", "out": "x"}, {"op": "fuse", "a": "x", "b": "c", "out": "y"}]}
    note, mended = without_cuts(r)[0]
    assert "b" in note and mended["steps"][0]["a"] == "a" and mended["result"] == "y"
    assert without_cuts({"steps": [{"op": "fuse", "a": "a", "b": "b", "out": "x"}]}) == []


def test_equip_places_added_parts_apart():
    from neml_brain.evolution.generative import layout_issues
    from neml_brain.evolution.judges import equip

    root = {"name": "root", "parent": "", "role": "gövde", "source": "designed", "dims_mm": [200, 120, 40], "mass_g": 500,
            "joint": {"type": "fixed", "x": 0, "y": 0, "z": 0, "axis": "z"}}
    wheel = {"name": "tekerlek_1", "parent": "root", "role": "tekerlek", "source": "designed", "dims_mm": [65, 65, 26], "mass_g": 25,
             "joint": {"type": "revolute", "x": 0, "y": 100, "z": 0, "axis": "y"}}
    done = equip({"links": [root, wheel]})
    assert len(done["links"]) > 2
    added = done["links"][2:]
    assert not [i for i in layout_issues({"links": [root, *added]}) if "iç içe" in i]


def test_too_many_moving_joints_are_sent_back_not_equipped():
    from neml_brain.evolution.judges import equip, robot_issues

    root = {"name": "root", "parent": "", "role": "gövde", "source": "designed", "dims_mm": [200, 120, 40], "mass_g": 500,
            "joint": {"type": "fixed", "x": 0, "y": 0, "z": 0, "axis": "z"}}
    arms = [{"name": f"kol_{i}", "parent": "root", "role": "kol", "source": "designed", "dims_mm": [20, 20, 20], "mass_g": 5,
             "joint": {"type": "revolute", "x": 30 * i, "y": 0, "z": 40, "axis": "y"}} for i in range(24)]
    plan = {"links": [root, *arms]}
    assert any("döner kol eklemi" in x for x in robot_issues(plan))
    assert not any(lk.get("part") in ("sg90", "mg90s", "mg996r", "ds3218") for lk in equip(plan)["links"])


def test_softer_rounds_halve_then_quarter_then_drop_the_round():
    from neml_brain.evolution.judges import softer_rounds

    r = {"solids": [], "result": "a", "round": {"kind": "fillet", "r": 2, "edges": "all"}}
    got = softer_rounds(r)
    assert [m.get("round", {}).get("r") for _, m in got] == [1.0, 0.5, None]
    assert softer_rounds({"result": "a"}) == []


def test_equip_adds_motor_drivers_and_a_servo_driver_board():
    from neml_brain.evolution.judges import equip

    root = {"name": "root", "parent": "", "role": "gövde", "source": "designed", "dims_mm": [200, 120, 40], "mass_g": 500,
            "joint": {"type": "fixed", "x": 0, "y": 0, "z": 0, "axis": "z"}}
    wheels = [{"name": f"tekerlek_{i}", "parent": "root", "role": "tekerlek", "source": "designed", "dims_mm": [65, 65, 26], "mass_g": 25,
               "joint": {"type": "revolute", "x": 40 * i, "y": 80, "z": 0, "axis": "y"}} for i in range(4)]
    parts = [lk.get("part") for lk in equip({"links": [root, *wheels]})["links"]]
    assert parts.count("tb6612") == 2


def test_equip_thickens_slender_printed_bars():
    from neml_brain.evolution.judges import equip

    root = {"name": "root", "parent": "", "role": "gövde", "source": "designed", "dims_mm": [200, 120, 40], "mass_g": 500,
            "joint": {"type": "fixed", "x": 0, "y": 0, "z": 0, "axis": "z"}}
    bar = {"name": "cubuk", "parent": "root", "role": "çubuk", "source": "designed", "dims_mm": [20, 3, 3], "mass_g": 2,
           "joint": {"type": "fixed", "x": 0, "y": 0, "z": 30, "axis": "z"}}
    assert equip({"links": [root, bar]})["links"][1]["dims_mm"] == [20, 6.0, 6.0]


def test_thickened_makes_a_thin_bar_pass_the_beam_check():
    from neml_brain.evolution import structure
    from neml_brain.evolution.judges import thickened

    recipe = {"solids": [{"id": "a", "t": "box", "at": [0, 0, 0], "size": [20, 3, 3]}], "steps": [], "result": "a"}
    got = thickened(recipe, [0, 0, 0, 20, 3, 3], 6.0)
    box = got["solids"][-1]
    assert box["size"] == [20, 6.0, 6.0] and box["at"] == [0, -1.5, -1.5]
    assert got["steps"][-1] == {"op": "fuse", "a": "a", "b": "sturdy", "out": "sturdy_part"} and got["result"] == "sturdy_part"
    assert structure.generic_link([20, 3, 3], 180, "PLA", 1.2, 5)
    assert not structure.generic_link([20, 6, 6], 720, "PLA", 1.2, 5)
