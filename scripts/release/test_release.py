# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the release tooling (SPEC 0.6)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import release


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "brain" / "neml_brain").mkdir(parents=True)
    (tmp_path / "brain" / "neml_brain" / "__init__.py").write_text(
        '__version__ = "0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "dotnet").mkdir()
    (tmp_path / "dotnet" / "Directory.Build.props").write_text(
        "<Project>\n  <PropertyGroup>\n    <LangVersion>latest</LangVersion>\n"
        "  </PropertyGroup>\n</Project>\n",
        encoding="utf-8",
    )
    (tmp_path / "mobile").mkdir()
    (tmp_path / "mobile" / "pubspec.yaml").write_text(
        "name: neml_mobile\nversion: 1.0.0+1\n", encoding="utf-8"
    )
    return tmp_path


def test_stamp_writes_all_three(tree: Path) -> None:
    changed = release.stamp("1.2.0", build=7, root=tree)
    assert all(changed.values())
    assert '__version__ = "1.2.0"' in (tree / "brain/neml_brain/__init__.py").read_text()
    assert "<Version>1.2.0</Version>" in (tree / "dotnet/Directory.Build.props").read_text()
    assert "version: 1.2.0+7" in (tree / "mobile/pubspec.yaml").read_text()


def test_stamp_is_idempotent(tree: Path) -> None:
    release.stamp("1.2.0", build=7, root=tree)
    assert release.stamp("1.2.0", build=7, root=tree) == {
        "brain/neml_brain/__init__.py": False,
        "dotnet/Directory.Build.props": False,
        "mobile/pubspec.yaml": False,
    }


def test_check_does_not_touch_the_tree(tree: Path) -> None:
    before = (tree / "mobile/pubspec.yaml").read_text()
    assert any(release.stamp("9.9.9", root=tree, write=False).values())
    assert (tree / "mobile/pubspec.yaml").read_text() == before


def test_stamp_keeps_the_build_number_when_not_given(tree: Path) -> None:
    release.stamp("1.2.0", root=tree)
    assert "version: 1.2.0+1" in (tree / "mobile/pubspec.yaml").read_text()


def test_stamp_rejects_a_non_semver(tree: Path) -> None:
    with pytest.raises(SystemExit):
        release.stamp("v1.2", root=tree)


def test_manifest_records_hash_and_build_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "git_commit", lambda root=None: "c0ffee")
    apk = tmp_path / "neml.apk"
    apk.write_bytes(b"binary")

    entry = release.manifest("1.2.0", [apk], root=tmp_path)["artifacts"][0]
    assert entry["sha256"] == hashlib.sha256(b"binary").hexdigest()
    assert entry["source"] == "deterministic-build"
    assert entry["input_hash"] == "c0ffee"  # SPEC 0.6: the input is the commit
    assert entry["model"] is None and entry["seed"] is None


def test_manifest_reads_the_provenance_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "git_commit", lambda root=None: "c0ffee")
    part = tmp_path / "hardware" / "exports" / "leg_link_v1.3mf"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"3mf")
    part.with_suffix(".3mf.provenance.json").write_text(
        json.dumps(
            {
                "model": "Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ",
                "prompt_hash": "aaa",
                "seed": 42,
                "input_hash": "bbb",
            }
        ),
        encoding="utf-8",
    )

    entry = release.manifest("1.2.0", [part], root=tmp_path)["artifacts"][0]
    assert entry["source"] == "generated"
    assert entry["seed"] == 42
    assert entry["model"].endswith("AWQ")


def test_generated_artefact_without_a_record_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC 0.6: an artefact with no origin record is invalid."""
    monkeypatch.setattr(release, "git_commit", lambda root=None: "c0ffee")
    part = tmp_path / "hardware" / "exports" / "orphan.stl"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"stl")

    with pytest.raises(SystemExit, match="0.6"):
        release.manifest("1.2.0", [part], root=tmp_path)


def test_incomplete_sidecar_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "git_commit", lambda root=None: "c0ffee")
    part = tmp_path / "hardware" / "exports" / "half.stl"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"stl")
    part.with_suffix(".stl.provenance.json").write_text(
        json.dumps({"model": "m", "prompt_hash": "p", "seed": 1}), encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="input_hash"):
        release.manifest("1.2.0", [part], root=tmp_path)
