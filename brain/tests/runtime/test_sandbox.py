# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""T-015 / SPEC 5.3. No Docker here: the runner is injected."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from neml_brain.runtime.sandbox import RunResult, Sandbox, scan_banned_calls

BANNED_SNIPPETS = [
    ("os.system", "import os\nos.system('rm -rf /')\n"),
    ("from os import system", "from os import system\nsystem('ls')\n"),
    ("eval", "eval('1+1')\n"),
    ("exec", "exec('x=1')\n"),
    ("__import__", "__import__('os')\n"),
    ("socket", "import socket\ns = socket.socket()\n"),
    ("socket from", "from socket import create_connection\n"),
    ("ctypes", "import ctypes\n"),
    ("subprocess import", "from subprocess import run\nrun(['gz'])\n"),
    ("subprocess not allowlisted", "import subprocess\nsubprocess.run(['curl', 'x'])\n"),
    ("subprocess dynamic", "import subprocess\nsubprocess.run(cmd)\n"),
    ("subprocess shell", "import subprocess\nsubprocess.run(['gz'], shell=True)\n"),
]
CLEAN_SNIPPETS = [
    ("allowlisted tool", "import subprocess\nsubprocess.run(['prusa-slicer', '--help'])\n"),
    ("plain maths", "def area(w: float, h: float) -> float:\n    return w * h\n"),
    ("no false positive on a string", "msg = 'do not eval this'\n"),
]


@pytest.mark.parametrize(("name", "src"), BANNED_SNIPPETS, ids=[n for n, _ in BANNED_SNIPPETS])
def test_banned_calls_are_caught(name: str, src: str) -> None:
    assert scan_banned_calls(src), f"{name} slipped through"


@pytest.mark.parametrize(("name", "src"), CLEAN_SNIPPETS, ids=[n for n, _ in CLEAN_SNIPPETS])
def test_clean_code_passes(name: str, src: str) -> None:
    assert scan_banned_calls(src) == []


def test_unparsable_source_is_a_violation() -> None:
    assert scan_banned_calls("def (:\n")


class FakeRunner:
    def __init__(self, *results: RunResult) -> None:
        self.calls: list[list[str]] = []
        self._results = list(results)

    async def __call__(self, argv: Sequence[str], timeout_s: float) -> RunResult:
        self.calls.append(list(argv))
        self.timeout_s = timeout_s
        return self._results.pop(0) if self._results else RunResult(0)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "gen.py").write_text("VALUE = 1\n", encoding="utf-8")
    return tmp_path


async def test_banned_call_blocks_before_any_tool_runs(work: Path) -> None:
    (work / "evil.py").write_text("import socket\n", encoding="utf-8")
    runner = FakeRunner()
    result = await Sandbox(runner).run(work, ["python", "gen.py"])
    assert not result.ok
    assert result.stage == "banned_calls"
    assert runner.calls == [], "nothing runs, not even ruff"


@pytest.mark.parametrize(("stage", "index"), [("ruff", 0), ("mypy", 1), ("bandit", 2)])
async def test_static_failure_stops_before_the_container(
    work: Path, stage: str, index: int
) -> None:
    results = [RunResult(0), RunResult(0), RunResult(0)]
    results[index] = RunResult(1, stdout=f"{stage} said no")
    runner = FakeRunner(*results)
    result = await Sandbox(runner).run(work, ["python", "gen.py"])
    assert not result.ok
    assert result.stage == stage
    assert len(runner.calls) == index + 1
    assert all(call[0] != "docker" for call in runner.calls)


async def test_static_order_is_ruff_mypy_bandit(work: Path) -> None:
    runner = FakeRunner()
    await Sandbox(runner).run(work, ["python", "gen.py"])
    assert [call[0] for call in runner.calls] == ["ruff", "mypy", "bandit", "docker"]
    assert runner.calls[1][:2] == ["mypy", "--strict"]


async def test_container_flags_match_spec_5_3(work: Path) -> None:
    runner = FakeRunner()
    await Sandbox(runner).run(work, ["python", "gen.py"])
    argv = runner.calls[-1]
    assert argv[:3] == ["docker", "run", "--rm"]
    for flag, value in (
        ("--network", "none"),
        ("--cpus", "2.0"),
        ("--memory", "2g"),
        ("--pids-limit", "256"),
        ("--user", "1000:1000"),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges:true"),
        ("--volume", f"{work}:/work"),
    ):
        assert argv[argv.index(flag) + 1] == value, flag
    assert "--read-only" in argv
    assert argv[argv.index("neml/sandbox:1.0") + 1 :] == ["python", "gen.py"]
    assert runner.timeout_s == 180.0


async def test_timeout_is_a_failure(work: Path) -> None:
    runner = FakeRunner(RunResult(0), RunResult(0), RunResult(0), RunResult(124, timed_out=True))
    result = await Sandbox(runner).run(work, ["python", "slow.py"])
    assert not result.ok
    assert result.run is not None and result.run.timed_out


async def test_happy_path(work: Path) -> None:
    runner = FakeRunner(RunResult(0), RunResult(0), RunResult(0), RunResult(0, stdout="done"))
    result = await Sandbox(runner).run(work, ["python", "gen.py"])
    assert result.ok
    assert result.stage == "container"
    assert result.run is not None and result.run.stdout == "done"


@pytest.mark.integration
async def test_real_container_has_no_network(tmp_path: Path) -> None:
    """Needs Docker and neml/sandbox:1.0. T-015: the network attempt must fail."""
    (tmp_path / "net.py").write_text(
        "import urllib.request\nurllib.request.urlopen('http://1.1.1.1', timeout=5)\n",
        encoding="utf-8",
    )
    sandbox = Sandbox()
    result = await sandbox._runner(  # noqa: SLF001 - static gate bans the probe on purpose
        sandbox.docker_argv(tmp_path, ["python", "net.py"]), 60.0
    )
    assert result.rc != 0
