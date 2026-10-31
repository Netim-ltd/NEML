# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The robot-model chat: say "move the camera forward" or "make it carry more" and get an answer or a draft.

A message becomes one action, chosen by the language model under a grammar and carried out by code:

  explain    answer a question about the design (the model's own sentence, nothing executed)
  place      move or resize ONE part -> a DRAFT genome with a new `layout`
  redesign   ask the lab to design the robot again with the operator's wishes (the model + the CAD MCP,
             see generative.py); the result is a new model and appears on the learning page
  import     take a GitHub repository into this model
  learn      research a topic on the web and keep notes (RAG)
  simulate   queue a recorded simulation run in a chosen world

There are no parametric parameters to edit: parts are made by the model through the CAD MCP. Nothing
the chat does changes the active genome. A draft becomes active only through the owner's approval
(the manufacture gate); a design the lab itself made and verified is activated in simulation by
the lab (generative.py) and still needs the owner to print or build it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neml_brain.agents.base import untrusted
from neml_brain.evolution.evaluator import WORLDS
from neml_brain.evolution.knowledge import Researcher
from neml_brain.evolution.model_scene import build_scene
from neml_brain.evolution.runner import EvolutionRunner
from neml_brain.evolution.worlds import WorldStore

log = structlog.get_logger(__name__)

MAX_EDITS = 3
AXES = ("x", "y", "z", "sx", "sy", "sz")  # part centre x/y/z and box size x/y/z, mm

PROMPT = (
    "You are the design assistant of a robot model the lab designed. The operator writes in Turkish. "
    "Choose ONE action: 'explain' for a question about the design (use the fit check and the learned "
    "notes below); 'place' to move or resize ONE named part (placements: part id, axis x|y|z for its "
    "centre or sx|sy|sz for its box size, value in mm); 'redesign' when they want the robot changed in "
    "a way that needs new parts or a new layout (the lab designs it again; put their wish in 'reply'); "
    "'simulate' to run the robot in a world; 'learn' to research a topic on the web (topic = a short "
    "English search phrase); 'import' to take a GitHub repository into THIS model (repo = owner/name or "
    "the URL). Always fill 'reply' with one or two short Turkish sentences.\n"
    "Example: 'kamerayı 10 mm öne al' (camera centre x is 140 now) -> action place, placements "
    "[{{part: camera, axis: x, value: 150}}]; for any other action leave placements empty.\n"
    "Parts (id: label, centre x y z, box size x y z in mm):\n{parts}\n"
    "Fit check: {fit}\nImported items (with licence):\n{imports}\n"
    "Learned notes (from the web, unverified):\n{notes}\n"
    "Worlds: {worlds}; set world to the one asked for, else flat."
)


class Rejected(Exception):
    """The request is understood but not allowed or not possible."""


def imports_text(body: Mapping[str, Any]) -> str:
    """One line per imported item for the prompt (names are plain characters since the import)."""
    lines = []
    for e in body["mechanical"].get("imports", []):
        extra = ""
        if e["kind"] == "kicad":
            erc, drc = e.get("erc") or {}, e.get("drc") or {}
            extra = f", ERC errors {erc.get('errors', '?')}, DRC errors {drc.get('errors', '?')}"
        elif e["kind"] == "repo":
            a = e.get("analysis") or {}
            extra = f", {a.get('category', '?')}: {a.get('summary', '')}"
        elif e["kind"] == "urdf":
            u = e.get("urdf") or {}
            extra = f", {u.get('links', '?')} links, {u.get('movable_joints', '?')} movable joints"
        lines.append(f"- {e['id']}: {e['name']} ({e['kind']}, {e['repo']}, {e['license']}{extra})")
    return "\n".join(lines) or "(none)"


