# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builds the real AutonomyService (database, MCP, LLM, orchestrator).

Kept apart from service.py so the service logic imports - and tests - without a
database, a GPU or an MCP daemon. This is the only module that touches them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

import sqlalchemy as sa
import structlog

from neml_brain.autonomy.db_repo import AutonomyRepo
from neml_brain.autonomy.service import AutonomyService, Runtime, tag_with_llm
from neml_brain.evolution.evaluator import BodyEvaluator
from neml_brain.evolution.recording import MediaUploader
from neml_brain.evolution.runner import EvolutionRunner

log = structlog.get_logger(__name__)


async def build_service() -> tuple[AutonomyService, Callable[[], Awaitable[None]]]:
    from neml_brain import services
    from neml_brain.agents.base import Deps
    from neml_brain.config import get_settings, llm_config
    from neml_brain.db import repo as db_repo
    from neml_brain.db.session import get_engine, get_sessionmaker
    from neml_brain.llm.provider import load_provider
    from neml_brain.logging import configure_logging
    from neml_brain.mcp.client import McpClient, load_servers
    from neml_brain.memory.consolidation import consolidate
    from neml_brain.memory.embedding import EmbeddingClient
    from neml_brain.memory.store import insert_chunks
    from neml_brain.paths import CONFIG_DIR
    from neml_brain.runtime.audit import AuditLog
    from neml_brain.runtime.budget import Budget
    from neml_brain.runtime.sandbox import Sandbox
    from neml_brain.safety.gates import _owners_from_env
    from neml_brain.settings.store import SettingsStore

    settings = get_settings()
    configure_logging()
    sessions = get_sessionmaker()
    audit = AuditLog(sessions)
    mcp_client = McpClient(load_servers(CONFIG_DIR / "mcp.yaml"))
    llm = services.Llm(load_provider(llm_config(settings)), settings.vllm_url, settings.llm_model)
    embedder = EmbeddingClient(settings.embed_url)
    db = services.Db(sessions, audit)
    safety = services.Safety(sessions, audit, _owners_from_env())
    del safety  # the loop never decides approvals; humans do, through the API
    orchestrator = services.Orchestrator(
        Deps(llm=llm, mcp=services.Mcp(mcp_client), db=db, sandbox=Sandbox(), bridge=None),
        settings.db_url,
    )
    repo = AutonomyRepo(sessions, SettingsStore(sessions))
    budget = services.BudgetService(Budget(CONFIG_DIR / "budget.yaml"))

    async def remember(kind: str, source_id: str, content: str) -> None:
        vector = (await embedder.embed([content]))[0]
        async with sessions() as session:
            await insert_chunks(
                session,
                [
                    {
                        "source_kind": kind,
                        "source_id": source_id,
                        "content": content,
                        "embedding": vector,
                    }
                ],
            )
            await session.commit()

    async def update_skill_stats(skill_key: str, success: bool) -> float:
        async with sessions() as session:
            skill_id = (
                await session.execute(
                    sa.text(
                        "SELECT id FROM skills WHERE skill_key = :k ORDER BY version DESC LIMIT 1"
                    ),
                    {"k": skill_key},
                )
            ).scalar_one_or_none()
            if skill_id is None:
                return 1.0  # an unknown skill cannot trigger a repair
            await session.execute(
                sa.text(
                    "INSERT INTO skill_runs (skill_id, env, success, deterministic)"
                    " VALUES (:s, 'sim', :ok, true)"
                ),
                {"s": skill_id, "ok": success},
            )
            await session.commit()
            rate = await db_repo.skill_success_rate(session, skill_id)
        return 1.0 if rate is None else rate

    async def consolidate_memory() -> int:
        async with sessions() as session:
            written = await consolidate(session, embedder)
            await session.commit()
        return written

    async def notify(event: dict[str, Any]) -> None:
        # The cloud bridge lives in the brain process. The owner sees this through
        # the audit log (and the structlog line) until the bridge is shared.
        await audit.write(
            actor="autonomy", action=str(event.get("kind")), params=event, outcome="notified"
        )

    async def consume_sim(runs: float) -> None:
        try:
            await budget.budget.consume("sim_runs", runs)
        except Exception as exc:  # noqa: BLE001 - the loop's budget_ok gate stops the next task
            log.warning("evolution.budget_consume_failed", error=str(exc))

    evolution = EvolutionRunner(
        sessions,
        BodyEvaluator(mcp_client, settings.work_dir),
        cast("Any", llm.provider),  # concrete providers take a profile, the Protocol does not
        db.create_approval,
        consume_sim,
        notify,
        uploader=MediaUploader.from_ws_url(
            settings.cloud_ws, settings.api_key.get_secret_value(), settings.node_id
        ),
    )

    rt = Runtime(
        repo=repo,
        sim=services.Sim(mcp_client),
        orchestrator=orchestrator,
        budget=budget,
        create_approval=db.create_approval,
        tag_failure=lambda ctx: tag_with_llm(llm.provider, ctx),
        remember=remember,
        update_skill_stats=update_skill_stats,
        consolidate_memory=consolidate_memory,
        notify=notify,
        evolution=evolution,
    )
    rt.factors = await repo.load_factors()  # the last refit survives a restart

    async def aclose() -> None:
        await orchestrator.aclose()
        await mcp_client.aclose()
        await get_engine().dispose()

    return AutonomyService(rt), aclose
