# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Doubles for every injected dependency. No live PostgreSQL, no live vLLM: the
# graph takes its checkpointer and its Deps from the caller, so the tests just
# hand it fakes.

import sys
from pathlib import Path

import pytest

# ponytail: keeps a bare `pytest` working next to `python -m pytest`; drop it
# once CI always installs the package with `uv pip install -e brain`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from neml_brain.agents.base import Deps  # noqa: E402

VALID_MECH = {
    "part_name": "leg_bar",
    "recipe": {
        "solids": [{"id": "bar", "t": "box", "at": [0, 0, 0], "size": [120, 20, 20]}],
        "steps": [],
        "result": "bar",
    },
    "rationale": "test",
}


class FakeLLM:
    """SPEC 4.7 LLMProvider double. classify/fill are constrained upstream."""

    def __init__(self, intent="explain", params=None, summary="summary"):
        self.intent = intent
        self.params = params or {}
        self.summary = summary
        self.prompts: list[str] = []
        self.profiles: list[str] = []
        self.schemas: list[dict] = []
        self.calls = {"classify": 0, "fill": 0, "summarize": 0}

    async def classify(self, prompt, choices, profile="router"):
        self.calls["classify"] += 1
        self.prompts.append(prompt)
        self.profiles.append(profile)
        assert self.intent in choices, "the model may only emit a declared choice"
        return self.intent

    async def fill(self, prompt, schema):
        self.calls["fill"] += 1
        self.prompts.append(prompt)
        self.schemas.append(schema)
        return self.params

    async def summarize(self, prompt, max_tokens):
        self.calls["summarize"] += 1
        self.prompts.append(prompt)
        return self.summary


class FakeMcp:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool, params):
        self.calls.append((tool, params))
        return self.results.get(tool, {"ok": True})

    def tools(self):
        return [tool for tool, _ in self.calls]


class FakeDb:
    def __init__(self):
        self.audits: list[dict] = []
        self.persisted: list[dict] = []
        self.approvals: dict[str, str] = {}
        self.create_calls = 0

    async def audit(self, **row):
        self.audits.append(row)

    async def query(self, **_):
        return [{"id": "r1"}]

    async def task_op(self, **_):
        return {"task_id": "t1"}

    async def campaign_op(self, **kw):
        self.campaigns = [*getattr(self, "campaigns", []), kw]
        return {"ok": True, "campaign": {"id": "c1"}}

    async def persist(self, snapshot):
        self.persisted.append(snapshot)

    async def create_approval(self, *, level, subject_kind, subject_id, payload, idempotency_key):
        # Idempotent: the APPROVAL node replays from the top when a human
        # resumes the interrupt, so a second call must not open a second row.
        self.create_calls += 1
        return self.approvals.setdefault(idempotency_key, f"apr-{len(self.approvals) + 1}")


class FakeGpu:
    """SPEC 4.5 GpuLock double. Records the acquire/release pairs."""

    def __init__(self):
        self.events: list[tuple] = []
        self.held = 0

    async def acquire(self, consumer, timeout_s=300, *, profile="fast"):
        self.held += 1
        self.events.append(("acquire", consumer, profile))

    async def release(self, consumer):
        self.held -= 1
        self.events.append(("release", consumer))


class FakeSandbox:
    def __init__(self, ok=True):
        self.ok = ok
        self.runs: list[tuple] = []

    async def run(self, target, source, command):
        self.runs.append((target, source, tuple(command)))
        return {"ok": self.ok, "exit_code": 0 if self.ok else 1}


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def mcp():
    return FakeMcp()


@pytest.fixture
def db():
    return FakeDb()


@pytest.fixture
def gpu():
    return FakeGpu()


@pytest.fixture
def deps(llm, mcp, db, gpu):
    return Deps(llm=llm, mcp=mcp, db=db, sandbox=FakeSandbox(), gpu=gpu)
