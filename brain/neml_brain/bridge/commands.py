# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the lab does with the messages the cloud queue sends down (SPEC 3.1, 9.5).

The remote API can only write a row to its `commands` table; the lab decides
whether and how to apply it. This module is that decision, and it closes the
loop with a `command_ack` so the app can see the outcome.

Wire contract: the .NET side serialises with System.Text.Json web defaults, so
payload keys are camelCase (`commandId`, `taskId`, `approvalId`), while the
envelope itself keeps its snake_case `idempotency_key`. Both directions are
spelled out here once, in `ACK` and `_Command`, rather than guessed per handler.

Authority: a cloud command carries no more power than the API call that queued
it. Hardware-touching kinds go through the same code paths as the lab's own REST
API (software e-stop, approval gate); nothing here bypasses safety/.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal, Protocol

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neml_brain.bridge.fab_ops import FabRejected
from neml_brain.bridge.protocol import Envelope
from neml_brain.evolution.imports import ImportRejected
from neml_brain.evolution.model_edit import Rejected as ModelRejected
from neml_brain.evolution.poses import PoseRejected
from neml_brain.evolution.skills import SkillLibrary
from neml_brain.settings import catalog

log = structlog.get_logger(__name__)

AckState = Literal["applied", "failed", "rejected"]
CLOUD_ACTOR = "cloud"


class Repo(Protocol):
    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def update_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None: ...
    async def cancel_task(self, task_id: str) -> bool: ...


class Safety(Protocol):
    async def software_estop(
        self, robot_id: str, actor: str, reason: str
    ) -> dict[str, Any] | None: ...
    async def decide_approval(
        self, *, approval_id: str, decision: str, decided_by: str, note: str | None
    ) -> dict[str, Any] | None: ...


class Orchestrator(Protocol):
    async def handle_command(
        self,
        *,
        text: str,
        actor: str,
        robot_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]: ...


class Settings(Protocol):
    async def model_ids(self) -> list[str]: ...
    async def get(self, model_id: str) -> dict[str, Any]: ...
    async def put(self, model_id: str, values: dict[str, Any], actor: str) -> dict[str, Any]: ...


class Fab(Protocol):
    async def cancel(self, print_job_id: str, reason: str | None) -> dict[str, Any]: ...
    async def submit_qc(
        self, print_job_id: str, body: dict[str, Any], genome_id: str | None
    ) -> dict[str, Any]: ...


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _Command(_Strict):
    """server -> lab `command` payload: CommandEnvelope(id, seq, kind, payload, idempotency_key)."""

    id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class _Decision(_Strict):
    """server -> lab `approval_decision` payload: {approvalId, decision, by, note}."""

    approval_id: str = Field(alias="approvalId")
    decision: Literal["approved", "rejected"]
    by: str = Field(min_length=1)
    note: str | None = None


class Rejected(Exception):
    """The command is well formed but this lab will not do it."""


