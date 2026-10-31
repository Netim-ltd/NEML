# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-genome - hardware genome store, port 9103 (SPEC 6.2 #12, SPEC 13.3).

Hard rule, enforced here in code and not by a prompt: the `limits` block is
closed to evolution. Any write that changes it - against the stored genome or
against the parent it claims - is refused.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from mcp_servers._common import make_app

PORT = 9103
VERSION = "1.0.0"
DEFAULT_TIMEOUT_S = 30.0
REPO_ROOT = Path(__file__).resolve().parents[2]
LOCKED_BLOCK = "limits"  # SPEC 13.3
HASH_LENGTH = 7  # SPEC 13.3 example: a3f91c7
MAX_LINEAGE_DEPTH = 64


class GenomeError(RuntimeError):
    """Base typed error for every genome entry point."""


class GenomeNotFound(GenomeError):
    """No genome file for that id."""


class GenomeInvalid(GenomeError):
    """Genome does not satisfy hardware/genome/genome.schema.json."""


class LimitsLocked(GenomeError):
    """SPEC 13.3: the limits block is closed to evolution."""


@dataclass
class WriteResult:
    genome_id: str
    hash: str
    path: str
    parent: str | None


@dataclass
class ValidationResult:
    valid: bool
    hash: str
    errors: list[str]


@dataclass
class _State:
    genome_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("NEML_GENOME_DIR", REPO_ROOT / "hardware" / "genome")
        )
    )


_S = _State()


def configure(genome_dir: Path | None = None) -> None:
    if genome_dir is not None:
        _S.genome_dir = Path(genome_dir)


def _schema() -> dict[str, Any]:
    path = _S.genome_dir / "genome.schema.json"
    if not path.is_file():
        raise GenomeError(f"genome schema not found: {path}")
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _path(genome_id: str) -> Path:
    if "/" in genome_id or "\\" in genome_id or genome_id.startswith("."):
        raise GenomeError(f"illegal genome id '{genome_id}'")
    return _S.genome_dir / f"{genome_id}.yaml"


def _load(genome_id: str) -> dict[str, Any]:
    path = _path(genome_id)
    if not path.is_file():
        raise GenomeNotFound(f"genome '{genome_id}' not found at {path}")
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def content_hash(genome: dict[str, Any]) -> str:
    """SPEC 13.3: derived from the content, with the hash field itself excluded."""
    body = {k: v for k, v in genome.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:HASH_LENGTH]


def _parent_id(genome: dict[str, Any]) -> str | None:
    parent = genome.get("parent")
    if not parent:
        return None
    return str(parent).split("@", 1)[0]


def _check_limits_unchanged(new: dict[str, Any], old: dict[str, Any], origin: str) -> None:
    if new.get(LOCKED_BLOCK) != old.get(LOCKED_BLOCK):
        raise LimitsLocked(
            f"write refused: '{LOCKED_BLOCK}' differs from {origin}; "
            "SPEC 13.3 keeps this block closed to evolution"
        )


# --- tools ------------------------------------------------------------------


async def read(genome_id: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Read one genome by id."""
    del timeout_s  # local file read; the argument keeps the no-unbounded-call rule
    return _load(genome_id)


async def validate(
    genome: dict[str, Any], timeout_s: float = DEFAULT_TIMEOUT_S
) -> ValidationResult:
    """Validate against hardware/genome/genome.schema.json and hash the content."""
    del timeout_s
    validator = jsonschema.Draft202012Validator(_schema())
    errors = [
        f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in validator.iter_errors(genome)
    ]
    return ValidationResult(valid=not errors, hash=content_hash(genome), errors=errors)


async def write(genome: dict[str, Any], timeout_s: float = DEFAULT_TIMEOUT_S) -> WriteResult:
    """Write a genome. Refuses schema violations and any limits change."""
    del timeout_s
    genome_id = str(genome.get("genome_id") or "")
    if not genome_id:
        raise GenomeInvalid("genome_id is required")
    result = await validate(genome)
    if not result.valid:
        raise GenomeInvalid("; ".join(result.errors))

    path = _path(genome_id)
    if path.is_file():
        _check_limits_unchanged(genome, _load(genome_id), f"the stored '{genome_id}'")
    parent = _parent_id(genome)
    if parent:
        # A child may not loosen the limits it inherits (SPEC 13.3).
        _check_limits_unchanged(genome, _load(parent), f"parent '{parent}'")

    stored = dict(genome)
    stored["hash"] = result.hash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(stored, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return WriteResult(
        genome_id=genome_id, hash=result.hash, path=str(path), parent=genome.get("parent")
    )


async def diff(
    genome_id_a: str, genome_id_b: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> dict[str, Any]:
    """Flat dotted-path diff between two stored genomes."""
    del timeout_s
    left, right = _flatten(_load(genome_id_a)), _flatten(_load(genome_id_b))
    return {
        "a": genome_id_a,
        "b": genome_id_b,
        "added": sorted(set(right) - set(left)),
        "removed": sorted(set(left) - set(right)),
        "changed": {
            k: [left[k], right[k]] for k in sorted(set(left) & set(right)) if left[k] != right[k]
        },
        "limits_changed": any(
            k.startswith(LOCKED_BLOCK + ".")
            for k in set(left) | set(right)
            if left.get(k) != right.get(k)
        ),
    }


async def lineage(genome_id: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> list[dict[str, Any]]:
    """Walk parent links from this genome back to the root (SPEC 13.3)."""
    del timeout_s
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = genome_id
    while current and current not in seen and len(out) < MAX_LINEAGE_DEPTH:
        seen.add(current)
        genome = _load(current)
        out.append(
            {
                "genome_id": genome.get("genome_id", current),
                "hash": genome.get("hash"),
                "parent": genome.get("parent"),
                "status": genome.get("status"),
                "created": str(genome.get("created", "")),
            }
        )
        current = _parent_id(genome)
    return out


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}{key}."))
        return out
    return {prefix.rstrip("."): node}


TOOLS: dict[str, Callable[..., Any]] = {
    "read": read,
    "write": write,
    "validate": validate,
    "diff": diff,
    "lineage": lineage,
}

app = make_app("neml-mcp-genome", VERSION, TOOLS)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
