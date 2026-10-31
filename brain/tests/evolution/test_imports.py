# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""GitHub imports: what is accepted, what is refused, and how an imported item reaches the scene."""

from __future__ import annotations

import asyncio
import json
import struct

import pytest
import yaml

from neml_brain.evolution.imports import (
    GithubImporter,
    ImportRejected,
    classify,
    clean,
    parse_repo,
    summarize_urdf,
    to_binary_stl,
)
from neml_brain.evolution.model_scene import build_scene
from neml_brain.paths import REPO_ROOT


def test_repository_addresses_are_parsed_and_anything_else_is_refused():
    assert parse_repo("https://github.com/a-b/c.d") == ("a-b", "c.d", None)
    assert parse_repo("owner/name/tree/dev/x") == ("owner", "name", "dev/x")
    for bad in (
        "http://evil.example/o/r",
        "o/r/../../etc",
        "../x",
        "o",
        "https://github.com/o/r?x=1",
    ):
        with pytest.raises(ImportRejected):
            parse_repo(bad)


def test_only_the_known_design_file_kinds_are_importable_and_text_is_cleaned():
    assert [classify(p) for p in ("a.STL", "b.step", "c.stp", "d.kicad_pcb", "e.py", "f.sh")] == [
        "stl",
        "step",
        "step",
        "kicad_pcb",
        None,
        None,
    ]
    assert clean("Evil <script>alert(1)</script> name") == "Evil scriptalert(1)script name"


def _binary_stl(path, triangles=1):
    data = bytearray(80) + struct.pack("<I", triangles)
    for _ in range(triangles):
        data += struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
    path.write_bytes(bytes(data))


def test_a_truncated_or_fake_stl_is_refused_and_a_good_one_passes(tmp_path):
    good = tmp_path / "good.stl"
    _binary_stl(good, 3)
    assert to_binary_stl(good) == good
    bad = tmp_path / "bad.stl"
    bad.write_bytes(good.read_bytes()[:-10])
    with pytest.raises(ImportRejected, match="geçerli"):
        to_binary_stl(bad)


def test_a_urdf_with_entities_is_refused_and_a_plain_one_is_summarised(tmp_path):
    evil = tmp_path / "evil.urdf"
    evil.write_text('<!DOCTYPE r [<!ENTITY a "x">]><robot name="&a;"/>', encoding="utf-8")
    with pytest.raises(ImportRejected, match="entity"):
        summarize_urdf(evil)
    ok = tmp_path / "ok.urdf"
    ok.write_text(
        '<robot name="dog"><link name="a"/><link name="b"/>'
        '<joint name="j" type="revolute"><parent link="a"/><child link="b"/></joint></robot>',
        encoding="utf-8",
    )
    assert summarize_urdf(ok) == {
        "robot": "dog",
        "links": 2,
        "joints": 1,
        "movable_joints": 1,
        "meshes": [],
    }


class FakeMcp:
    def __init__(self):
        self.calls = []

    async def call(self, server, tool, args, timeout=None):
        self.calls.append((server, tool, args))
        url = args["url"]
        if url.endswith("/repos/o/r"):
            return {
                "text": json.dumps(
                    {
                        "default_branch": "main",
                        "license": {"spdx_id": "MIT", "name": "MIT License"},
                        "description": "d",
                        "stargazers_count": 5,
                    }
                )
            }
        return {
            "text": json.dumps(
                {
                    "tree": [
                        {"path": "cad/leg.stl", "type": "blob", "size": 1000},
                        {"path": "cad/huge.stl", "type": "blob", "size": 99_000_000},
                        {"path": "src/run.py", "type": "blob", "size": 10},
                        {"path": "pcb/b.kicad_pcb", "type": "blob", "size": 5000},
                    ]
                }
            )
        }


def _importer(tmp_path):
    return GithubImporter(FakeMcp(), None, None, None, tmp_path)


def test_scanning_lists_only_design_files_with_the_licence_and_flags_oversize_ones(tmp_path):
    info = asyncio.run(_importer(tmp_path).scan("o/r"))
    assert info["license"] == {"spdx": "MIT", "name": "MIT License"} and info["branch"] == "main"
    assert [(f["path"], f["kind"], f["too_big"]) for f in info["files"]] == [
        ("cad/huge.stl", "stl", True),
        ("cad/leg.stl", "stl", False),
        ("pcb/b.kicad_pcb", "kicad_pcb", False),
    ]


