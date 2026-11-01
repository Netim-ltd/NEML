# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""neml-brain application factory and lifespan (SPEC 8.1, 8.3, 17.1 port 8080).

Run:  uvicorn neml_brain.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from neml_brain import __version__
from neml_brain.api import ROUTERS
from neml_brain.api.problem import install_error_handlers
from neml_brain.config import budget_config, get_settings, llm_config
from neml_brain.logging import configure_logging, correlation_middleware, get_logger
from neml_brain.paths import CONFIG_DIR

log = get_logger(__name__)

# SPEC 5.2 — an approval that outlives its window is auto-rejected. Five minutes
# is fine: expiry is measured from `expires_at`, the sweep only writes the row.
APPROVAL_SWEEP_MINUTES = 5


def _schedule_jobs(scheduler: AsyncIOScheduler, state: Any, budget_cfg: dict[str, Any]) -> None:
    """The three recurring jobs the brain owns. Everything else is event driven."""
    tz = ZoneInfo(budget_cfg.get("timezone", "Europe/Istanbul"))
    hour, _, minute = str(budget_cfg.get("reset_at", "00:00")).partition(":")

    # SPEC 14.4 — daily budgets reset at 00:00 TRT.
    scheduler.add_job(
        state.budget.reset_daily,
        CronTrigger(hour=int(hour), minute=int(minute or 0), timezone=tz),
        id="budget_reset",
        replace_existing=True,
    )
    # SPEC 7 — telemetry is RANGE partitioned by month. Checked daily so the
    # partition for next month exists long before the first insert needs it.
    scheduler.add_job(
        state.repo.ensure_telemetry_partitions,
        CronTrigger(hour=int(hour), minute=5, timezone=tz),
        id="telemetry_partition_check",
        replace_existing=True,
    )
    # SPEC 5.2 — expired approval requests are rejected automatically.
    scheduler.add_job(
        state.safety.expire_approvals,
        IntervalTrigger(minutes=APPROVAL_SWEEP_MINUTES),
        id="approval_expiry_sweep",
        replace_existing=True,
    )


