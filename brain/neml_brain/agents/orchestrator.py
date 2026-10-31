# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""NEML_SPEC.md 8.4 - the main LangGraph loop.

ROUTER -> {QUERY, TASK_FILL -> TASK_OPS, DESIGN, EXPLAIN}; DESIGN -> PARAM_FILL
-> GENERATE -> VALIDATE -> SIMULATE (failure edge loops back) -> APPROVAL ->
EXECUTE; every branch converges on PERSIST. A failed VALIDATE skips SIMULATE and
goes straight to APPROVAL, which records the rejection (ADR-014).

SPEC 6.5 is binding here: a 1.5B model cannot choose tools reliably, so **every
MCP call is made by a graph node against a statically declared tool name**. The
model classifies (guided_choice) and fills parameters (guided_json) and does
nothing else. Handing the model a tool list to pick from is forbidden.

Node failures are not routed: a policy or MCP error propagates out of ainvoke.
The checkpoint written before the failing node survives, so the flow resumes
from that node once the cause is fixed - the SPEC 8.4 crash-recovery property.
"""

import hashlib
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from neml_brain.agents import electronics, mechanical
from neml_brain.agents.base import Agent, Deps, ToolNotPermitted, register, untrusted
from neml_brain.agents.state import INTENT, MAX_SIM_RETRIES, MAX_STEPS, GraphState

# SPEC 4.4 - the summarize profile is the only unconstrained one, and its output
# is shown to a human, never fed back into the system.
SUMMARIZE_TOKENS = 384

# SPEC 5.2 - a design that reaches EXECUTE manufactures something (print, PCB,
# firmware). That is level 4, the highest gate, owner-only.
APPROVAL_LEVEL = 4

# The grammar alone tells the model nothing about what a label means; small models then guess.
INTENT_HELP = {
    "create_task": "the operator wants a new job done by a robot",
    "update_task": "change an existing task (it names a task id)",
    "cancel_task": "cancel or stop an existing task",
    "query_status": "ask for robot or system status",
    "query_telemetry": "ask for sensor or telemetry values",
    "query_skill": "ask which skills exist",
    "mech_param_change": "design or change a mechanical part: describe it (shape, size, holes, material) "  # noqa: E501
    "and the lab draws it in FreeCAD",
    "elec_param_change": "change an electronics board parameter (voltage, resistor, current, bus)",
    "explain": "explain something to the operator",
    "unknown": "none of the above",
}
_ROUTER_PROMPT = "Classify the operator request into exactly one intent. Intents:\n" + "\n".join(
    f"- {name}: {text}" for name, text in INTENT_HELP.items()
)
_PARAM_PROMPT = (
    "Extract the design parameters requested by the operator. For a field the operator did not "
    "mention, pick a typical value inside the limits of the schema (never below a minimum)."
)
_EXPLAIN_PROMPT = "Summarise the answer to the operator request for a human reader."

# SPEC 8.4 draws four branches; SPEC 4.3 defines twelve intents.
BRANCH = {
    "create_task": "task_ops",
    "update_task": "task_ops",
    "cancel_task": "task_ops",
    "query_status": "query",
    "query_telemetry": "query",
    "query_skill": "query",
    "mech_param_change": "design",
    "elec_param_change": "design",
    "explain": "explain",
    "unknown": "explain",
}

DESIGN_AGENTS: dict[str, Agent] = {
    "mech_param_change": mechanical.AGENT,
    "elec_param_change": electronics.AGENT,
}


class TaskParams(BaseModel):
    """guided_json grammar for the task branch (ADR-014). Every field optional:
    the model fills only what the operator actually said."""

    model_config = ConfigDict(extra="forbid")

    task_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    priority: float | None = Field(default=None, ge=0, le=999.999)


class CommandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    actor: str = "user"


def _agent(state: GraphState) -> Agent:
    agent = DESIGN_AGENTS.get(state.intent or "")
    if agent is None:
        raise ToolNotPermitted(f"no design agent for intent {state.intent!r}")
    return agent


def _artifact_ref(state: GraphState) -> dict[str, Any]:
    return {"artifacts": state.artifacts, "params": state.params}


# --------------------------------------------------------------------------
# nodes
# --------------------------------------------------------------------------


async def router(state: GraphState, deps: Deps) -> dict[str, Any]:
    """SPEC 4.3 stage 1. guided_choice: the model cannot emit anything else."""
    intent = await deps.llm.classify(untrusted(_ROUTER_PROMPT, state.command), INTENT)
    if intent not in INTENT:  # belt and braces; the grammar should make this dead
        intent = "unknown"
    return {"intent": intent, "branch": BRANCH[intent], "steps": 1}


async def query(state: GraphState, deps: Deps) -> dict[str, Any]:
    rows = await deps.db.query(intent=state.intent, command=state.command, actor=state.actor)
    return {"result": {"rows": rows}, "steps": 1}


async def task_fill(state: GraphState, deps: Deps) -> dict[str, Any]:
    """SPEC 4.3 stage 2 for the task branch: the same guided_json gate as
    PARAM_FILL, so `create_task` in prose reaches TASK_OPS with a title,
    a priority and, for update/cancel, a task id."""
    raw = await deps.llm.fill(
        untrusted(_PARAM_PROMPT, state.command), TaskParams.model_json_schema()
    )
    filled = TaskParams.model_validate(raw)  # provider swaps must not weaken the contract
    return {"params": filled.model_dump(mode="json", exclude_none=True), "steps": 1}


async def task_ops(state: GraphState, deps: Deps) -> dict[str, Any]:
    result = await deps.db.task_op(
        intent=state.intent, command=state.command, actor=state.actor, params=state.params
    )
    return {"result": result, "steps": 1}


async def explain(state: GraphState, deps: Deps) -> dict[str, Any]:
    text = await deps.llm.summarize(untrusted(_EXPLAIN_PROMPT, state.command), SUMMARIZE_TOKENS)
    return {"result": {"text": text}, "steps": 1}


async def design(state: GraphState, deps: Deps) -> dict[str, Any]:
    """Branch entry: bind the intent to one statically declared agent."""
    return {"agent": _agent(state).name, "steps": 1}


async def param_fill(state: GraphState, deps: Deps) -> dict[str, Any]:
    """SPEC 4.3 stage 2. The agent's output schema IS the guided_json grammar."""
    agent = _agent(state)
    raw = await deps.llm.fill(
        untrusted(_PARAM_PROMPT, state.command), agent.output_schema.model_json_schema()
    )
    # Second gate: grammar-constrained decoding should make this unreachable,
    # but a provider swap (SPEC 4.7) must not be able to weaken the contract.
    filled = agent.output_schema.model_validate(raw)
    return {"params": filled.model_dump(mode="json"), "steps": 1}


