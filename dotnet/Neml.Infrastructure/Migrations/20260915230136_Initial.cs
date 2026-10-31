// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System;
using System.Text.Json;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Neml.Infrastructure.Migrations
{
    /// <inheritdoc />
    public partial class Initial : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AlterDatabase()
                .Annotation("Npgsql:PostgresExtension:pgcrypto", ",,");

            migrationBuilder.CreateTable(
                name: "approvals",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    level = table.Column<int>(type: "integer", nullable: false),
                    subject_kind = table.Column<string>(type: "text", nullable: false),
                    subject_id = table.Column<string>(type: "text", nullable: false),
                    payload = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    requested_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    expires_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    decided_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    decided_by = table.Column<string>(type: "text", nullable: true),
                    decision = table.Column<string>(type: "text", nullable: true),
                    note = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_approvals", x => x.id);
                    table.CheckConstraint("ck_approvals_decision", "decision IN ('approved','rejected','expired')");
                    table.CheckConstraint("ck_approvals_level", "level BETWEEN 1 AND 4");
                });

            migrationBuilder.CreateTable(
                name: "campaigns",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    name = table.Column<string>(type: "text", nullable: false),
                    objective = table.Column<string>(type: "text", nullable: false),
                    weights = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    budget = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    state = table.Column<string>(type: "text", nullable: false),
                    started_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    ended_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_campaigns", x => x.id);
                    table.CheckConstraint("ck_campaigns_state", "state IN ('active','stopped','completed')");
                });

            migrationBuilder.CreateTable(
                name: "genomes",
                columns: table => new
                {
                    id = table.Column<string>(type: "text", nullable: false),
                    name = table.Column<string>(type: "text", nullable: false),
                    version = table.Column<int>(type: "integer", nullable: false),
                    hash = table.Column<string>(type: "text", nullable: false),
                    parent_id = table.Column<string>(type: "text", nullable: true),
                    status = table.Column<string>(type: "text", nullable: false),
                    body = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    limits = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    fitness_score = table.Column<decimal>(type: "numeric(6,4)", precision: 6, scale: 4, nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_genomes", x => x.id);
                    table.CheckConstraint("ck_genomes_status", "status IN ('draft','testing','active','deprecated')");
                    table.ForeignKey(
                        name: "fk_genomes_genomes_parent_id",
                        column: x => x.parent_id,
                        principalTable: "genomes",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "users",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    email = table.Column<string>(type: "text", nullable: false),
                    password_hash = table.Column<string>(type: "text", nullable: false),
                    role = table.Column<string>(type: "text", nullable: false),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_users", x => x.id);
                    table.CheckConstraint("ck_users_role", "role IN ('owner','operator','viewer')");
                });

            migrationBuilder.CreateTable(
                name: "audit_log",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    ts = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    actor = table.Column<string>(type: "text", nullable: false),
                    action = table.Column<string>(type: "text", nullable: false),
                    target = table.Column<string>(type: "text", nullable: true),
                    params_hash = table.Column<string>(type: "text", nullable: true),
                    outcome = table.Column<string>(type: "text", nullable: true),
                    duration_ms = table.Column<int>(type: "integer", nullable: true),
                    approval_id = table.Column<Guid>(type: "uuid", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_audit_log", x => x.id);
                    table.ForeignKey(
                        name: "fk_audit_log_approvals_approval_id",
                        column: x => x.approval_id,
                        principalTable: "approvals",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "artifacts",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    kind = table.Column<string>(type: "text", nullable: false),
                    path = table.Column<string>(type: "text", nullable: false),
                    sha256 = table.Column<string>(type: "text", nullable: false),
                    genome_id = table.Column<string>(type: "text", nullable: true),
                    generator = table.Column<string>(type: "text", nullable: false),
                    input_hash = table.Column<string>(type: "text", nullable: true),
                    llm_model = table.Column<string>(type: "text", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_artifacts", x => x.id);
                    table.CheckConstraint("ck_artifacts_kind", "kind IN ('cad_src','step','stl','3mf','gcode','kicad','gerber','bom','urdf','bt')");
                    table.ForeignKey(
                        name: "fk_artifacts_genomes_genome_id",
                        column: x => x.genome_id,
                        principalTable: "genomes",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "bom_items",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    genome_id = table.Column<string>(type: "text", nullable: false),
                    @ref = table.Column<string>(name: "ref", type: "text", nullable: false),
                    part_number = table.Column<string>(type: "text", nullable: false),
                    qty = table.Column<int>(type: "integer", nullable: false),
                    unit_cost_try = table.Column<decimal>(type: "numeric(10,2)", precision: 10, scale: 2, nullable: true),
                    supplier = table.Column<string>(type: "text", nullable: true),
                    lead_time_days = table.Column<int>(type: "integer", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_bom_items", x => x.id);
                    table.ForeignKey(
                        name: "fk_bom_items_genomes_genome_id",
                        column: x => x.genome_id,
                        principalTable: "genomes",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "candidates",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    campaign_id = table.Column<Guid>(type: "uuid", nullable: false),
                    generation = table.Column<int>(type: "integer", nullable: false),
                    genome_id = table.Column<string>(type: "text", nullable: false),
                    @operator = table.Column<string>(name: "operator", type: "text", nullable: false),
                    rationale = table.Column<string>(type: "text", nullable: true),
                    llm_model = table.Column<string>(type: "text", nullable: true),
                    prompt_hash = table.Column<string>(type: "text", nullable: true),
                    fitness = table.Column<decimal>(type: "numeric(6,4)", precision: 6, scale: 4, nullable: true),
                    fitness_parts = table.Column<JsonDocument>(type: "jsonb", nullable: true),
                    verdict = table.Column<string>(type: "text", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_candidates", x => x.id);
                    table.CheckConstraint("ck_candidates_operator", "operator IN ('mutation','crossover','llm_guided','seed')");
                    table.CheckConstraint("ck_candidates_verdict", "verdict IN ('pending','sim_pass','sim_fail','real_pass','real_fail','accepted','rejected')");
                    table.ForeignKey(
                        name: "fk_candidates_campaigns_campaign_id",
                        column: x => x.campaign_id,
                        principalTable: "campaigns",
                        principalColumn: "id");
                    table.ForeignKey(
                        name: "fk_candidates_genomes_genome_id",
                        column: x => x.genome_id,
                        principalTable: "genomes",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "robots",
                columns: table => new
                {
                    id = table.Column<string>(type: "text", nullable: false),
                    genome_id = table.Column<string>(type: "text", nullable: false),
                    @namespace = table.Column<string>(name: "namespace", type: "text", nullable: false),
                    hostname = table.Column<string>(type: "text", nullable: false),
                    state = table.Column<string>(type: "text", nullable: false),
                    battery_soc = table.Column<decimal>(type: "numeric(4,3)", precision: 4, scale: 3, nullable: true),
                    last_seen = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    calibrated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    reality_gap = table.Column<decimal>(type: "numeric(5,4)", precision: 5, scale: 4, nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_robots", x => x.id);
                    table.CheckConstraint("ck_robots_state", "state IN ('offline','idle','charging','running','fault','estop','maintenance')");
                    table.ForeignKey(
                        name: "fk_robots_genomes_genome_id",
                        column: x => x.genome_id,
                        principalTable: "genomes",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "skills",
                columns: table => new
                {
                    id = table.Column<string>(type: "text", nullable: false),
                    skill_key = table.Column<string>(type: "text", nullable: false),
                    version = table.Column<int>(type: "integer", nullable: false),
                    genome_id = table.Column<string>(type: "text", nullable: false),
                    bt_path = table.Column<string>(type: "text", nullable: false),
                    parameters = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    preconditions = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    status = table.Column<string>(type: "text", nullable: false),
                    supersedes = table.Column<string>(type: "text", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_skills", x => x.id);
                    table.CheckConstraint("ck_skills_status", "status IN ('candidate','validated','retired')");
                    table.ForeignKey(
                        name: "fk_skills_genomes_genome_id",
                        column: x => x.genome_id,
                        principalTable: "genomes",
                        principalColumn: "id");
                    table.ForeignKey(
                        name: "fk_skills_skills_supersedes",
                        column: x => x.supersedes,
                        principalTable: "skills",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "commands",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    idempotency_key = table.Column<string>(type: "text", nullable: false),
                    seq = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    kind = table.Column<string>(type: "text", nullable: false),
                    payload = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    state = table.Column<string>(type: "text", nullable: false),
                    result = table.Column<JsonDocument>(type: "jsonb", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    applied_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_commands", x => x.id);
                    table.CheckConstraint("ck_commands_state", "state IN ('pending','delivered','applied','failed','rejected')");
                    table.ForeignKey(
                        name: "fk_commands_users_user_id",
                        column: x => x.user_id,
                        principalTable: "users",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "devices",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    platform = table.Column<string>(type: "text", nullable: false),
                    push_token = table.Column<string>(type: "text", nullable: true),
                    last_seen = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_devices", x => x.id);
                    table.CheckConstraint("ck_devices_platform", "platform IN ('android','ios','web')");
                    table.ForeignKey(
                        name: "fk_devices_users_user_id",
                        column: x => x.user_id,
                        principalTable: "users",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "refresh_tokens",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    token_hash = table.Column<string>(type: "text", nullable: false),
                    issued_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    expires_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    revoked_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    replaced_by = table.Column<Guid>(type: "uuid", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_refresh_tokens", x => x.id);
                    table.ForeignKey(
                        name: "fk_refresh_tokens_users_user_id",
                        column: x => x.user_id,
                        principalTable: "users",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "print_jobs",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    artifact_id = table.Column<Guid>(type: "uuid", nullable: false),
                    printer_id = table.Column<string>(type: "text", nullable: false),
                    profile_id = table.Column<string>(type: "text", nullable: false),
                    approval_id = table.Column<Guid>(type: "uuid", nullable: false),
                    est_time_h = table.Column<decimal>(type: "numeric(6,2)", precision: 6, scale: 2, nullable: true),
                    est_filament_g = table.Column<decimal>(type: "numeric(8,2)", precision: 8, scale: 2, nullable: true),
                    est_cost_try = table.Column<decimal>(type: "numeric(10,2)", precision: 10, scale: 2, nullable: true),
                    state = table.Column<string>(type: "text", nullable: false),
                    qc = table.Column<JsonDocument>(type: "jsonb", nullable: true),
                    started_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    ended_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_print_jobs", x => x.id);
                    table.CheckConstraint("ck_print_jobs_state", "state IN ('queued','printing','done','failed','cancelled')");
                    table.ForeignKey(
                        name: "fk_print_jobs_artifacts_artifact_id",
                        column: x => x.artifact_id,
                        principalTable: "artifacts",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "sim_runs",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    candidate_id = table.Column<Guid>(type: "uuid", nullable: true),
                    world_id = table.Column<string>(type: "text", nullable: false),
                    seed = table.Column<long>(type: "bigint", nullable: false),
                    profile = table.Column<string>(type: "text", nullable: false),
                    sim_version = table.Column<string>(type: "text", nullable: false),
                    duration_s = table.Column<decimal>(type: "numeric(8,2)", precision: 8, scale: 2, nullable: true),
                    metrics = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    deterministic = table.Column<bool>(type: "boolean", nullable: false, defaultValue: true),
                    run_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_sim_runs", x => x.id);
                    table.CheckConstraint("ck_sim_runs_profile", "profile IN ('fast','lidar','visual')");
                    table.ForeignKey(
                        name: "fk_sim_runs_candidates_candidate_id",
                        column: x => x.candidate_id,
                        principalTable: "candidates",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "safety_checks",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    robot_id = table.Column<string>(type: "text", nullable: false),
                    estop_ok = table.Column<bool>(type: "boolean", nullable: false),
                    watchdog_ok = table.Column<bool>(type: "boolean", nullable: false),
                    current_limit_ok = table.Column<bool>(type: "boolean", nullable: false),
                    performed_by = table.Column<string>(type: "text", nullable: false),
                    performed_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_safety_checks", x => x.id);
                    table.ForeignKey(
                        name: "fk_safety_checks_robots_robot_id",
                        column: x => x.robot_id,
                        principalTable: "robots",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "tasks",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    title = table.Column<string>(type: "text", nullable: false),
                    kind = table.Column<string>(type: "text", nullable: false),
                    source = table.Column<string>(type: "text", nullable: false),
                    priority = table.Column<decimal>(type: "numeric(6,3)", precision: 6, scale: 3, nullable: false),
                    state = table.Column<string>(type: "text", nullable: false),
                    robot_id = table.Column<string>(type: "text", nullable: true),
                    spec = table.Column<JsonDocument>(type: "jsonb", nullable: false),
                    result = table.Column<JsonDocument>(type: "jsonb", nullable: true),
                    deadline = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    updated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_tasks", x => x.id);
                    table.CheckConstraint("ck_tasks_kind", "kind IN ('human','repair','exploration','evolution','maintenance','calibration')");
                    table.CheckConstraint("ck_tasks_state", "state IN ('queued','planning','awaiting_approval','running','paused','succeeded','failed','cancelled')");
                    table.ForeignKey(
                        name: "fk_tasks_robots_robot_id",
                        column: x => x.robot_id,
                        principalTable: "robots",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "skill_validations",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    skill_id = table.Column<string>(type: "text", nullable: false),
                    env = table.Column<string>(type: "text", nullable: false),
                    trials = table.Column<int>(type: "integer", nullable: false),
                    successes = table.Column<int>(type: "integer", nullable: false),
                    ci95_low = table.Column<decimal>(type: "numeric(5,4)", precision: 5, scale: 4, nullable: false),
                    ci95_high = table.Column<decimal>(type: "numeric(5,4)", precision: 5, scale: 4, nullable: false),
                    seeds = table.Column<int[]>(type: "integer[]", nullable: false),
                    failure_modes = table.Column<JsonDocument>(type: "jsonb", nullable: false, defaultValueSql: "'[]'"),
                    run_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_skill_validations", x => x.id);
                    table.CheckConstraint("ck_skill_validations_env", "env IN ('sim','real')");
                    table.CheckConstraint("ck_skill_validations_trials", "trials > 0");
                    table.ForeignKey(
                        name: "fk_skill_validations_skills_skill_id",
                        column: x => x.skill_id,
                        principalTable: "skills",
                        principalColumn: "id");
                });

            migrationBuilder.CreateTable(
                name: "task_runs",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    task_id = table.Column<Guid>(type: "uuid", nullable: false),
                    attempt = table.Column<int>(type: "integer", nullable: false),
                    env = table.Column<string>(type: "text", nullable: false),
                    seed = table.Column<long>(type: "bigint", nullable: true),
                    started_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    ended_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    outcome = table.Column<string>(type: "text", nullable: true),
                    metrics = table.Column<JsonDocument>(type: "jsonb", nullable: true),
                    rosbag_path = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_task_runs", x => x.id);
                    table.CheckConstraint("ck_task_runs_env", "env IN ('sim','bench','tethered','free')");
                    table.CheckConstraint("ck_task_runs_outcome", "outcome IN ('success','failure','aborted','timeout')");
                    table.ForeignKey(
                        name: "fk_task_runs_tasks_task_id",
                        column: x => x.task_id,
                        principalTable: "tasks",
                        principalColumn: "id");
                });

            migrationBuilder.CreateIndex(
                name: "ix_artifacts_genome_id",
                table: "artifacts",
                column: "genome_id");

            migrationBuilder.CreateIndex(
                name: "ix_audit_log_approval_id",
                table: "audit_log",
                column: "approval_id");

            migrationBuilder.CreateIndex(
                name: "ix_audit_log_ts",
                table: "audit_log",
                column: "ts",
                descending: new bool[0]);

            migrationBuilder.CreateIndex(
                name: "ix_bom_items_genome_id",
                table: "bom_items",
                column: "genome_id");

            migrationBuilder.CreateIndex(
                name: "ix_candidates_campaign_id",
                table: "candidates",
                column: "campaign_id");

            migrationBuilder.CreateIndex(
                name: "ix_candidates_genome_id",
                table: "candidates",
                column: "genome_id");

            migrationBuilder.CreateIndex(
                name: "ix_commands_idempotency_key",
                table: "commands",
                column: "idempotency_key",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_commands_state_seq",
                table: "commands",
                columns: new[] { "state", "seq" });

            migrationBuilder.CreateIndex(
                name: "ix_commands_user_id",
                table: "commands",
                column: "user_id");

            migrationBuilder.CreateIndex(
                name: "ix_devices_user_id",
                table: "devices",
                column: "user_id");

            migrationBuilder.CreateIndex(
                name: "ix_genomes_hash",
                table: "genomes",
                column: "hash",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_genomes_parent_id",
                table: "genomes",
                column: "parent_id");

            migrationBuilder.CreateIndex(
                name: "ix_genomes_status",
                table: "genomes",
                column: "status");

            migrationBuilder.CreateIndex(
                name: "ix_print_jobs_artifact_id",
                table: "print_jobs",
                column: "artifact_id");

            migrationBuilder.CreateIndex(
                name: "ix_refresh_tokens_token_hash",
                table: "refresh_tokens",
                column: "token_hash",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_refresh_tokens_user_id",
                table: "refresh_tokens",
                column: "user_id");

            migrationBuilder.CreateIndex(
                name: "ix_robots_genome_id",
                table: "robots",
                column: "genome_id");

            migrationBuilder.CreateIndex(
                name: "ix_robots_namespace",
                table: "robots",
                column: "namespace",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_safety_checks_robot_id",
                table: "safety_checks",
                column: "robot_id");

            migrationBuilder.CreateIndex(
                name: "ix_sim_runs_candidate_id",
                table: "sim_runs",
                column: "candidate_id");

            migrationBuilder.CreateIndex(
                name: "ix_skill_validations_skill_id",
                table: "skill_validations",
                column: "skill_id");

            migrationBuilder.CreateIndex(
                name: "ix_skills_genome_id",
                table: "skills",
                column: "genome_id");

            migrationBuilder.CreateIndex(
                name: "ix_skills_skill_key_version",
                table: "skills",
                columns: new[] { "skill_key", "version" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_skills_supersedes",
                table: "skills",
                column: "supersedes");

            migrationBuilder.CreateIndex(
                name: "ix_task_runs_task_id_attempt",
                table: "task_runs",
                columns: new[] { "task_id", "attempt" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_tasks_robot_id",
                table: "tasks",
                column: "robot_id");

            migrationBuilder.CreateIndex(
                name: "ix_tasks_state_priority",
                table: "tasks",
                columns: new[] { "state", "priority" },
                descending: new[] { false, true });

            migrationBuilder.CreateIndex(
                name: "ix_users_email",
                table: "users",
                column: "email",
                unique: true);

            // Hand written: EF models neither PARTITION BY nor the monthly children, so the
            // telemetry parent of section 7 is raw SQL and the entity is ExcludeFromMigrations.
            // The current and next month are created here only so a fresh database accepts rows
            // immediately; every later month belongs to scripts/db/create_partitions.sh, which
            // runs on a systemd timer and uses the same telemetry_YYYY_MM naming.
            migrationBuilder.Sql(
                """
                CREATE TABLE telemetry (
                    ts        timestamptz      NOT NULL,
                    robot_id  text             NOT NULL,
                    metric    text             NOT NULL,
                    value     double precision NOT NULL,
                    tags      jsonb
                ) PARTITION BY RANGE (ts);

                CREATE INDEX ix_telemetry_robot_id_metric_ts ON telemetry (robot_id, metric, ts DESC);

                DO $$
                DECLARE m date;
                BEGIN
                    FOR m IN SELECT generate_series(date_trunc('month', now()),
                                                    date_trunc('month', now()) + interval '1 month',
                                                    interval '1 month')::date
                    LOOP
                        EXECUTE format(
                            'CREATE TABLE IF NOT EXISTS telemetry_%s PARTITION OF telemetry FOR VALUES FROM (%L) TO (%L)',
                            to_char(m, 'YYYY_MM'), m, (m + interval '1 month')::date);
                    END LOOP;
                END $$;
                """);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql("DROP TABLE IF EXISTS telemetry CASCADE;");

            migrationBuilder.DropTable(
                name: "audit_log");

            migrationBuilder.DropTable(
                name: "bom_items");

            migrationBuilder.DropTable(
                name: "commands");

            migrationBuilder.DropTable(
                name: "devices");

            migrationBuilder.DropTable(
                name: "print_jobs");

            migrationBuilder.DropTable(
                name: "refresh_tokens");

            migrationBuilder.DropTable(
                name: "safety_checks");

            migrationBuilder.DropTable(
                name: "sim_runs");

            migrationBuilder.DropTable(
                name: "skill_validations");

            migrationBuilder.DropTable(
                name: "task_runs");

            migrationBuilder.DropTable(
                name: "approvals");

            migrationBuilder.DropTable(
                name: "artifacts");

            migrationBuilder.DropTable(
                name: "users");

            migrationBuilder.DropTable(
                name: "candidates");

            migrationBuilder.DropTable(
                name: "skills");

            migrationBuilder.DropTable(
                name: "tasks");

            migrationBuilder.DropTable(
                name: "campaigns");

            migrationBuilder.DropTable(
                name: "robots");

            migrationBuilder.DropTable(
                name: "genomes");
        }
    }
}
