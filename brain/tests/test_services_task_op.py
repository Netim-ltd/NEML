# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

from neml_brain.services import Db


def test_a_model_invented_task_id_is_refused_not_sent_to_postgres():
    repo = Db.__new__(Db)  # no database: the id check must fire before any query
    out = asyncio.run(
        repo.task_op(intent="update_task", command="x", actor="u", params={"task_id": "12345"})
    )
    assert out["ok"] is False and "12345" in out["reason"]


def test_design_arguments_reach_the_mcp_tools_unchanged():
    from neml_brain.services import adapt_params

    recipe = {
        "recipe": {"solids": [], "result": "a"},
        "name": "bar",
        "out_dir": "/srv/neml/work/design/x",
    }
    assert adapt_params("cad.generate", recipe) == recipe
    assert adapt_params("sim.run", {"condition": "c"}) == {"condition": "c"}


def test_design_simulation_is_a_real_sim_run_not_a_malformed_run_until(monkeypatch):
    from neml_brain import services

    calls: list[tuple[str, str, dict]] = []

    class Client:
        async def call(self, server, tool, args, timeout_s=None):
            calls.append((server, tool, args))
            return {"satisfied": True, "sim_time_s": 10.0, "world_sha256": "x"}

    out = asyncio.run(services.Mcp(Client()).call("sim.run", {"params": {"wall_mm": 3}}))
    assert out["ok"] and out["kind"] == "smoke"
    assert [c[1] for c in calls] == ["set_seed", "load_world", "run_until", "teardown"]