def test_importing_needs_the_licence_ack_a_target_and_files_that_exist_in_the_repo(tmp_path):
    imp = _importer(tmp_path)

    def run(**kw):
        return asyncio.run(
            imp.import_files(
                **{
                    "repo_text": "o/r",
                    "branch": "main",
                    "paths": ["cad/leg.stl"],
                    "ack": True,
                    "genome_id": None,
                    "new_name": "x",
                    "actor": "t",
                    **kw,
                }
            )
        )

    with pytest.raises(ImportRejected, match="Lisans"):
        run(ack=False)
    with pytest.raises(ImportRejected, match="ad ya da"):
        run(new_name="")
    with pytest.raises(ImportRejected, match="içe aktarılabilir"):
        run(paths=["src/run.py"])
    with pytest.raises(ImportRejected, match="çok büyük"):
        run(paths=["cad/huge.stl"])
    with pytest.raises(ImportRejected, match="1 ile"):
        run(paths=[])


def _body():
    return yaml.safe_load(
        (REPO_ROOT / "hardware/genome/quadruped_v2.yaml").read_text(encoding="utf-8")
    )


ENTRY = {
    "id": "imp_abc123_0",
    "kind": "stl",
    "name": "leg",
    "repo": "o/r",
    "license": "MIT",
    "source": "https://github.com/o/r/blob/main/cad/leg.stl",
    "sha256": "ab" * 32,
    "urls": {"stl": "u/leg.stl"},
    "size": [10.0, 20.0, 30.0],
    "center": [5.0, 6.0, 7.0],
}


def test_an_imported_workspace_scene_holds_only_the_imported_parts_with_source_rows():
    body = _body()
    body["morphology"]["body_type"] = "imported"
    body["mechanical"]["imports"] = [ENTRY]
    scene = build_scene("g", body, {})
    assert [p["id"] for p in scene["parts"]] == ["imp_abc123_0"]
    part = scene["parts"][0]
    assert (
        part["group"] == "ithal"
        and part["pos"] == [5.0, 6.0, 7.0]
        and part["geom"]["size"] == [10.0, 20.0, 30.0]
    )
    assert scene["fit"]["ok"] and scene["imports"][0]["license"] == "MIT"
    assert scene["bom"][0]["links"][0]["url"].startswith("https://github.com/")


def test_imports_make_the_scene_and_the_bill_of_materials_of_the_model():
    body = _body()
    body["mechanical"]["imports"] = [ENTRY]
    scene = build_scene("g", body, {})
    assert len(scene["parts"]) == 1 and scene["fit"]["ok"]
    assert any(r["spec"].startswith("o/r") for r in scene["bom"])


def test_a_whole_repository_takes_every_importable_file_within_the_caps_and_says_what_it_left(
    tmp_path,
):
    imp = _importer(tmp_path)
    full = asyncio.run(imp._scan_full("o/r"))  # noqa: SLF001
    chosen, skipped = imp._choose(full, [], True)  # noqa: SLF001
    assert [f["path"] for f in chosen] == ["cad/leg.stl", "pcb/b.kicad_pcb"]
    assert skipped == ["cad/huge.stl (çok büyük)"]
    assert full["overview"]["files"] == 4 and full["overview"]["importable"] == 3
    with pytest.raises(ImportRejected, match="tüm repoyu"):
        imp._choose(full, [], False)  # noqa: SLF001


def test_upper_case_extensions_are_copied_to_the_lower_case_name_the_media_store_accepts(tmp_path):
    from neml_brain.evolution.imports import lower_suffix

    upper = tmp_path / "part.STL"
    upper.write_bytes(b"abc")
    low = lower_suffix(upper, ".stl")
    assert low.name.lower() == "part.stl" and low.read_bytes() == b"abc"
    assert lower_suffix(low, ".stl") == low


def test_an_obj_is_converted_to_a_binary_stl_with_fanned_faces_and_bad_ones_are_refused(tmp_path):
    from neml_brain.evolution.imports import obj_to_stl
    from neml_brain.evolution.model_scene import stl_bounds

    obj = tmp_path / "cube.obj"
    obj.write_text(
        "v 0 0 0\nv 2 0 0\nv 2 3 0\nv 0 3 0\nf 1 2 3 4\nf -4/1/1 -3 -2\n", encoding="utf-8"
    )
    stl = obj_to_stl(obj)
    assert struct.unpack("<I", stl.read_bytes()[80:84])[0] == 3  # a quad is two triangles, plus one
    lo, hi = stl_bounds(stl)
    assert list(hi - lo) == [2.0, 3.0, 0.0]
    bad = tmp_path / "bad.obj"
    bad.write_text("v 0 0 0\nf 1 2 3\n", encoding="utf-8")
    with pytest.raises(ImportRejected, match="OBJ"):
        obj_to_stl(bad)


