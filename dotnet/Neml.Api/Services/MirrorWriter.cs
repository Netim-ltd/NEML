// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Neml.Api.Bridge;
using Neml.Api.Contracts;
using Neml.Api.Hubs;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;

namespace Neml.Api.Services;

/// <summary>
/// The parts of neml_cloud the lab owns and the bridge keeps in step: robot state and
/// approval requests. Telemetry has its own path through
/// Neml.Infrastructure.Repositories.TelemetryRepository. No user request reaches these
/// writes — only an authenticated bridge node does.
/// </summary>
public sealed class MirrorWriter(NemlDbContext db)
{
    /// <summary>
    /// The lab tables the app reads but only the lab writes, with the columns an upsert may set.
    /// The names are the only text that reaches the SQL below; the row values travel as one jsonb
    /// parameter. Parents come first in a cycle (genomes, campaigns, tasks, then the rows that
    /// reference them), and the lab re-sends everything on a timer, so a row that lost a race
    /// with its parent lands on the next pass.
    /// </summary>
    private static readonly Dictionary<string, string[]> MirroredTables = new()
    {
        ["genomes"] = ["id", "name", "version", "hash", "parent_id", "status", "body", "limits", "fitness_score", "created_at"],
        ["campaigns"] = ["id", "name", "objective", "weights", "budget", "state", "started_at", "ended_at"],
        ["tasks"] = ["id", "title", "kind", "source", "priority", "state", "robot_id", "spec", "result", "deadline", "created_at", "updated_at"],
        ["candidates"] = ["id", "campaign_id", "generation", "genome_id", "operator", "rationale", "llm_model", "prompt_hash", "fitness", "fitness_parts", "verdict", "created_at"],
        ["task_runs"] = ["id", "task_id", "attempt", "env", "seed", "started_at", "ended_at", "outcome", "metrics", "rosbag_path"],
    };

    /// <summary>Upserts one batch of lab rows (<c>{table, rows}</c>). Returns the rows applied.</summary>
    public async Task<int> UpsertAsync(JsonElement batch, CancellationToken ct)
    {
        var table = batch.GetProperty("table").GetString() ?? "";
        if (!MirroredTables.TryGetValue(table, out var columns))
        {
            throw new JsonException($"'{table}' is not a mirrored table.");
        }

        var rows = batch.GetProperty("rows");
        if (rows.ValueKind != JsonValueKind.Array || rows.GetArrayLength() == 0)
        {
            return 0;
        }

        // Names come from the static map above, never from the message.
        var assignments = string.Join(", ", columns.Skip(1).Select(c => $"{c} = EXCLUDED.{c}"));
        var sql = $"INSERT INTO {table} SELECT * FROM jsonb_populate_recordset(NULL::{table}, CAST({{0}} AS jsonb)) "
                  + $"ON CONFLICT ({columns[0]}) DO UPDATE SET {assignments}";
#pragma warning disable EF1002 // identifiers are whitelisted constants; the values are a parameter
        return await db.Database.ExecuteSqlRawAsync(sql, [rows.GetRawText()], ct);
#pragma warning restore EF1002
    }

    /// <summary>Zero rows means the robot is not mirrored here yet; the lab stays authoritative.</summary>
    public Task<int> UpdateRobotStateAsync(RobotStatePayload state, CancellationToken ct)
    {
        if (!EnumText.TryParse<RobotState>(state.State, out var parsed))
        {
            return Task.FromResult(0);
        }

        var lastSeen = state.LastSeen ?? DateTimeOffset.UtcNow;
        return db.Robots
            .Where(r => r.Id == state.RobotId)
            .ExecuteUpdateAsync(s => s
                .SetProperty(r => r.State, parsed)
                .SetProperty(r => r.BatterySoc, state.BatterySoc)
                .SetProperty(r => r.LastSeen, lastSeen), ct);
    }

    /// <summary>Repeated requests for the same approval id are ignored (spec 3.1).</summary>
    public async Task<bool> InsertApprovalRequestAsync(ApprovalRequest request, CancellationToken ct)
    {
        if (await db.Approvals.AnyAsync(a => a.Id == request.ApprovalId, ct))
        {
            return false;
        }

        db.Approvals.Add(new Approval
        {
            Id = request.ApprovalId,
            Level = request.Level,
            SubjectKind = request.SubjectKind,
            SubjectId = request.SubjectId,
            Payload = request.Payload,
            ExpiresAt = request.ExpiresAt,
        });

        await db.SaveChangesAsync(ct);
        return true;
    }

    /// <summary>Mirrors lab audit rows so the app can read them (screen 12). The lab's envelope idempotency key already de-duplicates replays.</summary>
    public async Task InsertAuditAsync(IReadOnlyList<AuditPayload> rows, CancellationToken ct)
    {
        db.AuditLog.AddRange(rows.Select(r => new AuditLogEntry
        {
            Ts = r.Ts,
            Actor = r.Actor,
            Action = r.Action,
            Target = r.Target,
            Outcome = r.Outcome,
            DurationMs = r.DurationMs,
            ApprovalId = r.ApprovalId,
        }));
        await db.SaveChangesAsync(ct);
    }
}