def snake(args: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """camelCase request keys -> the column names the repo takes; unknown keys dropped."""
    return {to: args[frm] for frm, to in mapping.items() if args.get(frm) is not None}


class CommandRouter:
    """Dispatches cloud messages and answers each command with a `command_ack`."""

    def __init__(
        self,
        *,
        repo: Repo,
        safety: Safety,
        orchestrator: Orchestrator,
        settings: Settings,
        send: Callable[..., Any],  # CloudBridge.send
        fab: Fab | None = None,
        models: Any = None,
        boards: Any = None,
        bench: Any = None,
        evolver: Any = None,
        importer: Any = None,
        poses: Any = None,
        learning: Any = None,
        generator: Any = None,
        steward: Any = None,
        notes: Any = None,
    ) -> None:
        self._repo, self._safety = repo, safety
        self._fab = fab
        self._importer = importer  # GitHub imports
        self._poses = poses  # named joint poses
        self._generator = generator  # robots the lab designs itself (LLM + CAD MCP)
        self._learning = learning  # LearningStore: the lab's lessons
        self._steward = steward  # the data steward: training data of every area
        self._notes = notes  # the research notes (shown on the learning page)
        self._bench = bench
        self._evolver = evolver  # recipe rules the lab finds by running the benchmark
        self._boards = boards  # the board team: agents design KiCad boards (no templates)
        self._models = models  # the robot-model chat; None when the lab has no CAD/uploader
        self._orch, self._settings, self._send = orchestrator, settings, send
        self._kinds: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
            "brain.command": self._brain_command,
            "model.chat": self._model_chat,
            "model.apply": self._model_apply,
            "model.part": self._model_part,
            "model.design": self._model_design,
            "import.scan": self._import_scan,
            "import.refresh": self._import_refresh,
            "model.archive": self._model_archive,
            "pose.op": self._pose_op,
            "learn.op": self._learn_op,
            "import.github": self._import_github,
            "model.notes": self._model_notes,
            "task.create": self._task_create,
            "task.update": self._task_update,
            "task.cancel": self._task_cancel,
            "robot.estop": self._robot_estop,
            "print.cancel": self._print_cancel,
            "print.qc": self._print_qc,
            "model_settings.get": self._settings_get,
            "model_settings.put": self._settings_put,
        }

    # ------------------------------------------------------------ entry point
    async def __call__(self, envelope: Envelope) -> None:
        if envelope.type == "approval_decision":
            await self._approval(envelope)
        elif envelope.type == "command":
            await self._command(envelope)
        else:
            log.info("bridge.ignored", message_type=envelope.type)

    async def _approval(self, envelope: Envelope) -> None:
        try:
            d = _Decision.model_validate(envelope.payload)
        except ValidationError as exc:
            log.error("bridge.bad_approval_decision", error=str(exc))
            return
        decided = await self._safety.decide_approval(
            approval_id=d.approval_id, decision=d.decision, decided_by=d.by, note=d.note
        )
        if decided is not None and self._models is not None:
            try:
                await self._models.on_decision(decided)  # a drafted design becomes active
            except Exception as exc:  # noqa: BLE001 - the decision itself is already recorded
                log.error("bridge.model_activation_failed", error=str(exc))

    async def _command(self, envelope: Envelope) -> None:
        try:
            cmd = _Command.model_validate(envelope.payload)
        except ValidationError as exc:
            log.error("bridge.bad_command", error=str(exc))
            return  # no id to ack against
        handler = self._kinds.get(cmd.kind)
        if handler is None:
            self._ack(cmd.id, "rejected", {"error": f"unknown command kind '{cmd.kind}'"})
            return
        try:
            self._ack(cmd.id, "applied", await handler(cmd.payload))
        except Rejected as exc:
            self._ack(cmd.id, "rejected", {"error": str(exc)})
            self._learn_from(cmd.kind, str(exc))
        except Exception as exc:  # noqa: BLE001 - one bad command must not take the link down
            log.error("bridge.command_failed", kind=cmd.kind, error=str(exc))
            self._learn_from(cmd.kind, f"{type(exc).__name__}: {exc}")
            self._ack(cmd.id, "failed", {"error": f"{type(exc).__name__}: {exc}"})

    def _learn_from(self, kind: str, error: str) -> None:
        """A refused or failed command is something to learn from (by the area it belongs to)."""
        area = {"import": "import", "board": "electronics", "model": "cad"}.get(kind.split(".")[0])
        if area and self._learning is not None:
            self._learning.note(area, f"command:{kind}", f"{kind}: {error}")

    def _ack(self, command_id: str, state: AckState, result: dict[str, Any]) -> None:
        self._send("command_ack", {"commandId": command_id, "state": state, "result": result})

    # --------------------------------------------------------------- handlers
    async def _brain_command(self, a: dict[str, Any]) -> dict[str, Any]:
        text = a.get("text")
        if not isinstance(text, str) or not text.strip():
            raise Rejected("text is required")
        return await self._orch.handle_command(text=text, actor=CLOUD_ACTOR)

    async def _model_chat(self, a: dict[str, Any]) -> dict[str, Any]:
        genome_id, text = a.get("genomeId"), a.get("text")
        if self._models is None:
            raise Rejected("this lab has no model editor")
        if not isinstance(genome_id, str) or not isinstance(text, str) or not text.strip():
            raise Rejected("genomeId and text are required")
        try:
            screen = a.get("screen")
            return dict(
                await self._models.chat(
                    genome_id, text, CLOUD_ACTOR, screen if isinstance(screen, str) else ""
                )
            )
        except ModelRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _model_part(self, a: dict[str, Any]) -> dict[str, Any]:
        genome_id, part = a.get("genomeId"), a.get("part")
        pos, size, params = a.get("pos"), a.get("size"), a.get("params")
        if self._models is None or not isinstance(genome_id, str) or not isinstance(part, str):
            raise Rejected("genomeId and part are required")
        for vec in (pos, size):
            if vec is not None and not (
                isinstance(vec, list)
                and len(vec) == 3
                and all(isinstance(v, int | float) for v in vec)
            ):
                raise Rejected("pos and size are three numbers")
        if params is not None and not (
            isinstance(params, dict) and all(isinstance(v, int | float) for v in params.values())
        ):
            raise Rejected("params is a map of numbers")
        try:
            return dict(await self._models.part_edit(genome_id, part, pos, size, params))
        except ModelRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _model_design(self, a: dict[str, Any]) -> dict[str, Any]:
        text, history = a.get("text"), a.get("history") or []
        if self._generator is None or not isinstance(text, str) or not text.strip():
            raise Rejected("text is required")
        if not isinstance(history, list):
            raise Rejected("history is a list of {role, text}")
        if self._generator.busy():
            raise Rejected(
                "Şu an bir tasarım yapılıyor; bitince yenisini iste (Öğrenme sayfasında ilerlemesi görünür)."
            )
        brief = " ".join(
            [
                *(
                    str(h.get("text"))
                    for h in history[-6:]
                    if isinstance(h, dict) and h.get("role") == "user"
                ),
                text,
            ]
        )[:900]
        job = self._generator.start(brief, CLOUD_ACTOR)
        return {
            "action": "design_started",
            "job": job["id"],
            "reply": "Tasarımı başlattım: önce parça ağacını planlıyorum, sonra her parçayı FreeCAD'de modelliyorum. CPU'da bu 10-40 dakika sürebilir; ilerlemeyi Öğrenme sayfasının 'Tasarımlar' bölümünde izleyebilirsin. Denetimi geçerse simülasyon tasarımı olarak kendiliğinden devreye girer; üretim yine senin onayında.",
        }

    async def _import_refresh(self, a: dict[str, Any]) -> dict[str, Any]:
        genome_id, repo = a.get("genomeId"), a.get("repo")
        if self._importer is None or not isinstance(genome_id, str):
            raise Rejected("genomeId is required")
        try:
            return dict(
                await self._importer.refresh(
                    genome_id, repo if isinstance(repo, str) and repo else None, CLOUD_ACTOR
                )
            )
        except ImportRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _model_archive(self, a: dict[str, Any]) -> dict[str, Any]:
        name = a.get("name")
        if self._models is None or not isinstance(name, str):
            raise Rejected("name is required")
        try:
            return dict(await self._models.archive(name))
        except ModelRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _learn_op(self, a: dict[str, Any]) -> dict[str, Any]:
        if self._learning is None:
            raise Rejected("the lab has no learning store")
        store = self._learning
        op = a.get("op")
        if op == "state":
            keys = (
                "verdict",
                "summary",
                "how_it_should_work",
                "missing",
                "actions",
                "research_topics",
                "chat",
                "votes",
                "learned",
                "at",
            )
            reviews = {}
            for m, r in store._read(store.root / "reviews.json").items():  # noqa: SLF001
                talk = {
                    role: s.get("objection") or (s.get("missing") or [""])[0]
                    for role, s in r.get("transcript", {}).get("tur2", {}).items()
                }
                reviews[m] = {k: r.get(k) for k in keys} | {"talk": talk}
            return {
                **store.state(),
                "designs": self._generator.jobs()[-12:] if self._generator else [],
                "boards": self._boards.jobs()[-8:] if self._boards else [],
                "bench": self._bench.report() if self._bench else {},
                "evolve": self._evolver.state() if self._evolver else {},
                "steward": self._steward.report() if self._steward else {},
                "notes": [
                    {k: n.get(k) for k in ("topic", "area", "title", "rule", "status", "source", "learned_at")}
                    for n in (self._notes.all() if self._notes else [])[-40:]
                ],
                "autopilot": store._read(store.root / "autopilot.json"),  # noqa: SLF001
                "lora": store._read(store.root / "lora.json"),  # noqa: SLF001
                "recipes": [{"key": r["key"], "text": r["text"], "source": r.get("source")} for r in SkillLibrary(store.root).all()],
                "reviews": reviews,
                "daily": store._read(store.root / "daily.json"),  # noqa: SLF001
            }
        if op == "board":
            if self._boards is None or self._boards.busy():
                raise Rejected("kart ekibi şu an meşgul ya da kapalı")
            return dict(self._boards.start(str(a.get("brief") or "")[:900], CLOUD_ACTOR))
        if op == "bench":
            if self._bench is None or self._bench.busy():
                raise Rejected("ölçüm şu an çalışıyor ya da kapalı")
            return dict(self._bench.start())
        if op == "steward":
            if self._steward is None:
                raise Rejected("veri ajanı kapalı")
            return dict(self._steward.cycle(self._generator.jobs() if self._generator else []))
        if op == "gateway":  # customers/products of the language model door: their keys and token limits (owner only, checked by the API)
            from neml_brain.gateway_clients import operate

            try:
                return operate(a)
            except ValueError as exc:
                raise Rejected(str(exc)) from exc
        if op == "cad":  # fit, standard_part, drawing, build_recipe, fem, assemble
            if self._generator is None:
                raise Rejected("CAD şu an kapalı")
            try:
                return dict(await self._generator.cad(str(a.get("tool")), a.get("args") if isinstance(a.get("args"), dict) else {}))
            except Exception as exc:  # noqa: BLE001 - the CAD server's message is what the caller needs
                raise Rejected(str(exc)[:400]) from exc
        if op == "evolve":
            if self._evolver is None or self._evolver.busy():
                raise Rejected("kural evrimi çalışıyor ya da kapalı")
            return dict(self._evolver.start())
        if op == "design":
            if self._generator is None or self._generator.busy():
                raise Rejected("tasarım şu an yapılamıyor (meşgul ya da kapalı)")
            return dict(self._generator.start(str(a.get("brief") or "")[:900], CLOUD_ACTOR))
        if op == "decide":
            lesson = store.decide(str(a.get("id")), str(a.get("decision")))
            if lesson is None:
                raise Rejected("unknown lesson or decision")
            return {"lesson": lesson}
        if op == "note":
            ok = store.note(
                str(a.get("domain")),
                str(a.get("kind") or "web"),
                str(a.get("text") or ""),
                a.get("context"),
            )
            return {"noted": ok}
        if op == "world":
            from neml_brain.evolution.worlds import WorldStore

            return dict(
                WorldStore().create(
                    str(a.get("template") or "hobby_garden"),
                    int(a.get("difficulty") or 1),
                    int(a.get("seed") or 0),
                )
            )
        raise Rejected("op must be state, decide, note or world")

    async def _pose_op(self, a: dict[str, Any]) -> dict[str, Any]:
        model, op, name = a.get("model"), a.get("op"), a.get("name")
        if (
            self._poses is None
            or not isinstance(model, str)
            or op not in ("list", "save", "delete")
        ):
            raise Rejected("model and op (list, save, delete) are required")
        try:
            if op == "list":
                return {"poses": self._poses.list(model)}
            if not isinstance(name, str):
                raise Rejected("name is required")
            if op == "save":
                return {"poses": self._poses.save(model, name, a.get("values"))}
            return {"poses": self._poses.delete(model, name)}
        except PoseRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _import_scan(self, a: dict[str, Any]) -> dict[str, Any]:
        repo = a.get("repo")
        if self._importer is None or not isinstance(repo, str):
            raise Rejected("repo is required")
        try:
            return dict(await self._importer.scan(repo))
        except ImportRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _import_github(self, a: dict[str, Any]) -> dict[str, Any]:
        repo, branch, paths = a.get("repo"), a.get("branch") or "", a.get("paths") or []
        whole = a.get("all") is True
        if (
            self._importer is None
            or not isinstance(repo, str)
            or not isinstance(branch, str)
            or not isinstance(paths, list)
            or not all(isinstance(p, str) for p in paths)
            or not (paths or whole)
        ):
            raise Rejected("repo and either paths or all are required")
        genome_id, new_name = a.get("genomeId"), a.get("newName")
        try:
            return dict(
                await self._importer.import_files(
                    repo,
                    branch,
                    paths,
                    a.get("ack") is True,
                    genome_id if isinstance(genome_id, str) else None,
                    new_name if isinstance(new_name, str) else None,
                    CLOUD_ACTOR,
                    whole,
                )
            )
        except ImportRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _model_notes(self, a: dict[str, Any]) -> dict[str, Any]:
        if self._models is None:
            raise Rejected("this lab has no model editor")
        forget = a.get("forget")
        if isinstance(forget, str):
            self._models.researcher.base.forget(forget)
        return {"notes": self._models.notes()}

    async def _model_apply(self, a: dict[str, Any]) -> dict[str, Any]:
        genome_id = a.get("genomeId")
        if self._models is None or not isinstance(genome_id, str):
            raise Rejected("genomeId is required")
        try:
            return dict(await self._models.apply(genome_id, CLOUD_ACTOR))
        except ModelRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _task_create(self, a: dict[str, Any]) -> dict[str, Any]:
        body = snake(
            a,
            {
                "title": "title",
                "kind": "kind",
                "source": "source",
                "priority": "priority",
                "spec": "spec",
                "robotId": "robot_id",
                "deadline": "deadline",
            },
        )
        missing = [k for k in ("title", "kind", "source", "priority", "spec") if k not in body]
        if missing:
            raise Rejected(f"missing fields: {', '.join(missing)}")
        return await self._repo.create_task(body)

    async def _task_update(self, a: dict[str, Any]) -> dict[str, Any]:
        task_id = a.get("taskId")
        changes = snake(
            a,
            {
                "title": "title",
                "priority": "priority",
                "state": "state",
                "robotId": "robot_id",
                "deadline": "deadline",
            },
        )
        if not isinstance(task_id, str) or not changes:
            raise Rejected("taskId and at least one field are required")
        if isinstance(changes.get("deadline"), str):  # the column is timestamptz
            changes["deadline"] = datetime.fromisoformat(changes["deadline"])
        task = await self._repo.update_task(task_id, changes)
        if task is None:
            raise Rejected(f"no task {task_id}")
        return task

    async def _task_cancel(self, a: dict[str, Any]) -> dict[str, Any]:
        task_id = a.get("taskId")
        if not isinstance(task_id, str) or not await self._repo.cancel_task(task_id):
            raise Rejected(f"no task {task_id}")
        return {"taskId": task_id, "state": "cancelled"}

    async def _robot_estop(self, a: dict[str, Any]) -> dict[str, Any]:
        robot_id, reason = a.get("robotId"), a.get("reason") or "cloud e-stop"
        stopped = (
            await self._safety.software_estop(robot_id, CLOUD_ACTOR, str(reason))
            if isinstance(robot_id, str)
            else None
        )
        if stopped is None:
            raise Rejected(f"no robot {robot_id}")
        return stopped

    async def _print_cancel(self, a: dict[str, Any]) -> dict[str, Any]:
        job_id = a.get("jobId")
        if self._fab is None or not isinstance(job_id, str):
            raise Rejected("jobId is required and the lab must have a fab service")
        try:
            return await self._fab.cancel(job_id, a.get("reason"))
        except FabRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _print_qc(self, a: dict[str, Any]) -> dict[str, Any]:
        job_id, body = a.get("jobId"), a.get("form")
        if self._fab is None or not isinstance(job_id, str) or not isinstance(body, dict):
            raise Rejected("jobId and form are required and the lab must have a fab service")
        try:
            return await self._fab.submit_qc(job_id, body, a.get("genomeId"))
        except FabRejected as exc:
            raise Rejected(str(exc)) from exc

    async def _settings_get(self, a: dict[str, Any]) -> dict[str, Any]:
        model_id = a.get("modelId")
        if model_id is None:  # the list screen: every model and what is still open
            out = []
            for mid in await self._settings.model_ids():
                view = catalog.describe(mid, await self._settings.get(mid))
                out.append({"modelId": mid, "missingRequired": view["missing_required"]})
            return {"models": out}
        if model_id not in await self._settings.model_ids():
            raise Rejected(f"no model {model_id}")
        return catalog.describe(str(model_id), await self._settings.get(str(model_id)))

    async def _settings_put(self, a: dict[str, Any]) -> dict[str, Any]:
        model_id, values = a.get("modelId"), a.get("values")
        if not isinstance(model_id, str) or not isinstance(values, dict):
            raise Rejected("modelId and values are required")
        if model_id not in await self._settings.model_ids():
            raise Rejected(f"no model {model_id}")
        errors = catalog.validate(model_id, {k: v for k, v in values.items() if v is not None})
        if errors:
            raise Rejected("; ".join(errors))
        merged = await self._settings.put(model_id, values, str(a.get("by") or CLOUD_ACTOR))
        return catalog.describe(model_id, merged)


class ApprovalAnnouncer:
    """Tells the cloud about every pending approval, whichever process created it.

    The orchestrator, the deployment gate and the autonomy service all write
    `approvals` rows; this one poll covers all of them. The cloud insert is
    idempotent on the approval id, so re-sending after a restart is harmless and
    the in-memory set only saves bandwidth.
    """

    def __init__(
        self,
        pending: Callable[[], Awaitable[list[dict[str, Any]]]],
        send: Callable[..., Any],
    ) -> None:
        self._pending, self._send = pending, send
        self._announced: set[str] = set()

    async def announce(self) -> int:
        sent = 0
        for row in await self._pending():
            approval_id = str(row["id"])
            if approval_id in self._announced:
                continue
            self._send(
                "approval_request",
                {
                    "approvalId": approval_id,
                    "level": row["level"],
                    "subjectKind": row["subject_kind"],
                    "subjectId": row["subject_id"],
                    "expiresAt": row["expires_at"],
                    "payload": row.get("payload") or {},
                },
                idempotency_key=f"approval-request:{approval_id}",
            )
            self._announced.add(approval_id)
            sent += 1
        return sent
