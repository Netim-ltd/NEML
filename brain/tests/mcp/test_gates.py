# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two refusals that must hold in code: SPEC 5.2 level 4 and SPEC 13.3."""

import json

import httpx
import pytest
import yaml
from mcp_servers.neml_mcp_fab import server as fab
from mcp_servers.neml_mcp_genome import server as genome

GENOME_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "genome_id", "limits"],
    "properties": {
        "schema_version": {"type": "integer"},
        "genome_id": {"type": "string"},
        "parent": {"type": ["string", "null"]},
        "limits": {
            "type": "object",
            "required": ["joint_torque_nm_max"],
            "properties": {
                "joint_torque_nm_max": {"type": "number"},
                "body_current_a_max": {"type": "number"},
            },
        },
    },
}

BASE_GENOME = {
    "schema_version": 1,
    "genome_id": "quadruped_v2",
    "status": "active",
    "limits": {"joint_torque_nm_max": 2.5, "body_current_a_max": 20.0},
}


@pytest.fixture
def genome_dir(tmp_path):
    (tmp_path / "genome.schema.json").write_text(json.dumps(GENOME_SCHEMA), encoding="utf-8")
    genome.configure(genome_dir=tmp_path)
    return tmp_path


# --- SPEC 5.2 level 4: MANUFACTURE needs a human approval token --------------


@pytest.mark.parametrize("token", ["", "   ", None])
async def test_fab_start_refuses_without_approval_token(token):
    handle = fab.FileHandle(
        printer_id="prusa-1", name="p.gcode", remote_path="usb/p.gcode", size_bytes=1
    )
    with pytest.raises(fab.ApprovalRequiredError):
        await fab.start(handle, "prusa-1", token)


async def test_fab_start_runs_with_a_token(monkeypatch):
    monkeypatch.setenv("PRUSALINK_URL", "http://printer.local")
    monkeypatch.setenv("PRUSALINK_API_KEY", "k")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("X-Api-Key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 42})

    class TestBudget:
        async def consume(self, resource, amount):
            assert resource == "filament_grams"
            return 0.0

    fab.configure(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)), budget=TestBudget()
    )
    handle = fab.FileHandle(
        printer_id="prusa-1", name="p.gcode", remote_path="usb/p.gcode", size_bytes=1
    )
    job = await fab.start(handle, "prusa-1", "approval-abc")

    assert job.job_id == "42" and job.approval_token == "approval-abc"  # noqa: S105 - a test token, not a secret
    assert seen["url"] == "http://printer.local/api/v1/job"  # SPEC 6.4
    assert seen["key"] == "k"
    assert "approval" not in json.dumps(seen["body"])  # token never leaves the lab


# --- SPEC 13.3: the limits block is closed to evolution ----------------------


async def test_genome_write_then_read_roundtrip(genome_dir):
    result = await genome.write(dict(BASE_GENOME))
    assert result.hash and len(result.hash) == genome.HASH_LENGTH
    stored = await genome.read("quadruped_v2")
    assert stored["hash"] == result.hash
    assert stored["limits"] == BASE_GENOME["limits"]


async def test_genome_write_refuses_a_limits_change(genome_dir):
    await genome.write(dict(BASE_GENOME))
    loosened = json.loads(json.dumps(BASE_GENOME))
    loosened["limits"]["joint_torque_nm_max"] = 4.0
    with pytest.raises(genome.LimitsLocked):
        await genome.write(loosened)
    on_disk = yaml.safe_load((genome_dir / "quadruped_v2.yaml").read_text(encoding="utf-8"))
    assert on_disk["limits"]["joint_torque_nm_max"] == 2.5


async def test_genome_child_cannot_loosen_inherited_limits(genome_dir):
    parent = await genome.write(dict(BASE_GENOME))
    child = json.loads(json.dumps(BASE_GENOME))
    child["genome_id"] = "quadruped_v3"
    child["parent"] = f"quadruped_v2@{parent.hash}"
    child["limits"]["body_current_a_max"] = 30.0
    with pytest.raises(genome.LimitsLocked):
        await genome.write(child)

    child["limits"] = dict(BASE_GENOME["limits"])
    await genome.write(child)
    assert [g["genome_id"] for g in await genome.lineage("quadruped_v3")] == [
        "quadruped_v3",
        "quadruped_v2",
    ]


async def test_genome_write_refuses_schema_violation(genome_dir):
    broken = {"schema_version": 1, "genome_id": "bad"}  # no limits block
    with pytest.raises(genome.GenomeInvalid):
        await genome.write(broken)