async def generate(state: GraphState, deps: Deps) -> dict[str, Any]:
    """SPEC 4.3 stage 3. Deterministic: a hand-written template, no model."""
    agent = _agent(state)
    tool = agent.stages.get("generate")
    if tool is None:
        raise ToolNotPermitted(f"{agent.name} has no generate stage")
    args = state.params
    if (
        agent is mechanical.AGENT
    ):  # the CAD MCP draws a recipe: it needs a name and a folder of its own  # noqa: E501
        key = hashlib.sha256(state.command.encode()).hexdigest()[:12]
        args = {
            "recipe": state.params["recipe"],
            "name": state.params["part_name"],
            "out_dir": f"/srv/neml/work/design/{key}",
        }
    elif agent is electronics.AGENT:
        key = hashlib.sha256(state.command.encode()).hexdigest()[:12]
        args = {
            "circuit": state.params["circuit"],
            "name": state.params["board_name"],
            "out_dir": f"/srv/neml/artifacts/kicad/{key}",
        }
    artifact = await agent.call(deps, tool, args)
    return {"artifacts": [*state.artifacts, artifact], "steps": 1}


async def validate(state: GraphState, deps: Deps) -> dict[str, Any]:
    """DFM / DRC / schema (SPEC 8.4). Schema already held at PARAM_FILL."""
    agent = _agent(state)
    tool = agent.stages.get("validate")
    if tool is None:
        return {"validation": {"ok": True, "checks": {"schema": True}}, "steps": 1}
    report = await agent.call(deps, tool, _artifact_ref(state))
    return {
        "validation": {"ok": bool(report.get("ok")), "checks": {"schema": True, "tool": report}},
        "steps": 1,
    }


async def simulate(state: GraphState, deps: Deps) -> dict[str, Any]:
    agent = _agent(state)
    tool = agent.stages.get("simulate")
    if tool is None:
        # A PCB parameter change has nothing to simulate in Gazebo.
        return {"sim": {"ok": True, "skipped": "agent declares no simulate stage"}, "steps": 1}
    if not (state.validation or {}).get("ok", False):
        return {"sim": {"ok": False, "reason": "validation failed"}, "steps": 1}
    result = await agent.call(deps, tool, _artifact_ref(state))
    return {"sim": result, "sim_retries": state.sim_retries + 1, "steps": 1}


async def approval(state: GraphState, deps: Deps) -> dict[str, Any]:
    """SPEC 5.2 human gate. interrupt() parks the flow in the checkpoint.

    The node replays from the top when the human resumes, so create_approval is
    called with an idempotency key rather than blindly inserting a second row.
    """
    if not (state.validation or {}).get("ok", False):
        return {
            "approval": {"decision": "rejected", "reason": "validation failed"},
            "steps": 1,
        }
    if not (state.sim or {}).get("ok", False):
        return {
            "approval": {"decision": "rejected", "reason": "simulation did not pass"},
            "steps": 1,
        }
    if not state.thread_id:
        raise ValueError("GraphState.thread_id must be set; it keys the approval row")
    approval_id = await deps.db.create_approval(
        level=APPROVAL_LEVEL,
        subject_kind="task",
        subject_id=state.thread_id or "",
        payload={"intent": state.intent, "artifacts": state.artifacts, "sim": state.sim},
        idempotency_key=f"{state.thread_id}:approval",
    )
    decision = interrupt({"approval_id": approval_id, "level": APPROVAL_LEVEL})
    if isinstance(decision, str):
        decision = {"decision": decision}
    return {"approval_id": approval_id, "approval": decision, "steps": 1}


