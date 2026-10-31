// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Neml.Infrastructure.Migrations
{
    /// <inheritdoc />
    public partial class SkillRunsAndBudgetUsage : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "budget_usage",
                columns: table => new
                {
                    day = table.Column<DateOnly>(type: "date", nullable: false),
                    resource = table.Column<string>(type: "text", nullable: false),
                    used = table.Column<decimal>(type: "numeric(14,4)", precision: 14, scale: 4, nullable: false, defaultValueSql: "0")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_budget_usage", x => new { x.day, x.resource });
                });

            migrationBuilder.CreateTable(
                name: "skill_runs",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    skill_id = table.Column<string>(type: "text", nullable: false),
                    task_run_id = table.Column<long>(type: "bigint", nullable: true),
                    env = table.Column<string>(type: "text", nullable: false),
                    seed = table.Column<long>(type: "bigint", nullable: true),
                    success = table.Column<bool>(type: "boolean", nullable: false),
                    failure_mode = table.Column<string>(type: "text", nullable: true),
                    deterministic = table.Column<bool>(type: "boolean", nullable: false, defaultValue: true),
                    run_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_skill_runs", x => x.id);
                    table.CheckConstraint("ck_skill_runs_env", "env IN ('sim','real')");
                    table.ForeignKey(
                        name: "fk_skill_runs_skills_skill_id",
                        column: x => x.skill_id,
                        principalTable: "skills",
                        principalColumn: "id");
                    table.ForeignKey(
                        name: "fk_skill_runs_task_runs_task_run_id",
                        column: x => x.task_run_id,
                        principalTable: "task_runs",
                        principalColumn: "id");
                });

            migrationBuilder.CreateIndex(
                name: "ix_skill_runs_skill_id_run_at",
                table: "skill_runs",
                columns: new[] { "skill_id", "run_at" },
                descending: new[] { false, true });

            migrationBuilder.CreateIndex(
                name: "ix_skill_runs_task_run_id",
                table: "skill_runs",
                column: "task_run_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "budget_usage");

            migrationBuilder.DropTable(
                name: "skill_runs");
        }
    }
}
