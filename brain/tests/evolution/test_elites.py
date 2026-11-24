# ruff: noqa: E501
from neml_brain.evolution import elites


def _plan(name, mass):
    j = {"type": "fixed", "x": 0, "y": 0, "z": 0, "axis": "z"}
    return {"name": name, "links": [{"name": "b", "parent": "", "mass_g": mass, "dims_mm": [100, 80, 20], "joint": j}]}


def test_the_best_plan_of_a_niche_is_kept_and_other_niches_are_offered(tmp_path):
    assert elites.keep(tmp_path, _plan("a", 300), 2.0)
    assert not elites.keep(tmp_path, _plan("b", 300), 1.0)  # same niche, worse
    assert elites.keep(tmp_path, _plan("c", 1200), 1.0)  # another niche
    assert "'c'" in elites.hint(tmp_path, _plan("a", 300), 0)
    assert elites.hint(tmp_path / "none", None, 0) == ""