async def execute(state: GraphState, deps: Deps) -> dict[str, Any]:
    """SPEC 5.2 enforced in code: no approved approval, no hardware."""
    decision = (state.approval or {}).get("decision")
    if decision != "approved" or not state.approval_id:
        return {"result": {"executed": False, "reason": f"approval:{decision}"}, "steps": 1}
    agent = _agent(state)
    tool = agent.stages.get("execute")
    if tool is None:
        return {"result": {"executed": False, "reason": "no execute stage"}, "steps": 1}
    output = await agent.call(deps, tool, _artifact_ref(state), approval_id=state.approval_id)
    return {"result": {"executed": True, "output": output}, "steps": 1}


async def persist(state: GraphState, deps: Deps) -> dict[str, Any]:
    """SPEC 8.4 terminal: DB + audit + bridge."""
    snapshot = state.model_dump(mode="json")
    await deps.db.persist(snapshot)
    await deps.db.audit(
        actor=f"user:{state.actor}",
        action=f"command:{state.intent}",
        target=state.agent or state.branch,
        params_hash=None,
        outcome="ok",
        duration_ms=0,
        approval_id=state.approval_id,
    )
    if deps.bridge is not None:
        await deps.bridge.publish(snapshot)
    return {"steps": 1}


# --------------------------------------------------------------------------
# edges
# --------------------------------------------------------------------------


def _after_router(state: GraphState) -> str:
    return state.branch or "explain"


def _after_validate(state: GraphState) -> str:
    """A design that failed DFM/DRC is never simulated: it would burn a sim run
    (and the GPU budget) on a part that cannot be made."""
    return "simulate" if (state.validation or {}).get("ok", False) else "approval"


def _after_simulate(state: GraphState) -> str:
    """SPEC 8.4 failure edge: SIMULATE loops back into itself while it fails."""
    sim = state.sim or {}
    retryable = sim.get("skipped") is None and (state.validation or {}).get("ok", False)
    if not sim.get("ok", False) and retryable and state.sim_retries <= MAX_SIM_RETRIES:
        return "simulate"
    return "approval"


Node = Callable[[GraphState, Deps], Awaitable[dict[str, Any]]]

NODES: dict[str, Node] = {
    "router": router,
    "query": query,
    "task_fill": task_fill,
    "task_ops": task_ops,
    "design": design,
    "explain": explain,
    "param_fill": param_fill,
    "generate": generate,
    "validate": validate,
    "simulate": simulate,
    "approval": approval,
    "execute": execute,
    "persist": persist,
}


def _bind(fn: Node, deps: Deps) -> Any:
    """Close a node over its dependencies. `Any` because add_node's overloads
    do not accept a bare coroutine function."""

    async def node(state: GraphState) -> dict[str, Any]:
        return await fn(state, deps)

    node.__name__ = fn.__name__
    return node


def build_graph(deps: Deps, checkpointer: Any) -> CompiledStateGraph[GraphState, None, Any, Any]:
    """Compile the SPEC 8.4 graph. `checkpointer` is injected, never constructed.

    Production passes postgres_checkpointer(); tests pass an in-memory saver.
    """
    graph = StateGraph(GraphState)
    for name, fn in NODES.items():
        graph.add_node(name, _bind(fn, deps))

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        _after_router,
        {
            "query": "query",
            "task_ops": "task_fill",
            "design": "design",
            "explain": "explain",
        },
    )
    graph.add_edge("task_fill", "task_ops")
    graph.add_edge("design", "param_fill")
    graph.add_edge("param_fill", "generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges(
        "validate", _after_validate, {"simulate": "simulate", "approval": "approval"}
    )
    graph.add_conditional_edges(
        "simulate", _after_simulate, {"simulate": "simulate", "approval": "approval"}
    )
    graph.add_edge("approval", "execute")
    for branch in ("query", "task_ops", "explain", "execute"):
        graph.add_edge(branch, "persist")
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=checkpointer)


def run_config(thread_id: str) -> RunnableConfig:
    """LangGraph's own recursion_limit must not pre-empt the SPEC 8.4 cap.

    The cap is enforced by GraphState.steps so that it holds for any caller;
    recursion_limit is set above it so StepLimitExceeded is what actually fires.
    """
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": MAX_STEPS + 5}


def postgres_checkpointer(dsn: str) -> AbstractAsyncContextManager[Any]:
    """SPEC 8.4 / T-012 checkpointer. Async context manager yielding the saver.

    Imported lazily so the graph, and its tests, do not need psycopg installed.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    return AsyncPostgresSaver.from_conn_string(dsn)


# SPEC 16 T-013 lists `orchestrator` as a core agent, so it declares schemas and
# a tool list like the others. Owner decision 3 grants it db.read and nothing
# else: the QUERY and TASK_OPS nodes read, every write is somebody else's tool.
AGENT = register(
    "orchestrator", input_schema=CommandIn, output_schema=GraphState, tools=("db.read",)
)
