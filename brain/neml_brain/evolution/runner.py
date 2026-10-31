# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab's database-facing runner: the active genome of a model, new genomes, recorded
simulation runs and the 3D scenes published to the panel.

There are no evolution campaigns and no parametric templates any more: robots are designed by the
model through the CAD MCP (evolution/generative.py). This module only keeps what every design
needs: the genome rows, the recorded runs and the scenes.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import sqlalchemy as sa
import structlog
import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neml_brain.evolution.evaluator import BodyEvaluator, genome_hash
from neml_brain.evolution.mesh_formats import compact, stl_triangles
from neml_brain.evolution.model_scene import build_scene, scene_name
from neml_brain.evolution.recording import MediaUploader, live_name, media_entry
from neml_brain.learning.store import note as learn_note
from neml_brain.paths import REPO_ROOT

log = structlog.get_logger(__name__)

Sessions = async_sessionmaker[AsyncSession]


class Llm(Protocol):
    async def fill(
        self, prompt: str, schema: dict[str, Any], profile: str = ...
    ) -> dict[str, Any]: ...


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


class EvolutionRunner:
    def __init__(
        self,
        sessions: Sessions,
        evaluator: BodyEvaluator,
        llm: Llm | None,
        create_approval: Callable[..., Awaitable[str]],
        consume_sim: Callable[[float], Awaitable[Any]],
        notify: Callable[[dict[str, Any]], Awaitable[None]],
        genome_dir: Path | None = None,
        uploader: MediaUploader | None = None,
    ) -> None:
        self._sessions = sessions
        self.ev = evaluator
        self.llm = llm
        self._create_approval = create_approval
        self._consume_sim = consume_sim
        self._notify = notify
        self._genome_dir = genome_dir or REPO_ROOT / "hardware" / "genome"
        self._uploader = uploader
        self._mesh_urls: dict[str, str] = {}  # STL url -> compact mesh url

    # ------------------------------------------------------------------ db
    async def _one(self, session: AsyncSession, sql: str, **params: Any) -> dict[str, Any] | None:
        row = (await session.execute(sa.text(sql), params)).mappings().first()
        return None if row is None else dict(row)

    async def active_genome(self, model: str | None = None) -> dict[str, Any]:
        """The active genome of a model (default: any); a fresh database gets the seed genome."""
        sql = (
            "SELECT id, name, version, hash, body, fitness_score FROM genomes"
            " WHERE status = 'active' AND (CAST(:m AS text) IS NULL OR name = :m)"
            " ORDER BY created_at DESC LIMIT 1"
        )
        async with self._sessions() as session:
            found = await self._one(session, sql, m=model)
            if found:
                return found
            seed_file = sorted(self._genome_dir.glob("*.yaml"))[0]
            body = _jsonable(yaml.safe_load(seed_file.read_text(encoding="utf-8")))
            await session.execute(
                sa.text(
                    "INSERT INTO genomes (id, name, version, hash, status, body, limits)"
                    " VALUES (:id, :name, 1, :hash, 'active', CAST(:body AS jsonb),"
                    " CAST(:limits AS jsonb)) ON CONFLICT DO NOTHING"
                ),
                {
                    "id": f"{body['genome_id']}@{body['hash']}",
                    "name": body["genome_id"],
                    "hash": body["hash"],
                    "body": json.dumps(body),
                    "limits": json.dumps(body["limits"]),
                },
            )
            await session.commit()
            log.info("evolution.genome_seeded", genome=body["genome_id"], hash=body["hash"])
            found = await self._one(session, sql, m=model)
        if found is None:
            raise RuntimeError("seeding the active genome failed")
        return found

    async def _new_genome(
        self,
        session: AsyncSession,
        parent: Mapping[str, Any],
        body: dict[str, Any],
        status: str = "testing",
    ) -> tuple[str, dict[str, Any]]:
        """Insert a genome (candidate: testing, chat edit: draft); return its id and body."""
        body = {
            **body,
            "parent": parent["id"],
            "status": status,
            "created": datetime.now(UTC).date().isoformat(),
        }
        body["hash"] = genome_hash(body)
        name = str(body["genome_id"]).split("@")[0]
        genome_id = f"{name}@{body['hash']}"
        await session.execute(
            sa.text(
                "INSERT INTO genomes (id, name, version, hash, parent_id, status, body, limits)"
                " VALUES (:id, :name, :version, :hash, :parent, :status, CAST(:body AS jsonb),"
                " CAST(:limits AS jsonb)) ON CONFLICT (hash) DO NOTHING"
            ),
            {
                "id": genome_id,
                "name": name,
                "version": int(parent["version"]) + 1,
                "hash": body["hash"],
                "parent": parent["id"],
                "status": status,
                "body": json.dumps(_jsonable(body)),
                "limits": json.dumps(_jsonable(body["limits"])),
            },
        )
        return genome_id, body

    async def record_run(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        """A user-started recorded simulation run: choose the world, watch the chassis drive it."""
        world = str(spec.get("world_id", "flat"))
        seconds = float(spec.get("duration_s", 8.0))
        try:
            active = await self.active_genome(spec.get("model"))
        except RuntimeError:  # a draft-only or imported model has no simulatable body
            learn_note(
                "sim",
                "no_active_design",
                f"model {spec.get('model')}: aktif tasarım yok, koşu başlatılamadı",
            )
            return {
                "outcome": "failure",
                "metrics": {
                    "error": f"{spec.get('model')}: aktif tasarım yok (taslak ya da içe aktarılmış"
                    " model), simülasyon çalışmaz."
                },
            }
        mass = float(spec.get("mass_kg") or active["body"]["mechanical"]["body_mass_kg"])
        seed = int(spec.get("seed", 7))
        try:
            path, values = await self.ev.record(
                mass,
                seed,
                world,
                seconds,
                world,
                on_frame=self._live(spec.get("model") or active["name"]),
            )
        except Exception as exc:  # noqa: BLE001
            learn_note(
                "sim",
                "run_failed",
                f"koşu başarısız ({world}): {type(exc).__name__}: {str(exc)[:150]}",
            )
            return {
                "outcome": "failure",
                "metrics": {"error": f"{type(exc).__name__}: {str(exc)[:200]}"},
            }
        if values.get("safety_violation"):
            learn_note("sim", "tipped_over", f"robot {mass:.1f} kg ile {world} dünyasında devrildi")
        url = await self._uploader.upload(path) if self._uploader else None
        path.unlink(missing_ok=True)
        media = [media_entry("gif", url, f"{world} - {mass:.2f} kg")] if url else []
        reached = values.get("x_m", 0.0) >= 1.0 and not values.get("safety_violation")
        return {
            "outcome": "success",
            "metrics": {
                "world_id": world,
                "mass_kg": mass,
                "seed": seed,
                "x_m": round(values.get("x_m", 0.0), 3),
                "goal_reached": reached,
                "tipped_over": bool(values.get("safety_violation")),
                "media": media,
            },
        }

    async def publish_scenes(self) -> int:
        """Build and upload the 3D scene of every model's active genome. Returns how many."""
        if self._uploader is None:
            return 0
        await self.active_genome()  # seeds the first genome on a fresh database
        async with self._sessions() as session:
            rows = [
                dict(r)
                for r in (
                    await session.execute(
                        sa.text("SELECT id, body FROM genomes WHERE status = 'active'")
                    )
                ).mappings()
            ]
        published = 0
        for row in rows:
            try:
                published += await self._publish_scene(row["id"], row["body"])
            except Exception as exc:  # noqa: BLE001 - the panel just shows no 3D until the next try
                log.warning("evolution.scene_failed", genome=row["id"], error=str(exc)[:200])
        return published

    async def _upload_mesh(self, stl: Path, stl_url: str | None) -> None:
        """The compact mesh the viewer downloads in place of the STL (a fifth of the size)."""
        if stl_url is None or stl_url in self._mesh_urls or self._uploader is None:
            return
        try:
            small = stl.with_suffix(".nmesh")
            small.write_bytes(compact(stl_triangles(stl)))
            url = await self._uploader.upload(small, "nmesh")
            small.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - the viewer falls back to the STL
            log.warning("evolution.mesh_failed", error=str(exc)[:150])
            return
        if url:
            self._mesh_urls[stl_url] = url

    async def _publish_scene(self, genome_id: str, body: Mapping[str, Any]) -> int:
        if self._uploader is None:
            return 0
        scene = self.ev.dir / "models" / scene_name(genome_id)
        scene.parent.mkdir(parents=True, exist_ok=True)
        scene.write_text(
            json.dumps(build_scene(genome_id, body, {}, {}, self._mesh_urls)), encoding="utf-8"
        )
        url = await self._uploader.upload(scene, "json", name=scene.name)
        scene.unlink(missing_ok=True)
        log.info("evolution.scene_published", genome=genome_id)
        return 1 if url else 0

    def _live(self, model: str) -> Callable[[Any], Awaitable[None]] | None:
        """Upload each recorded frame as the model's `live` picture, so the panel can watch."""
        uploader = self._uploader
        if uploader is None:
            return None

        async def push(image: Any) -> None:
            import io

            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            path = self.ev.dir / "media" / live_name(model)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(buffer.getvalue())
            await uploader.upload(path, "png", name=path.name)
            path.unlink(missing_ok=True)

        return push