def scene_parts(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The parts of the genome's scene (no STL links needed to place them)."""
    return list(build_scene(str(body.get("genome_id", "x")), body)["parts"])


def apply_layout(
    body: Mapping[str, Any], placements: list[Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The body with part placements applied (mechanical.layout), and the list of changes."""
    parts = {p["id"]: p for p in scene_parts(body)}
    new = deepcopy(dict(body))
    layout = new["mechanical"].setdefault("layout", {})
    changes: list[dict[str, Any]] = []
    for item in placements[:MAX_EDITS]:
        pid, axis, value = str(item["part"]), str(item["axis"]), float(item["value"])
        part = parts.get(pid)
        if part is None or axis not in AXES:
            raise Rejected(
                f"'{pid}' bu modelde bir parça değil ya da '{axis}' geçerli bir eksen değil."
            )
        size_axis = axis.startswith("s")
        if size_axis and part["geom"]["type"] == "stl":
            raise Rejected(
                f"{part['label']} CAD ile üretilmiş bir parça: ölçüsünü 'yeniden tasarla' diyerek değiştir."
            )
        if size_axis and not 1 <= value <= 600:
            raise Rejected("Boyut 1–600 mm arasında olmalı.")
        i = "xyz".index(axis[-1])
        key = "size" if size_axis else "pos"
        base = part["geom"]["size"] if size_axis else part["pos"]
        current = list((layout.get(pid) or {}).get(key) or base)
        old = current[i]
        if abs(old - value) < 1e-6:
            continue
        current[i] = value
        layout.setdefault(pid, {})[key] = [round(float(v), 2) for v in current]
        changes.append({"parameter": f"{pid}.{axis}", "old": round(float(old), 2), "new": value})
    if not changes:
        raise Rejected("İstenen değerler zaten böyle; değiştirecek bir şey yok.")
    return new, changes


def action_schema(body: Mapping[str, Any]) -> dict[str, Any]:
    parts = [p["id"] for p in scene_parts(body)] or ["none"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "placements", "topic", "repo", "world", "reply"],
        "properties": {
            "action": {"enum": ["explain", "place", "redesign", "simulate", "learn", "import"]},
            "repo": {"type": "string", "maxLength": 100},
            "placements": {
                "type": "array",
                "maxItems": MAX_EDITS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["part", "axis", "value"],
                    "properties": {
                        "part": {"enum": parts},
                        "axis": {"enum": list(AXES)},
                        "value": {"type": "number", "minimum": -600, "maximum": 600},
                    },
                },
            },
            "topic": {"type": "string", "maxLength": 120},
            "world": {"enum": [*WORLDS, *sorted(WorldStore().index())]},
            "reply": {"type": "string", "maxLength": 400},
        },
    }


class ModelEditor:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        runner: EvolutionRunner,
        llm: Any,
        create_task: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        create_approval: Callable[..., Awaitable[str]],
        researcher: Researcher | None = None,
    ) -> None:
        self._sessions, self.runner, self.llm = sessions, runner, llm
        self.researcher = researcher
        self.importer: Any = None  # the GitHub importer, set once both exist
        self.generator: Any = None  # the lab's own designer (generative.py), set once both exist
        self._create_task = create_task
        self._create_approval = create_approval

    # ------------------------------------------------------------------ db
    async def _genome(self, genome_id: str) -> dict[str, Any]:
        async with self._sessions() as session:
            row = (
                (
                    await session.execute(
                        sa.text(
                            "SELECT id, name, version, status, body FROM genomes WHERE id = :id"
                        ),
                        {"id": genome_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise Rejected(f"genom bulunamadı: {genome_id}")
        return dict(row)

    # ---------------------------------------------------------------- chat
    async def chat(self, genome_id: str, text: str, actor: str, screen: str = "") -> dict[str, Any]:
        genome = await self._genome(genome_id)
        body = genome["body"]
        scene = build_scene(genome_id, body)
        parts = "\n".join(
            f"- {p['id']}: {p['label']}, {[round(v) for v in p['pos']]}, {p['geom']['size']}"
            for p in scene["parts"]
        )
        known = self.researcher.base.relevant(text) if self.researcher else []
        notes = "\n".join(f"- {n['title']}: {n['rule']} ({n['source']})" for n in known) or "(none)"
        try:  # what the owner accepted on the learning page (assembly, CAD and design lessons)
            from neml_brain.learning.propose import hints
            from neml_brain.learning.store import LearningStore

            store = LearningStore()
            lessons = chr(10).join(
                x
                for x in (hints(store, "assembly"), hints(store, "cad"), hints(store, "design"))
                if x
            )
            if lessons:
                notes += chr(10) + "Lessons accepted by the owner:" + chr(10) + lessons
        except OSError:
            pass
        prompt = PROMPT.format(
            parts=parts,
            fit=scene["fit"]["note"],
            imports=imports_text(body),
            notes=notes,
            worlds=", ".join(WORLDS),
        )
        out = await self.llm.fill(
            untrusted(prompt, f"{text}\n\n[Screen: {screen[:300]}]" if screen else text),
            action_schema(body),
            profile="param_skill",
        )
        action, reply = str(out["action"]), str(out.get("reply", "")).strip()
        log.info("model_chat.action", genome=genome_id, action=action, actor=actor)
        if action == "place":
            return await self.place(genome, list(out.get("placements") or []))
        if action == "import":
            return await self.import_repo(genome, str(out.get("repo") or ""))
        if action == "learn":
            return await self.learn(str(out.get("topic") or text))
        if action == "redesign":
            return await self.redesign(genome, text, reply)
        if action == "simulate":
            world = str(out.get("world") or "flat")
            task = await self._create_task(
                {
                    "title": f"Kayıtlı koşu: {world}",
                    "kind": "exploration",
                    "source": "user:chat",
                    "priority": 900,
                    "spec": {
                        "world_id": world,
                        "record": True,
                        "duration_s": 8,
                        "model": genome["name"],
                    },
                }
            )
            return {
                "action": "simulate",
                "reply": f"{world} dünyasında kayıtlı bir koşu kuyruğa aldım; Simülasyon sekmesinde belirir.",
                "task_id": task.get("id"),
            }
        return {"action": "explain", "reply": reply or "Bunu açıklayamadım."}

    async def redesign(self, genome: Mapping[str, Any], wish: str, reply: str) -> dict[str, Any]:
        """The operator wants new parts or a new layout: the lab designs the robot again with that wish."""
        if self.generator is None:
            return {"action": "redesign", "reply": "Tasarım servisi bu düğümde kapalı."}
        if self.generator.busy():
            return {
                "action": "redesign",
                "rejected": True,
                "reply": "Şu an bir tasarım yapılıyor; bitince yeniden iste.",
            }
        from neml_brain.learning.roundtable import summarize

        brief = f"{genome['name']} robotunun yeni sürümü. İstek: {wish[:300]}\nMevcut tasarım:\n{summarize(genome['body'])[:900]}"
        job = self.generator.start(brief, "chat")
        return {
            "action": "redesign",
            "job": job["id"],
            "reply": (reply or "Yeniden tasarlıyorum.")
            + " Tasarım birkaç on dakika sürer; ilerlemesi Öğrenme sayfasında.",
        }

    async def place(
        self, genome: Mapping[str, Any], placements: list[Mapping[str, Any]]
    ) -> dict[str, Any]:
        """Move or resize single parts: a draft with the new mechanical.layout."""
        if not placements:
            return {"action": "place", "reply": "Hangi parçayı nereye taşıyacağımı anlayamadım."}
        try:
            new_body, changes = apply_layout(genome["body"], placements)
        except Rejected as exc:
            return {"action": "place", "reply": str(exc), "rejected": True}
        return await self._draft("place", genome, new_body, changes)

    async def part_edit(
        self,
        genome_id: str,
        part: str,
        pos: list[float] | None,
        size: list[float] | None,
        params: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        """The part editor's form: position and box size in one draft (there are no template parameters)."""
        genome = await self._genome(genome_id)
        placements: list[Mapping[str, Any]] = [
            {"part": part, "axis": prefix + axis, "value": v}
            for prefix, vals in (("", pos), ("s", size))
            for axis, v in zip("xyz", vals or [], strict=False)
        ]
        try:
            body, changes = (
                apply_layout(genome["body"], placements) if placements else (genome["body"], [])
            )
        except Rejected as exc:
            return {"action": "part", "reply": str(exc), "rejected": True}
        if not changes:
            return {"action": "part", "reply": "Değişen bir değer yok."}
        return await self._draft("part", genome, body, changes)

    async def import_repo(self, genome: Mapping[str, Any], repo: str) -> dict[str, Any]:
        """Chat: take a whole GitHub repository into this model. A repository without a licence
        needs the explicit confirmation of the import panel."""
        if self.importer is None or not repo.strip():
            return {"action": "import", "reply": "Hangi GitHub deposunu alacağımı anlayamadım."}
        try:
            info = await self.importer.scan(repo)
            if info["license"] is None:
                return {
                    "action": "import",
                    "rejected": True,
                    "reply": f"{info['repo']} deposunun lisansı yok. Kullanım hakkı belirsiz; "
                    "asistandaki 'GitHub'dan al' bölümünden onaylayarak alabilirsin.",
                }
            done = await self.importer.import_files(
                repo, "", [], True, str(genome["id"]), None, "chat", True
            )
        except Exception as exc:  # noqa: BLE001 - say what went wrong instead of failing the chat
            return {"action": "import", "rejected": True, "reply": f"Alamadım: {str(exc)[:200]}"}
        return {"action": "import", "reply": done["reply"], "draft": done["draft"]}

    async def learn(self, topic: str) -> dict[str, Any]:
        if self.researcher is None:
            return {"action": "learn", "reply": "Araştırma bu düğümde kapalı."}
        try:
            got = await self.researcher.learn(topic)
        except Exception as exc:  # noqa: BLE001 - the web or the model failing must not fail the chat
            log.warning("model_chat.learn_failed", error=str(exc)[:200])
            return {"action": "learn", "reply": f"Araştıramadım: {str(exc)[:120]}"}
        n = len(got["notes"])
        if n:
            reply = f"{len(got['pages'])} sayfa okudum, {n} not öğrendim (doğrulanmamış olarak işaretli)."
        else:
            reply = "İlgili bir şey bulamadım." + (
                f" ({len(got['failed'])} sayfa açılmadı.)" if got["failed"] else ""
            )
        return {"action": "learn", "reply": reply, **got}

    def notes(self) -> list[dict[str, Any]]:
        return self.researcher.base.all() if self.researcher else []

    async def _draft(
        self,
        action: str,
        genome: Mapping[str, Any],
        new_body: dict[str, Any],
        changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self._sessions() as session:
            draft_id, draft_body = await self.runner._new_genome(  # noqa: SLF001
                session, genome, new_body, status="draft"
            )
            await session.commit()
        await self.runner._publish_scene(draft_id, draft_body)  # noqa: SLF001
        text = "; ".join(f"{c['parameter']} {c['old']} → {c['new']}" for c in changes)
        return {
            "action": action,
            "reply": f"Taslak hazır: {text}. 3B'de inceleyebilir, beğenirsen 'Uygula' ile onay isteyebilirsin.",
            "fit": build_scene(draft_id, draft_body)["fit"],
            "draft": {"id": draft_id, "changes": changes},
        }

    async def archive(self, name: str) -> dict[str, Any]:
        """Hide a model's drafts and tests (status deprecated); one with an active design stays."""
        async with self._sessions() as session:
            active = (
                await session.execute(
                    sa.text("SELECT 1 FROM genomes WHERE name = :n AND status = 'active' LIMIT 1"),
                    {"n": name},
                )
            ).first()
            if active is not None:
                raise Rejected("Aktif tasarımı olan model arşivlenemez.")
            done = await session.execute(
                sa.text(
                    "UPDATE genomes SET status = 'deprecated' WHERE name = :n AND status IN ('draft', 'testing')"
                ),
                {"n": name},
            )
            await session.commit()
        count = int(getattr(done, "rowcount", 0) or 0)
        if not count:
            raise Rejected("Arşivlenecek taslak bulunamadı.")
        return {"archived": count, "reply": f"{count} taslak arşivlendi."}

    # --------------------------------------------------------------- apply
    async def apply(self, genome_id: str, actor: str) -> dict[str, Any]:
        """Ask the owner (level 4) to make a draft the active genome."""
        genome = await self._genome(genome_id)
        if genome["status"] != "draft":
            raise Rejected("Yalnızca taslak bir tasarım uygulanabilir.")
        active = await self.runner.active_genome(genome["name"])
        approval_id = await self._create_approval(
            level=4,
            subject_kind="genome",
            subject_id=genome_id,
            payload={
                "summary": f"{genome['name']}: taslak tasarımı aktif yap",
                "genome": genome_id,
                "replaces": active["id"],
                "requested_by": actor,
            },
            idempotency_key=f"genome:{genome_id}",
        )
        return {
            "action": "apply",
            "approval_id": approval_id,
            "reply": "Onay istendi: Onaylar ekranında.",
        }

    async def on_decision(self, approval: Mapping[str, Any]) -> bool:
        """Called after any approval is decided. Activates the draft when the owner said yes."""
        if approval.get("subject_kind") != "genome" or approval.get("decision") != "approved":
            return False
        genome = await self._genome(str(approval["subject_id"]))
        if genome["status"] != "draft":
            return False
        async with self._sessions() as session:
            await session.execute(
                sa.text(
                    "UPDATE genomes SET status = 'deprecated' WHERE name = :n AND status IN ('active', 'draft') AND id <> :id"
                ),
                {"n": genome["name"], "id": genome["id"]},
            )
            await session.execute(
                sa.text("UPDATE genomes SET status = 'active' WHERE id = :id"), {"id": genome["id"]}
            )
            await session.commit()
        log.info("model_edit.activated", genome=genome["id"])
        return True