# The contract the routers depend on. app.state.<name> must provide exactly
# these, all awaitable. Nothing else in api/ reaches into db/, llm/ or mcp/.
# The objects themselves live in services.py; this module only builds them.
#
#   repo        ping() list_robots() get_robot(id) list_tasks(**f) get_task(id) create_task(d)
#               update_task(id, d) cancel_task(id) list_task_runs(id)
#               get_approval(id)
#               list_skills(**f) genome_lineage(**f) pending_approvals()
#               query_telemetry(**f) ensure_telemetry_partitions()
#   llm         ping()
#   mcp         health() -> {server: status}          aclose()
#   sim         run_once(spec) -> {outcome, metrics, ...}
#   budget      allow(resource) -> bool   snapshot() -> {"resources": {...}}
#               reset_daily()
#   gpu_lock    acquire(consumer, timeout_s) release(consumer)   (SPEC 4.5)
#   safety      software_estop(robot_id, actor, reason) record_safety_check(**f)
#               decide_approval(approval_id, decision, decided_by, note)
#               expire_approvals()
#   bridge      start() stop() health()
#   evolution   start_campaign(d) list_campaigns(**f) campaign_progress(id) stop_campaign(id, **kw)
#   orchestrator handle_command(text, actor, robot_id, correlation_id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Wire the service layer onto app.state, then start the scheduler.

    ponytail: the db/llm/mcp/agent/bridge/service imports are local to this
    function on purpose. create_app() stays importable -- and the SPEC 8.3
    contract tests stay runnable -- without a database, a GPU, LangGraph or an
    MCP daemon on the machine. Move them to module level the day startup cost
    matters more than that.
    """
    import faulthandler
    import sys

    # The brain has frozen twice, both right after a model reply: if the loop is blocked, say where (stacks of every thread).
    faulthandler.dump_traceback_later(20, repeat=True, file=sys.stderr)

    async def _beat() -> None:
        while True:
            faulthandler.cancel_dump_traceback_later()  # the loop is alive: re-arm, so a dump means it was stuck for 20 s
            faulthandler.dump_traceback_later(20, repeat=True, file=sys.stderr)
            await asyncio.sleep(5)

    beat = asyncio.create_task(_beat())

    from neml_brain import services
    from neml_brain.agents.base import Deps
    from neml_brain.bridge.client import CloudBridge
    from neml_brain.bridge.commands import ApprovalAnnouncer, CommandRouter
    from neml_brain.bridge.fab_ops import FabOps
    from neml_brain.bridge.live import LivePublisher
    from neml_brain.bridge.mirror import MirrorPublisher
    from neml_brain.bridge.outbox import Outbox
    from neml_brain.bridge.protocol import Envelope
    from neml_brain.db.session import get_engine, get_sessionmaker
    from neml_brain.evolution.board_team import BoardTeam
    from neml_brain.evolution.evaluator import BodyEvaluator
    from neml_brain.evolution.imports import GithubImporter
    from neml_brain.evolution.knowledge import KnowledgeBase, Researcher
    from neml_brain.evolution.model_edit import ModelEditor
    from neml_brain.evolution.poses import PoseStore
    from neml_brain.evolution.recording import MediaUploader
    from neml_brain.evolution.runner import EvolutionRunner
    from neml_brain.llm.provider import load_provider
    from neml_brain.mcp.client import McpClient, load_servers
    from neml_brain.platform.artifacts import ModelArtifacts
    from neml_brain.platform.config import load_config as load_platform_config
    from neml_brain.platform.deployment import DeploymentManager
    from neml_brain.platform.publisher import PlatformPublisher
    from neml_brain.platform.robots import ModelRegistry
    from neml_brain.platform.store import PlatformStore
    from neml_brain.platform.task_models import OperationModels
    from neml_brain.runtime.audit import AuditLog
    from neml_brain.runtime.budget import Budget
    from neml_brain.runtime.gpu_lock import GpuLock
    from neml_brain.runtime.sandbox import Sandbox

    # SPEC 5.5 owner identity has exactly one definition; gates.py owns it.
    from neml_brain.safety.gates import _owners_from_env
    from neml_brain.settings.store import SettingsStore

    settings = get_settings()
    configure_logging()

    sessions = get_sessionmaker()
    audit = AuditLog(sessions)
    mcp_client = McpClient(load_servers(CONFIG_DIR / "mcp.yaml"))
    outbox = Outbox(settings.outbox_db)

    state = app.state
    state.settings = settings
    state.repo = services.Db(sessions, audit)
    state.platform_store = PlatformStore(sessions)
    state.settings_store = SettingsStore(sessions)
    state.operation_models = OperationModels(
        os.getenv("NEML_OPERATION_ROUTES", "{}"),
        os.getenv("NEML_OPERATION_SERVICE_KEY", ""),
    )
    state.platform_artifacts = ModelArtifacts(settings.artifact_dir / "models")
    signing_seed = os.getenv("NEML_MODEL_SIGNING_SEED", "")
    state.platform_deployment = None
    if signing_seed and signing_seed != "CHANGEME":
        signer = ModelRegistry(bytes.fromhex(signing_seed))
        policy = load_platform_config(CONFIG_DIR / "platform.yaml")
        state.platform_deployment = DeploymentManager(
            state.platform_store, policy.thresholds, signer
        )
    state.safety = services.Safety(sessions, audit, _owners_from_env())
    state.llm = services.Llm(
        load_provider(llm_config(settings)), settings.vllm_url, settings.llm_model
    )
    state.mcp = services.Mcp(mcp_client)
    state.sim = services.Sim(mcp_client)
    state.gpu_lock = services.Gpu(GpuLock())
    budget_cfg = budget_config(settings)
    state.budget = services.BudgetService(Budget(CONFIG_DIR / "budget.yaml"))

    async def on_cloud_message(envelope: Envelope) -> None:
        await router(envelope)

    state.bridge = services.Bridge(
        CloudBridge(
            settings.cloud_ws,
            settings.node_id,
            settings.api_key.get_secret_value(),
            outbox,
            on_message=on_cloud_message,
        ),
        outbox,
    )
    state.platform_publisher = PlatformPublisher(state.platform_store, state.bridge.cloud)
    state.orchestrator = services.Orchestrator(
        Deps(
            llm=state.llm,
            mcp=state.mcp,
            db=state.repo,
            sandbox=Sandbox(),
            bridge=state.bridge,
        ),
        settings.db_url,
    )

    async def no_budget(_: float) -> None:
        return None

    async def no_notice(_: dict[str, Any]) -> None:
        return None

    model_runner = EvolutionRunner(
        sessions,
        BodyEvaluator(mcp_client, settings.work_dir),
        cast("Any", state.llm.provider),
        state.repo.create_approval,
        no_budget,
        no_notice,
        uploader=MediaUploader.from_ws_url(
            settings.cloud_ws, settings.api_key.get_secret_value(), settings.node_id
        ),
    )
    researcher = Researcher(mcp_client, state.llm.provider, KnowledgeBase(settings.artifact_dir))
    models = ModelEditor(
        sessions,
        model_runner,
        state.llm.provider,
        state.repo.create_task,
        state.repo.create_approval,
        researcher,
    )
    from pathlib import Path

    from neml_brain.learning.store import LearningStore as _Store

    learn_store_for_boards = _Store()
    boards = BoardTeam(
        mcp_client,
        model_runner._uploader,  # noqa: SLF001 - the same cloud uploader
        state.llm.provider,
        learn_store_for_boards,
        Path(settings.artifact_dir) / "boards",
        KnowledgeBase(settings.artifact_dir),
    )
    importer = GithubImporter(
        mcp_client,
        model_runner._uploader,  # noqa: SLF001 - the same cloud uploader
        sessions,
        model_runner,
        settings.artifact_dir,
        state.llm.provider,
    )
    models.importer = importer
    from datetime import UTC, datetime, timedelta

    from neml_brain.evolution.worlds import WorldStore
    from neml_brain.learning.roles import apply_accepted
    from neml_brain.learning.roles import audit as audit_design
    from neml_brain.learning.store import LearningStore
    from neml_brain.learning.tick import tick as learning_tick
    from neml_brain.platform.learning import in_night_window

    world_store = WorldStore()
    learn_store = LearningStore()

    async def learning_job() -> None:
        apply_accepted(
            learn_store, world_store
        )  # safe accepted remedies (new worlds) go live by themselves
        await learning_tick(
            learn_store,
            state.llm.provider,
            night=in_night_window(datetime.now(UTC)),
        )

    from neml_brain.learning.radar import Radar

    radar = Radar(mcp_client, researcher, learn_store.root)

    async def radar_job() -> None:
        await radar.tick()

    async def autopilot_job() -> None:
        """Lessons are decided by the lab itself (rules + a second opinion from the model); nothing waits for the owner."""
        from neml_brain.learning import autopilot

        if generator.busy():
            return
        got = await autopilot.decide(learn_store, state.llm.provider)
        path = learn_store.root / "autopilot.json"
        book = learn_store._read(path)  # noqa: SLF001
        book["history"] = [*book.get("history", [])[-29:], {"at": time.time(), **got}]
        book["total"] = {k: book.get("total", {}).get(k, 0) + v for k, v in got.items()}
        learn_store._write(path, book)  # noqa: SLF001

    async def export_job() -> None:
        """The day's training file (accepted lessons and checked recipes) for a GPU fine-tuning run."""
        from neml_brain.learning import autopilot

        autopilot.export(learn_store, generator.skills.all() if generator.skills else [])

    async def audit_job() -> None:
        """The analysts and critics look at the active design (structure now, more areas as they get analysts)."""
        seed = await model_runner.active_genome()
        await audit_design(learn_store, state.llm.provider, dict(seed["body"]), str(seed["name"]))

    async def sweep_job() -> None:
        """Self-play in Gazebo: one recorded run per hour in the next world; a mastered world makes a harder one."""
        path = learn_store.root / "sweeps.json"
        record = learn_store._read(path)  # noqa: SLF001
        names = world_store.names()
        world = names[int(record.get("runs", 0)) % len(names)]
        out = await model_runner.record_run({"world_id": world, "duration_s": 6})
        metrics = out.get("metrics", {})
        passes = dict(record.get("passes", {}))
        passed = out.get("outcome") == "success" and bool(metrics.get("goal_reached"))
        passes[world] = passes.get(world, 0) + 1 if passed else 0
        fails = {w: m for w, m in dict(record.get("fails", {})).items() if w != world}
        if not passed:  # why the robot lost, so the next plan is told (generative.sim_hint)
            fails[world] = {"tipped": bool(metrics.get("tipped_over")), "x_m": metrics.get("x_m"), "mass_kg": metrics.get("mass_kg"), "error": str(metrics.get("error") or "")[:160]}
        grown = None
        if passes[world] >= 3:
            made = world_store.next_harder(world)
            grown = made["name"] if made and made["ok"] else None
            passes[world] = 0
            if grown:
                learn_store.note(
                    "world",
                    "curriculum",
                    f"robot {world} dünyasında 3 koşuyu da geçti, yeni ortam {grown} oluşturuldu",
                )
        learn_store._write(  # noqa: SLF001
            path,
            {
                "runs": int(record.get("runs", 0)) + 1,
                "last_world": world,
                "last_outcome": out.get("outcome"),
                "passes": passes,
                "fails": fails,
                "grown": grown or record.get("grown"),
                "last_metrics": {k: v for k, v in metrics.items() if k != "media"},
            },
        )

    import time
    from pathlib import Path

    from neml_brain.evolution.generative import IDEA_SCHEMA, Generator

    generator = Generator(
        mcp_client,
        importer,
        sessions,
        state.llm.provider,
        learn_store,
        Path(settings.artifact_dir) / "gen",
        KnowledgeBase(settings.artifact_dir),
    )

    boards.variants = 3
    generator.variants = 3  # every design races three plans before building the best

    from neml_brain.evolution.bench import CadBench, Evolver
    from neml_brain.evolution.skills import SkillLibrary

    generator.skills = SkillLibrary(learn_store.root)
    bench = CadBench(generator, Path(settings.artifact_dir) / "gen", learn_store.root)
    proposer = state.llm.provider
    if os.environ.get("NEML_PROPOSER_URL") and os.environ.get("NEML_PROPOSER_KEY"):
        # opt-in: a stronger hosted model writes the rules and chairs the round table; the owner sets all three, nothing is sent otherwise
        from neml_brain.llm.provider import RemoteOpenAIProvider

        proposer = RemoteOpenAIProvider(
            os.environ["NEML_PROPOSER_URL"].rstrip("/"),
            os.environ.get("NEML_PROPOSER_MODEL", "gpt-4o-mini"),
            180.0,
            api_key=os.environ["NEML_PROPOSER_KEY"],
        )
    evolver = Evolver(bench, generator, proposer, learn_store.root, notes=researcher.base)

    from neml_brain.learning.steward import Steward

    steward = Steward(learn_store)
    generator.on_findings = steward.ingest  # every hard-judge finding becomes a labelled training row at once

    async def steward_job() -> None:
        """The data steward: collect, clean and audit the training data of every area (no model, cheap)."""
        steward.cycle(generator.jobs())

    async def evolve_job() -> None:
        """The lab tunes how it asks for parts: one proposed recipe rule per round, kept only when the benchmark improves."""
        if not boards.busy():
            await evolver.step()

    async def initiative_job() -> None:
        """The lab's own initiative: when idle it asks itself which robot would be useful next, and designs it."""
        jobs = generator.jobs()
        made = [j for j in jobs if j["actor"] == "lab" and time.time() - j["at"] < 4 * 3600]
        finished_today = [j for j in jobs if j["state"] == "done" and time.time() - float(j["at"]) < 24 * 3600]
        if generator.busy() or made or len(finished_today) >= 8:  # a rolling daily budget; a lifetime cap used to stop the lab for good
            return
        names = ", ".join(world_store.names()[-8:])
        recent = ", ".join(
            e["title"]
            for e in learn_store._read(learn_store.root / "radar.json").get("log", [])[-5:]  # noqa: SLF001
        )
        idea = await state.llm.provider.fill(
            f"Bir robot laboratuvarının yeni bir robot tasarlama sırası. Elimizdeki simülasyon ortamları: {names}. "
            f"Son okunan haberler/yazılar: {recent or '(yok)'}. Bu ortamlarda ya da sık görülen ihtiyaçlar için "
            "küçük, basit, 3B yazıcı ile üretilebilir TEK bir robot fikri öner (ne iş yapacak, kaç tekerlek/bacak).",
            IDEA_SCHEMA,
            profile="param_skill",
            max_tokens=300,
        )
        brief = None
        for model, review in roundtable.reviews().items():
            if not review.get("redesigned"):
                brief = next_brief(roundtable.reviews(), model)
                if brief:  # the specialists found things missing: the next design is the better version of this one
                    review["redesigned"] = True
                    learn_store._write(
                        learn_store.root / "reviews.json", roundtable.reviews() | {model: review}
                    )  # noqa: SLF001
                    break
        generator.start(brief or str(idea["idea"]), "lab")

    import sqlalchemy as sa

    from neml_brain.learning.roundtable import RoundTable, next_brief

    roundtable = RoundTable(proposer, learn_store, researcher, sessions)

    async def meet(result: dict[str, Any]) -> None:
        await roundtable.review(str(result["model"]))

    generator.on_done = meet
    models.generator = generator

    async def daily_review_job() -> None:
        """Every day the agents meet again about the generated model that was reviewed longest ago."""
        async with sessions() as session:
            names = [
                r[0]
                for r in await session.execute(
                    sa.text(
                        "SELECT DISTINCT name FROM genomes WHERE status = 'active' AND body->'mechanical'->'generated' IS NOT NULL"
                    )
                )
            ]
        reviews = roundtable.reviews()
        due = sorted(names, key=lambda n: reviews.get(n, {}).get("at", 0))
        if (
            due
            and time.time() - reviews.get(due[0], {}).get("at", 0) > 20 * 3600
            and not generator.busy()
        ):
            await roundtable.review(due[0])

    async def digest_job() -> None:
        """A daily record of what the lab learned, built and trained (shown on the learning page)."""
        path = learn_store.root / "daily.json"
        days = learn_store._read(path)  # noqa: SLF001
        lessons = learn_store.lessons().values()
        since = time.time() - 24 * 3600
        days[time.strftime("%Y-%m-%d")] = {
            "events": sum(1 for e in learn_store.events() if e["ts"] > since),
            "lessons_new": sum(1 for x in lessons if x["ts"] > since),
            "lessons_accepted": sum(1 for x in lessons if x["status"] == "accepted"),
            "notes": len(KnowledgeBase(settings.artifact_dir).all()),
            "designs": sum(1 for j in generator.jobs() if j["state"] == "done" and j["at"] > since),
            "reviews": sum(1 for r in roundtable.reviews().values() if r.get("at", 0) > since),
        }
        learn_store._write(path, dict(sorted(days.items())[-14:]))  # noqa: SLF001

    router = CommandRouter(
        generator=generator,
        learning=learn_store,
        importer=importer,
        poses=PoseStore(settings.artifact_dir),
        models=models,
        boards=boards,
        bench=bench,
        evolver=evolver,
        steward=steward,
        notes=researcher.base,
        repo=state.repo,
        safety=state.safety,
        orchestrator=state.orchestrator,
        settings=state.settings_store,
        send=state.bridge.cloud.send,
        fab=FabOps(sessions),
    )

    async def budget_used() -> float:
        resources = (await state.budget.snapshot())["resources"]
        return max((float(r.get("ratio", 0.0)) for r in resources.values()), default=0.0)

    live = LivePublisher(
        sessions,
        state.bridge.cloud.send,
        model=settings.llm_model,
        budget_used=budget_used,
        gpu_owner=lambda: getattr(state.gpu_lock.lock, "_owner", None),
    )
    mirror = MirrorPublisher(sessions, state.bridge.cloud.send)
    announcer = ApprovalAnnouncer(state.repo.pending_approvals, state.bridge.cloud.send)

    scheduler = AsyncIOScheduler()
    _schedule_jobs(scheduler, state, budget_cfg)
    scheduler.add_job(
        model_runner.publish_scenes, id="scenes_at_start"
    )  # one shot: 3D scenes of the active designs
    scheduler.add_job(
        learning_job,
        IntervalTrigger(minutes=10),
        id="learning",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        daily_review_job,
        IntervalTrigger(hours=6),
        id="daily_review",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        digest_job,
        IntervalTrigger(hours=6),
        id="digest",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(UTC),
    )
    if os.environ.get("NEML_INITIATIVE") == "1":  # off by default: whole robots the lab dreams up are not checked against anything real
        scheduler.add_job(
            initiative_job,
            IntervalTrigger(hours=2),
            id="initiative",
            replace_existing=True,
            max_instances=1,
        )
    scheduler.add_job(
        radar_job, IntervalTrigger(minutes=15), id="radar", replace_existing=True, max_instances=1
    )
    scheduler.add_job(
        sweep_job, IntervalTrigger(hours=1), id="sim_sweep", replace_existing=True, max_instances=1
    )
    scheduler.add_job(
        evolve_job, IntervalTrigger(hours=6), id="evolve", replace_existing=True, max_instances=1
    )
    scheduler.add_job(
        steward_job, IntervalTrigger(minutes=30), id="steward", replace_existing=True, max_instances=1
    )
    scheduler.add_job(
        autopilot_job, IntervalTrigger(minutes=20), id="autopilot", replace_existing=True, max_instances=1
    )
    scheduler.add_job(
        export_job, IntervalTrigger(hours=24), id="lora_export", replace_existing=True, max_instances=1,
        next_run_time=datetime.now(UTC) + timedelta(minutes=5),
    )
    scheduler.add_job(
        state.platform_publisher.drain_all,
        IntervalTrigger(seconds=5),
        id="platform_outbox_publish",
        replace_existing=True,
    )
    if state.platform_deployment is not None:
        scheduler.add_job(
            state.platform_deployment.monitor_all_canaries,
            IntervalTrigger(minutes=1),
            id="platform_canary_monitor",
            replace_existing=True,
        )
    # The app's screens are fed by these (SPEC 9.4); see bridge/live.py.
    for job, seconds in (
        (announcer.announce, 10),
        (live.brain_status, 15),
        (live.robots, 5),
        (live.tasks, 5),
        (live.telemetry, 2),
        (live.audit, 10),
        (mirror.publish, 10),
    ):
        scheduler.add_job(
            job,
            IntervalTrigger(seconds=seconds),
            id=f"live_{job.__name__}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    for team in (generator, boards):  # designs the last process left running go on from their checkpoints
        team.resume()
    state.scheduler = scheduler

    await state.bridge.start()
    log.info("brain_started", version=__version__, env=settings.env, node_id=settings.node_id)
    try:
        yield
    finally:
        beat.cancel()
        faulthandler.cancel_dump_traceback_later()
        scheduler.shutdown(wait=False)
        await state.bridge.stop()
        await state.orchestrator.aclose()
        await state.mcp.aclose()
        await get_engine().dispose()
        log.info("brain_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="neml-brain",
        version=__version__,
        description="NEML lab brain. Internal API, LAN only (SPEC 17.1).",
        lifespan=lifespan,
    )
    app.middleware("http")(correlation_middleware)
    install_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    return app


app = create_app()
