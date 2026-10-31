// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Neml.Api.Contracts;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;
using Queue = Neml.Infrastructure.Repositories.CommandQueue;

namespace Neml.Api.Services;

/// <summary>
/// THE ONLY PATH FROM THIS SERVER TO THE LAB (spec 3.1, 19 risk 11). The remote API cannot
/// drive a robot: it has no connection towards the lab, no ROS, no PrusaLink client. Every
/// write in spec 9.3 ends here, as a row in the commands table, and the lab bridge decides
/// whether and when to apply it. Adding a controller path that reaches hardware any other
/// way breaks that guarantee — there is deliberately nothing here to reach it with.
///
/// Repeated idempotency keys are silently ignored and seq is the table BIGSERIAL, so a
/// reconnecting bridge can replay without duplicating anything (spec 3.1).
/// </summary>
public sealed class CommandQueue(NemlDbContext db)
{
    // commands.kind — the spec 9.3 write endpoints, one constant each.
    public const string RobotEstop = "robot.estop";
    public const string TaskCreate = "task.create";
    public const string TaskUpdate = "task.update";
    public const string TaskCancel = "task.cancel";
    public const string BrainCommand = "brain.command";
    public const string ModelChat = "model.chat";
    public const string ModelApply = "model.apply";
    public const string ModelPart = "model.part";
    public const string ModelDesign = "model.design";
    public const string ImportScan = "import.scan";
    public const string ImportGithub = "import.github";
    public const string ImportRefresh = "import.refresh";
    public const string ModelArchive = "model.archive";
    public const string PoseOp = "pose.op";
    public const string LearnOp = "learn.op";
    public const string ModelNotes = "model.notes";
    public const string CampaignCreate = "campaign.create";
    public const string CampaignStop = "campaign.stop";
    public const string ApprovalDecision = "approval.decision";
    public const string PrintCancel = "print.cancel";
    public const string PrintQc = "print.qc";

    private readonly Queue _queue = new(db);

    public async Task<CommandAccepted> EnqueueAsync(
        Guid userId, string kind, string payload, string idempotencyKey, CancellationToken ct)
    {
        var command = await _queue.EnqueueAsync(userId, kind, JsonDocument.Parse(payload), idempotencyKey, ct);
        return new CommandAccepted(command.Id, EnumText.Of(command.State), command.Seq);
    }

    /// <summary>Hands the next commands to the bridge and marks them delivered in one statement.</summary>
    public Task<IReadOnlyList<Command>> ClaimAsync(int max, CancellationToken ct) => _queue.ClaimAsync(max, ct);

    /// <summary>
    /// A lab that restarted loses the commands it was working on. The read-only and draft kinds are safe to
    /// run again, so they go back to pending when the lab reconnects (recent ones only).
    /// </summary>
    public Task<int> RequeueLostAsync(CancellationToken ct) => db.Database.ExecuteSqlRawAsync(
        "UPDATE commands SET state = 'pending' WHERE state = 'delivered' AND created_at > now() - interval '1 hour' " +
        "AND kind IN ('model.chat', 'model.part', 'model.notes')", ct);

    /// <summary>GET /brain/command/{id}. Null when the id is unknown.</summary>
    public async Task<CommandDto?> GetAsync(Guid id, CancellationToken ct)
    {
        // EnumText is a client side call, so the row is materialised before it is projected.
        var command = await db.Commands.AsNoTracking().FirstOrDefaultAsync(c => c.Id == id, ct);
        return command is null
            ? null
            : new CommandDto(
                command.Id, command.Seq, command.Kind, EnumText.Of(command.State),
                command.Result, command.CreatedAt, command.AppliedAt);
    }

    /// <summary>Records the lab's command_ack. A replayed ack on a finished command changes nothing.</summary>
    public Task<bool> AckAsync(Guid commandId, string state, string? result, CancellationToken ct) =>
        EnumText.TryParse<CommandState>(state, out var parsed)
            ? _queue.AckAsync(commandId, parsed, result is null ? null : JsonDocument.Parse(result), ct)
            : Task.FromResult(false);
}