def test_includes_resolve_next_to_the_including_file_or_by_package_name_and_never_climb_out():
    from neml_brain.evolution.imports import include_candidates

    paths = [
        "robot/urdf/main.xacro",
        "robot/urdf/macros.xacro",
        "other/macros.xacro",
        "robot/meshes/a.stl",
    ]
    assert (
        include_candidates("macros.xacro", "robot/urdf/main.xacro", paths)[0]
        == "robot/urdf/macros.xacro"
    )
    assert "robot/urdf/macros.xacro" in include_candidates(
        "package://pkg/urdf/macros.xacro", "x.xacro", paths
    )
    assert include_candidates("../../etc/passwd", "robot/urdf/main.xacro", paths) == []
    assert include_candidates("", "a", paths) == []


class FakeReader:
    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = 0

    async def fill(self, prompt, schema, profile=None):
        self.asked += 1
        return self.answers.pop(0)


def test_the_models_reading_of_a_repository_is_asked_again_when_it_comes_back_in_chinese(tmp_path):
    from collections import Counter

    full = {
        "repo": "o/r",
        "description": "d",
        "overview": {"files": 1, "by_ext": {}, "dirs": [], "sample": []},
    }
    good = {
        "title": "Robot",
        "category": "robot",
        "summary": "Dört bacaklı robot.",
        "steps": ["Parçaları bas."],
    }
    chinese = {"title": "机器人", "category": "robot", "summary": "这是一个机器人", "steps": []}
    imp = GithubImporter(None, None, None, None, tmp_path, FakeReader([chinese, good]))
    got = asyncio.run(imp._analyze(full, "readme", Counter()))  # noqa: SLF001
    assert got["summary"] == "Dört bacaklı robot." and imp._llm.asked == 2  # noqa: SLF001
    stubborn = GithubImporter(None, None, None, None, tmp_path, FakeReader([chinese, chinese]))
    assert asyncio.run(stubborn._analyze(full, "readme", Counter())) is None  # noqa: SLF001


def test_a_refresh_reads_the_branch_and_files_back_from_the_entries_sources():
    from neml_brain.evolution.imports import refresh_request

    entries = [
        {
            "kind": "stl",
            "source": "https://github.com/o/r/blob/dev/cad/leg%20one.stl",
            "branch": "dev",
        },
        {"kind": "kicad", "source": "https://github.com/o/r/blob/dev/pcb/b.kicad_pcb"},
        {"kind": "urdf", "source": "https://github.com/o/r/blob/dev/robot.urdf.xacro"},
        {"kind": "repo", "source": "https://github.com/o/r"},
    ]
    branch, paths = refresh_request(entries)
    assert branch == "dev"
    assert paths == ["cad/leg one.stl", "pcb/b.kicad_pcb", "pcb/b.kicad_sch", "robot.urdf.xacro"]
    assert refresh_request([{"kind": "repo", "source": "https://github.com/o/r"}]) == ("", [])


def test_poses_are_kept_per_model_validated_and_deletable(tmp_path):
    from neml_brain.evolution.poses import PoseRejected, PoseStore

    store = PoseStore(tmp_path)
    assert store.list("spot") == {}
    assert store.save("spot", "stand", {"hip": 0.5, "knee": -1.0}) == {
        "stand": {"hip": 0.5, "knee": -1.0}
    }
    store.save("spot", "sit", {"hip": 1})
    assert sorted(store.list("spot")) == ["sit", "stand"] and store.list("other") == {}
    assert store.delete("spot", "sit") == {"stand": {"hip": 0.5, "knee": -1.0}}
    for bad in (
        ("../x", "p", {}),
        ("spot", "", {}),
        ("spot", "p", {"j": float("nan")}),
        ("spot", "p", {"j": "1"}),
        ("spot", "p", [1]),
    ):
        with pytest.raises(PoseRejected):
            store.save(*bad)


def test_a_github_rate_limit_is_explained_not_reported_as_an_unreachable_repository(tmp_path):
    class Limited:
        async def call(self, server, tool, args, timeout=None):
            return {
                "status": 403,
                "text": json.dumps({"message": "API rate limit exceeded for 1.2.3.4"}),
            }

    imp = GithubImporter(Limited(), None, None, None, tmp_path)
    with pytest.raises(ImportRejected, match="rate limit exceeded.*NEML_GITHUB_TOKEN"):
        asyncio.run(imp.scan("o/r"))
