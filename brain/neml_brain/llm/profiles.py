# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SPEC 4.4 - one resident model, six prompt profiles.

The table below is the contract: system prompt, max_tokens and constraint kind
per profile. Only `summarize` is unconstrained, and its output is human-facing
only - `HumanText` marks it so it can never travel back into a prompt.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

CONSTRAINTS = ("guided_choice", "guided_json", "none")

# Owner decision 4 (amends SPEC 4.4): the `failure_tag` guided_choice list is
# fixed and lives HERE, with the profile it constrains. SPEC 14.6 step 2 tags a
# failed run with one of these and step 3 embeds the tag, so the same strings
# are what skill_runs.failure_mode stores. There is exactly one copy in the
# tree; config/llm.yaml mirrors it and a test pins the two equal.
#
# "unknown" is deliberate and must stay: a closed enum with no escape hatch
# makes a 1.5B model pick the nearest wrong label instead of admitting it
# cannot tell, which poisons the failure statistics SPEC 14.3 breeds from.
FAILURE_MODES = [
    "joint_limit_hit",
    "torque_saturation",
    "balance_lost",
    "foot_slip",
    "collision",
    "goal_not_reached",
    "timeout",
    "sensor_dropout",
    "power_brownout",
    "unknown",
]


def check_failure_mode(tag: str) -> str:
    """Return `tag` if it is a SPEC 4.4 failure mode, else refuse it.

    The single gate: reflection (the agent that produces the tag) and autonomy
    learning (the step that writes it) both call this, so an off-list label
    cannot reach memory_chunks or skill_runs.failure_mode by either route.
    """
    if tag not in FAILURE_MODES:
        raise ValueError(f"{tag!r} is not a failure_tag mode; expected one of {FAILURE_MODES}")
    return tag


class HumanText(str):
    """Free-form model output (SPEC 4.4 `summarize`).

    It is a `str` so it satisfies the SPEC 4.7 Protocol and renders in the UI,
    but it is tagged: `untrusted.check()` and the provider refuse to accept it
    as prompt input, so model prose never re-enters the system.
    """

    __slots__ = ()


@dataclass(frozen=True)
class Profile:
    name: str
    system_prompt: str
    max_tokens: int
    constraint: str
    # Fixed guided_choice list, when the profile pins one. `router` does not:
    # its choices are the SPEC 4.3 intents, owned by llm/schemas.py.
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.constraint not in CONSTRAINTS:
            raise ValueError(f"unknown constraint kind: {self.constraint}")
        # SPEC 4.4: "no profile other than summarize feeds the system directly".
        if (self.constraint == "none") != (self.name == "summarize"):
            raise ValueError(
                f"SPEC 4.4: only the summarize profile may be unconstrained, got {self.name}"
            )
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")


PROFILES: Mapping[str, Profile] = MappingProxyType(
    {
        p.name: p
        for p in (
            Profile(
                "router",
                "You are an intent classifier. Output exactly one label from the allowed list. "
                "Output nothing else.",
                8,
                "guided_choice",
            ),
            Profile(
                "param_mech",
                "You fill mechanical template parameters. Output one JSON object that matches the "
                "given schema. You do not write code or geometry.",
                256,
                "guided_json",
            ),
            Profile(
                "param_elec",
                "You fill electronic board parameters. Output one JSON object that matches the "
                "given schema. You do not design schematics or pick parts outside the schema.",
                256,
                "guided_json",
            ),
            Profile(
                "param_skill",
                "You fill behaviour parameters for one skill. Output one JSON object that matches "
                "the given schema. You do not write behaviour trees.",
                256,
                "guided_json",
            ),
            Profile(
                "failure_tag",
                "You label a failed run with exactly one failure mode from the allowed list. "
                "Output nothing else.",
                64,
                "guided_choice",
                tuple(FAILURE_MODES),
            ),
            Profile(
                "summarize",
                "You write a short report in Turkish for the human operator. It is read by a "
                "person only: it is never executed, parsed or fed back into the system.",
                384,
                "none",
            ),
        )
    }
)
