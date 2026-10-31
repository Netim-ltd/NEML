# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# SQLAlchemy 2.0 mapping of the NEML_SPEC.md SPEC 7 schema. The SQL in SPEC 7 is the
# contract: column names, types, CHECK constraints, indexes, FKs and defaults follow it
# literally. Both databases (neml_local, neml_cloud) share this metadata; the tables named
# in CLOUD_ONLY exist only on neml_cloud.

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

# SPEC 7 prose: the schema is shared and neml_cloud merely carries extra tables.
CLOUD_ONLY = frozenset({"users", "devices", "commands"})

TZ = sa.TIMESTAMP(timezone=True)
NOW = sa.text("now()")
UUID_PK = sa.text("gen_random_uuid()")


class Vector(UserDefinedType[list[float]]):
    """pgvector column type.

    ponytail: hand-rolled because SPEC 1.3 / SPEC 8.1 never listed the `pgvector` package as a
    dependency. Text round-trip is fine for the one column that uses it; swap in the real
    `pgvector.sqlalchemy.Vector` if we ever need the binary protocol or the operator overloads.
    """

    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **_kw: Any) -> str:
        return f"vector({self.dim})"

    def bind_processor(self, dialect: sa.Dialect) -> Any:
        def process(value: Any) -> Any:
            if value is None:
                return None
            return "[" + ",".join(repr(float(v)) for v in value) + "]"

        return process

    def result_processor(self, dialect: sa.Dialect, coltype: Any) -> Any:
        def process(value: Any) -> Any:
            if value is None or not isinstance(value, str):
                return value
            return [float(x) for x in value.strip("[]").split(",") if x]

        return process


class Base(DeclarativeBase):
    pass


# ============ ROBOT & GENOME ============


class Genome(Base):
    __tablename__ = "genomes"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    hash: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    parent_id: Mapped[str | None] = mapped_column(sa.Text, sa.ForeignKey("genomes.id"))
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fitness_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 4))
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('draft','testing','active','deprecated')", name="genomes_status_check"
        ),
        sa.Index("genomes_status_idx", "status"),
        sa.Index("genomes_parent_id_idx", "parent_id"),
    )


class Robot(Base):
    __tablename__ = "robots"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    genome_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("genomes.id"), nullable=False)
    namespace: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    hostname: Mapped[str] = mapped_column(sa.Text, nullable=False)
    state: Mapped[str] = mapped_column(sa.Text, nullable=False)
    battery_soc: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 3))
    last_seen: Mapped[dt.datetime | None] = mapped_column(TZ)
    calibrated_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    reality_gap: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 4))
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('offline','idle','charging','running','fault','estop','maintenance')",
            name="robots_state_check",
        ),
    )


# ============ SKILL ============


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    skill_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    genome_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("genomes.id"), nullable=False)
    bt_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    preconditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    supersedes: Mapped[str | None] = mapped_column(sa.Text, sa.ForeignKey("skills.id"))
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('candidate','validated','retired')", name="skills_status_check"
        ),
        sa.UniqueConstraint("skill_key", "version", name="skills_skill_key_version_key"),
    )


class SkillValidation(Base):
    __tablename__ = "skill_validations"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("skills.id"), nullable=False)
    env: Mapped[str] = mapped_column(sa.Text, nullable=False)
    trials: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    successes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    ci95_low: Mapped[Decimal] = mapped_column(sa.Numeric(5, 4), nullable=False)
    ci95_high: Mapped[Decimal] = mapped_column(sa.Numeric(5, 4), nullable=False)
    seeds: Mapped[list[int]] = mapped_column(ARRAY(sa.Integer), nullable=False)
    failure_modes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'")
    )
    run_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint("env IN ('sim','real')", name="skill_validations_env_check"),
        sa.CheckConstraint("trials > 0", name="skill_validations_trials_check"),
    )


class SkillRun(Base):
    """One trial per row (ADR-011, amends SPEC 7).

    `skill_validations` aggregates trials/successes, so SPEC 14.2's "success below 70% over a
    skill's last 20 runs" and SPEC 14.6 step 4 had no row to count. This is that row, and it
    carries `deterministic` so SPEC 11.2 rule 3 can be applied in the query the way sim_runs
    already does.
    """

    __tablename__ = "skill_runs"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("skills.id"), nullable=False)
    task_run_id: Mapped[int | None] = mapped_column(sa.BigInteger, sa.ForeignKey("task_runs.id"))
    env: Mapped[str] = mapped_column(sa.Text, nullable=False)
    seed: Mapped[int | None] = mapped_column(sa.BigInteger)
    success: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    failure_mode: Mapped[str | None] = mapped_column(sa.Text)
    deterministic: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("TRUE")
    )
    run_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint("env IN ('sim','real')", name="skill_runs_env_check"),
        sa.Index("skill_runs_skill_id_run_at_idx", "skill_id", sa.text("run_at DESC")),
    )


