# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for neml-mcp-genome (SPEC 6.2 #12, SPEC 13.3).

The rule this server exists to enforce: the `limits` block is closed to
evolution. It must be refused in code, both against the stored genome and
against the parent a child claims.
"""

from __future__ import annotations

import asyncio
import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from mcp_servers.neml_mcp_genome import server

REPO_ROOT = Path(__file__).resolve().parents[2]


def call(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def genome_dir(tmp_path: Path) -> Path:
    """A scratch copy of the real schema plus the SPEC 13.3 seed genome."""
    src = REPO_ROOT / "hardware" / "genome"
    shutil.copy(src / "genome.schema.json", tmp_path / "genome.schema.json")
    shutil.copy(src / "quadruped_v2.yaml", tmp_path / "quadruped_v2.yaml")
    server.configure(genome_dir=tmp_path)
    return tmp_path


def read_yaml(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_seed_genome_validates_against_its_schema(genome_dir: Path) -> None:
    result = call(server.validate(read_yaml(genome_dir / "quadruped_v2.yaml")))
    assert result.valid, result.errors
    assert len(result.hash) == server.HASH_LENGTH


def test_write_refuses_a_limits_change_against_the_stored_genome(genome_dir: Path) -> None:
    genome = read_yaml(genome_dir / "quadruped_v2.yaml")
    genome["limits"]["joint_torque_nm_max"] = 4.0  # schema-legal, still a limits change

    with pytest.raises(server.LimitsLocked):
        call(server.write(genome))

    # and the stored file is untouched
    assert read_yaml(genome_dir / "quadruped_v2.yaml")["limits"]["joint_torque_nm_max"] == 2.5


def test_write_refuses_a_child_that_loosens_its_parent_limits(genome_dir: Path) -> None:
    child = read_yaml(genome_dir / "quadruped_v2.yaml")
    child["genome_id"] = "quadruped_v3"
    child["parent"] = "quadruped_v2@a3f91c7"
    child["limits"]["body_current_a_max"] = 40.0

    with pytest.raises(server.LimitsLocked):
        call(server.write(child))
    assert not (genome_dir / "quadruped_v3.yaml").is_file()


def test_write_accepts_a_child_that_keeps_the_limits(genome_dir: Path) -> None:
    child = read_yaml(genome_dir / "quadruped_v2.yaml")
    child["genome_id"] = "quadruped_v3"
    child["parent"] = "quadruped_v2@a3f91c7"
    child["mechanical"]["body_mass_kg"] = 2.55

    result = call(server.write(child))

    stored = read_yaml(genome_dir / "quadruped_v3.yaml")
    assert stored["hash"] == result.hash
    assert stored["limits"] == child["limits"]


def test_write_refuses_a_schema_violation(genome_dir: Path) -> None:
    genome = read_yaml(genome_dir / "quadruped_v2.yaml")
    genome["morphology"]["leg_count"] = "four"
    with pytest.raises(server.GenomeInvalid):
        call(server.write(genome))


def test_content_hash_ignores_the_hash_field(genome_dir: Path) -> None:
    genome = read_yaml(genome_dir / "quadruped_v2.yaml")
    without = copy.deepcopy({k: v for k, v in genome.items() if k != "hash"})
    assert server.content_hash(genome) == server.content_hash(without)
    genome["morphology"]["leg_count"] = 6
    assert server.content_hash(genome) != server.content_hash(without)


def test_id_traversal_is_refused(genome_dir: Path) -> None:
    for bad in ("../etc/passwd", "a/b", ".hidden"):
        with pytest.raises(server.GenomeError):
            call(server.read(bad))


def test_missing_genome_is_a_typed_error(genome_dir: Path) -> None:
    with pytest.raises(server.GenomeNotFound):
        call(server.read("quadruped_v9"))


def test_diff_flags_a_limits_change(genome_dir: Path) -> None:
    other = read_yaml(genome_dir / "quadruped_v2.yaml")
    other["genome_id"] = "quadruped_v4"
    other["limits"]["body_temp_c_max"] = 65.0
    (genome_dir / "quadruped_v4.yaml").write_text(yaml.safe_dump(other), encoding="utf-8")

    result = call(server.diff("quadruped_v2", "quadruped_v4"))

    assert result["limits_changed"] is True
    assert result["changed"]["limits.body_temp_c_max"] == [70.0, 65.0]


def test_lineage_walks_back_to_the_root(genome_dir: Path) -> None:
    root = read_yaml(genome_dir / "quadruped_v2.yaml")
    root["genome_id"] = "quadruped_v1"
    root.pop("parent")
    (genome_dir / "quadruped_v1.yaml").write_text(yaml.safe_dump(root), encoding="utf-8")

    chain = call(server.lineage("quadruped_v2"))

    assert [g["genome_id"] for g in chain] == ["quadruped_v2", "quadruped_v1"]


def test_schema_file_is_valid_json(genome_dir: Path) -> None:
    json.loads((genome_dir / "genome.schema.json").read_text(encoding="utf-8"))
