# ruff: noqa: E501
from neml_brain.evolution import revisit
from tests.evolution.test_generative import PLAN


def test_a_weak_design_is_picked_once_per_cooldown_and_at_most_three_times(tmp_path):
    designs = {"bahce": {"brief": "bahçe gezgini", "plan": PLAN}}  # no caster, no motors: today's judges find faults
    model, brief = revisit.pick(tmp_path, designs, now=1e6)
    assert model == "bahce" and "bulgular" in brief
    revisit.mark(tmp_path, "bahce", now=1e6)
    assert revisit.pick(tmp_path, designs, now=1e6 + 3600) is None  # cooling down
    for k in range(2):
        revisit.mark(tmp_path, "bahce", now=1e6 + k)
    assert revisit.pick(tmp_path, designs, now=1e9) is None  # round limit