# ============ TASK ============


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source: Mapped[str] = mapped_column(sa.Text, nullable=False)
    priority: Mapped[Decimal] = mapped_column(sa.Numeric(6, 3), nullable=False)
    state: Mapped[str] = mapped_column(sa.Text, nullable=False)
    robot_id: Mapped[str | None] = mapped_column(sa.Text, sa.ForeignKey("robots.id"))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    deadline: Mapped[dt.datetime | None] = mapped_column(TZ)
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)
    updated_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint(
            "kind IN ('human','repair','exploration','evolution','maintenance','calibration')",
            name="tasks_kind_check",
        ),
        sa.CheckConstraint(
            "state IN ('queued','planning','awaiting_approval','running','paused',"
            "'succeeded','failed','cancelled')",
            name="tasks_state_check",
        ),
        sa.Index("tasks_state_priority_idx", "state", sa.text("priority DESC")),
    )


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[Any] = mapped_column(sa.Uuid, sa.ForeignKey("tasks.id"), nullable=False)
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    env: Mapped[str] = mapped_column(sa.Text, nullable=False)
    seed: Mapped[int | None] = mapped_column(sa.BigInteger)
    started_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False)
    ended_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    outcome: Mapped[str | None] = mapped_column(sa.Text)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rosbag_path: Mapped[str | None] = mapped_column(sa.Text)

    __table_args__ = (
        sa.CheckConstraint("env IN ('sim','bench','tethered','free')", name="task_runs_env_check"),
        sa.CheckConstraint(
            "outcome IN ('success','failure','aborted','timeout')", name="task_runs_outcome_check"
        ),
        sa.UniqueConstraint("task_id", "attempt", name="task_runs_task_id_attempt_key"),
    )


# ============ EVOLUTION ============


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    objective: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # SPEC 14.3: frozen at campaign start, guarded by the 0002 trigger.
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    budget: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(sa.Text, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)
    ended_at: Mapped[dt.datetime | None] = mapped_column(TZ)

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('active','stopped','completed')", name="campaigns_state_check"
        ),
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    campaign_id: Mapped[Any] = mapped_column(sa.Uuid, sa.ForeignKey("campaigns.id"), nullable=False)
    generation: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    genome_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("genomes.id"), nullable=False)
    operator: Mapped[str] = mapped_column(sa.Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(sa.Text)
    llm_model: Mapped[str | None] = mapped_column(sa.Text)
    prompt_hash: Mapped[str | None] = mapped_column(sa.Text)
    fitness: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 4))
    fitness_parts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    verdict: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint(
            "operator IN ('mutation','crossover','llm_guided','seed')",
            name="candidates_operator_check",
        ),
        sa.CheckConstraint(
            "verdict IN ('pending','sim_pass','sim_fail','real_pass','real_fail',"
            "'accepted','rejected')",
            name="candidates_verdict_check",
        ),
    )


class SimRun(Base):
    __tablename__ = "sim_runs"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[Any | None] = mapped_column(sa.Uuid, sa.ForeignKey("candidates.id"))
    world_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    seed: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    profile: Mapped[str] = mapped_column(sa.Text, nullable=False)
    sim_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    duration_s: Mapped[Decimal | None] = mapped_column(sa.Numeric(8, 2))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    deterministic: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("TRUE")
    )
    run_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint("profile IN ('fast','lidar','visual')", name="sim_runs_profile_check"),
    )


# ============ MANUFACTURING ============


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    sha256: Mapped[str] = mapped_column(sa.Text, nullable=False)
    genome_id: Mapped[str | None] = mapped_column(sa.Text, sa.ForeignKey("genomes.id"))
    generator: Mapped[str] = mapped_column(sa.Text, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(sa.Text)
    llm_model: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint(
            "kind IN ('cad_src','step','stl','3mf','gcode','kicad','gerber','bom','urdf','bt')",
            name="artifacts_kind_check",
        ),
    )


class PrintJob(Base):
    __tablename__ = "print_jobs"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    artifact_id: Mapped[Any] = mapped_column(sa.Uuid, sa.ForeignKey("artifacts.id"), nullable=False)
    printer_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    approval_id: Mapped[Any] = mapped_column(sa.Uuid, nullable=False)
    est_time_h: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 2))
    est_filament_g: Mapped[Decimal | None] = mapped_column(sa.Numeric(8, 2))
    est_cost_try: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 2))
    state: Mapped[str] = mapped_column(sa.Text, nullable=False)
    qc: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    ended_at: Mapped[dt.datetime | None] = mapped_column(TZ)

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('queued','printing','done','failed','cancelled')",
            name="print_jobs_state_check",
        ),
    )


