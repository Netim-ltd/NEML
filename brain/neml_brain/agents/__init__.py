# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 - importing the package registers every agent, which is what
# runs the SPEC 5.4 tool-policy check. A bad grant is therefore an import error.
# `orchestrator` is deliberately absent: it imports from this package.

from neml_brain.agents import (  # noqa: F401
    coding,
    electronics,
    manufacturing,
    mechanical,
    memory,
    perception,
    planner,
    reflection,
    swarm,
)
from neml_brain.agents.base import REGISTRY, Agent, Deps

__all__ = ["REGISTRY", "Agent", "Deps"]
