# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The interface contracts of SPEC 6.3 and SPEC 6.4, transcribed and enforced.

The tables below are copied from the spec. If a server signature drifts from the
spec, this file fails - that is the whole point of it.
"""

import inspect

import pytest
from fastapi.testclient import TestClient
from mcp_servers.neml_mcp_cad import server as cad
from mcp_servers.neml_mcp_fab import server as fab
from mcp_servers.neml_mcp_genome import server as genome
from mcp_servers.neml_mcp_sim import server as sim

# SPEC 6.3 - neml-mcp-sim
SIM_CONTRACT = {
    "set_seed": ["seed"],
    "load_world": ["world_id", "seed", "profile"],
    "spawn_robot": ["urdf_path", "pose", "ns"],
    "step": ["duration_s"],
    "run_until": ["condition", "timeout_s"],
    "read_sensor": ["robot", "sensor"],
    "capture_camera": ["robot", "cam"],
    "get_contacts": ["robot"],
    "apply_wrench": ["link", "force_N", "torque_Nm"],
    "get_metrics": ["robot"],
    "reset": ["handle"],
    "teardown": ["handle"],
}

# SPEC 6.4 - neml-mcp-fab
FAB_CONTRACT = {
    "slice": ["model_3mf", "profile_id"],
    "validate_gcode": ["gcode_path"],
    "estimate": ["gcode_path"],
    "upload": ["gcode_path", "printer_id"],
    "start": ["file", "printer_id", "approval_token"],
    "status": ["printer_id"],
    "cancel": ["job"],
}

ALL_SERVERS = [sim, fab, genome, cad]


def _names(fn):
    return list(inspect.signature(fn, eval_str=True).parameters)


@pytest.mark.parametrize("tool,params", SIM_CONTRACT.items())
def test_sim_signature(tool, params):
    assert tool in sim.TOOLS, f"SPEC 6.3 requires sim.{tool}"
    names = _names(sim.TOOLS[tool])
    assert names[: len(params)] == params


@pytest.mark.parametrize("tool,params", FAB_CONTRACT.items())
def test_fab_signature(tool, params):
    assert tool in fab.TOOLS, f"SPEC 6.4 requires fab.{tool}"
    names = _names(fab.TOOLS[tool])
    assert names[: len(params)] == params


def test_no_extra_tools():
    assert set(sim.TOOLS) == set(SIM_CONTRACT)
    assert set(fab.TOOLS) == set(FAB_CONTRACT)


@pytest.mark.parametrize("module", ALL_SERVERS)
def test_every_entry_point_takes_a_timeout(module):
    """SPEC 6.3: no unbounded blocking call - timeout on every call."""
    for name, fn in module.TOOLS.items():
        params = inspect.signature(fn, eval_str=True).parameters
        assert "timeout_s" in params, f"{module.__name__}.{name} has no timeout_s"
        param = params["timeout_s"]
        assert param.annotation is float
        if param.default is not inspect.Parameter.empty:
            assert isinstance(param.default, float) and param.default > 0


@pytest.mark.parametrize("module", ALL_SERVERS)
def test_tools_list_over_streamable_http(module):
    """SPEC 6.2: Streamable HTTP, and every tool is advertised."""
    with TestClient(module.app) as http:
        response = http.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0" and body["id"] == 1
        advertised = {tool["name"] for tool in body["result"]["tools"]}
        assert advertised == set(module.TOOLS)
        for tool in body["result"]["tools"]:
            assert tool["inputSchema"]["type"] == "object"


def test_ports_match_spec():
    assert (sim.PORT, fab.PORT, genome.PORT, cad.PORT) == (9101, 9102, 9103, 9104)


def test_unknown_tool_is_a_typed_jsonrpc_error():
    with TestClient(sim.app) as http:
        body = http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "definitely_not_a_tool", "arguments": {}},
            },
        ).json()
        assert body["error"]["code"] == -32000
        assert "definitely_not_a_tool" in body["error"]["message"]