class BomItem(Base):
    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    genome_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("genomes.id"), nullable=False)
    ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    part_number: Mapped[str] = mapped_column(sa.Text, nullable=False)
    qty: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    unit_cost_try: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 2))
    supplier: Mapped[str | None] = mapped_column(sa.Text)
    lead_time_days: Mapped[int | None] = mapped_column(sa.Integer)


# ============ TELEMETRY (monthly partitions) ============


class Telemetry(Base):
    """SPEC 7: no primary key, PARTITION BY RANGE (ts).

    ponytail: declarative needs *something* to identify a row, so the mapper gets a synthetic
    key over (ts, robot_id, metric). The real table stays PK-free exactly as SPEC 7 writes it.
    """

    __tablename__ = "telemetry"

    ts: Mapped[dt.datetime] = mapped_column(TZ, nullable=False)
    robot_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    metric: Mapped[str] = mapped_column(sa.Text, nullable=False)
    value: Mapped[float] = mapped_column(sa.Double, nullable=False)
    tags: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __mapper_args__ = {"primary_key": ["ts", "robot_id", "metric"]}
    __table_args__ = (
        sa.Index("telemetry_robot_id_metric_ts_idx", "robot_id", "metric", sa.text("ts DESC")),
        {"postgresql_partition_by": "RANGE (ts)"},
    )


# ============ BUDGET ============


class BudgetUsage(Base):
    """SPEC 14.4 daily counters, persisted (ADR-011, amends SPEC 7).

    T-084 wants 72 uninterrupted hours with no budget overrun, which in-process counters
    cannot promise across a restart. Reset is implicit: a new day is a new row, so there is
    no reset job. `pcb_orders` is the one monthly budget (SPEC 14.4) and keys on the first
    day of its month.
    """

    __tablename__ = "budget_usage"

    day: Mapped[dt.date] = mapped_column(sa.Date, primary_key=True)
    resource: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    used: Mapped[Decimal] = mapped_column(
        sa.Numeric(14, 4), nullable=False, server_default=sa.text("0")
    )


# ============ SAFETY & AUDIT ============


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    level: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    subject_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requested_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)
    expires_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False)
    decided_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    decided_by: Mapped[str | None] = mapped_column(sa.Text)
    decision: Mapped[str | None] = mapped_column(sa.Text)
    note: Mapped[str | None] = mapped_column(sa.Text)

    __table_args__ = (
        sa.CheckConstraint("level BETWEEN 1 AND 4", name="approvals_level_check"),
        sa.CheckConstraint(
            "decision IN ('approved','rejected','expired')", name="approvals_decision_check"
        ),
    )


class SafetyCheck(Base):
    __tablename__ = "safety_checks"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    robot_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("robots.id"), nullable=False)
    estop_ok: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    watchdog_ok: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    current_limit_ok: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    performed_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    performed_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)
    actor: Mapped[str] = mapped_column(sa.Text, nullable=False)
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    target: Mapped[str | None] = mapped_column(sa.Text)
    params_hash: Mapped[str | None] = mapped_column(sa.Text)
    outcome: Mapped[str | None] = mapped_column(sa.Text)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer)
    approval_id: Mapped[Any | None] = mapped_column(sa.Uuid, sa.ForeignKey("approvals.id"))

    __table_args__ = (sa.Index("audit_log_ts_idx", sa.text("ts DESC")),)


# ============ MEMORY (pgvector) ============


class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    source_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_id: Mapped[str | None] = mapped_column(sa.Text)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.Index(
            "memory_chunks_embedding_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


# ============ neml_cloud ONLY ============


class User(Base):
    __tablename__ = "users"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    email: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)  # argon2id
    role: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint("role IN ('owner','operator','viewer')", name="users_role_check"),
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    user_id: Mapped[Any] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), nullable=False)
    platform: Mapped[str] = mapped_column(sa.Text, nullable=False)
    push_token: Mapped[str | None] = mapped_column(sa.Text)
    last_seen: Mapped[dt.datetime | None] = mapped_column(TZ)

    __table_args__ = (
        sa.CheckConstraint("platform IN ('android','ios','web')", name="devices_platform_check"),
    )


class Command(Base):
    __tablename__ = "commands"

    id: Mapped[Any] = mapped_column(sa.Uuid, primary_key=True, server_default=UUID_PK)
    user_id: Mapped[Any] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    # SPEC 7 declares BIGSERIAL here even though it is not the primary key.
    seq: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.Sequence("commands_seq_seq"),
        nullable=False,
        server_default=sa.text("nextval('commands_seq_seq')"),
    )
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(sa.Text, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=NOW)
    applied_at: Mapped[dt.datetime | None] = mapped_column(TZ)

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('pending','delivered','applied','failed','rejected')",
            name="commands_state_check",
        ),
        sa.Index("commands_state_seq_idx", "state", "seq"),
    )
