# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outcome judge, second-look review and factor refit (ADR-014)."""

from neml_brain.autonomy.discovery import PRIOR_GAIN, Factors
from neml_brain.autonomy.judge import MAX_ATTEMPTS, RunFacts, TaskFacts, judge
from neml_brain.autonomy.review import review_completed
from neml_brain.autonomy.tuning import PSEUDO, RunRecord, fit


def task(kind="exploration", spec=None, attempts=1, skill=None):
    return TaskFacts("t1", kind, spec or {}, attempts, skill)


def run(outcome="success", env="sim", **metrics):
    return RunFacts(outcome, env, metrics)


def test_a_clean_sim_success_is_accepted():
    v = judge(task(), run())
    assert v.done and v.action == "accept"


def test_executor_success_is_not_enough_when_a_criterion_fails():
    t = task("calibration", attempts=1)
    v = judge(t, run(reality_gap=0.31))
    assert not v.done and v.action == "retry"
    assert "reality_gap" in v.reasons[0]
    assert v.next_spec["seed"] == 1 and v.next_spec["retry_of_attempt"] == 1


def test_a_missing_measurement_fails_instead_of_passing():
    v = judge(task("calibration"), run())
    assert not v.done and "no measurement" in v.reasons[0]


def test_explicit_acceptance_overrides_the_default():
    t = task(spec={"acceptance": [{"metric": "speed_mps", "op": ">=", "value": 0.5}]})
    assert judge(t, run(speed_mps=0.6)).done
    assert not judge(t, run(speed_mps=0.4)).done


def test_malformed_criterion_is_a_failure():
    t = task(spec={"acceptance": [{"metric": "x", "op": "~", "value": 1}]})
    assert not judge(t, run(x=1)).done


def test_safety_violation_escalates_and_never_retries():
    v = judge(task(attempts=1), run(safety_violation=True))
    assert v.action == "escalate" and v.next_spec is None


def test_physical_run_needs_independent_sensor_verification():
    assert judge(task(), run(env="free")).action == "escalate"
    assert judge(task(), run(env="free", sensor_verified=True)).done


def test_exhausted_attempts_open_a_repair_when_a_skill_is_behind_it():
    t = task(attempts=MAX_ATTEMPTS, skill="climb@3")
    assert judge(t, run("failure")).action == "repair"
    assert judge(task(attempts=MAX_ATTEMPTS), run("failure")).action == "escalate"


class FakeReview:
    def __init__(self, pairs):
        self.pairs, self.reopened = pairs, []

    async def recent_done(self, days):
        return self.pairs

    async def reopen(self, task_id, reasons):
        self.reopened.append((task_id, list(reasons)))


async def test_review_reopens_work_that_no_longer_passes():
    good = (TaskFacts("ok", "calibration", {}, 1), run(reality_gap=0.10))
    stale = (TaskFacts("bad", "calibration", {}, 1), run(reality_gap=0.25))
    repo = FakeReview([good, stale])
    assert await review_completed(repo) == ["bad"]
    assert repo.reopened[0][0] == "bad"


def test_fit_with_no_history_keeps_the_priors():
    assert fit([]).gain == dict(PRIOR_GAIN)


def test_fit_moves_toward_the_observed_rate_but_not_all_the_way():
    history = [RunRecord("exploration", False, 100.0)] * 3
    gain = fit(history).g("exploration")
    assert 0.05 <= gain < PRIOR_GAIN["exploration"]  # three failures pull it down, not to zero
    big = fit([RunRecord("exploration", True, 100.0)] * (PSEUDO * 40)).g("exploration")
    assert big > 0.9


def test_fit_makes_the_faster_kind_cheaper():
    history = [RunRecord("exploration", True, 10.0)] * 30 + [
        RunRecord("evolution", True, 1000.0)
    ] * 30
    f = fit(history, Factors())
    assert f.c("exploration") > f.c("evolution")
