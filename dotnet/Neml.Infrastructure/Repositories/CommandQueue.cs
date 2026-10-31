// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;
using Npgsql;

namespace Neml.Infrastructure.Repositories;

/// <summary>
/// The section 3.1 command queue. The lab never accepts an inbound connection, so mobile and
/// web write here and the bridge drains it. seq is the table BIGSERIAL, monotonic by
/// construction, and idempotency_key makes a replayed enqueue a no-op.
/// </summary>
public class CommandQueue(NemlDbContext db)
{
    /// <summary>Writes a command, or returns the one already stored under the same key.</summary>
    public async Task<Command> EnqueueAsync(
        Guid userId, string kind, JsonDocument payload, string idempotencyKey, CancellationToken ct = default)
    {
        if (await db.Commands.AsNoTracking().FirstOrDefaultAsync(c => c.IdempotencyKey == idempotencyKey, ct)
            is { } replay) return replay;

        var command = new Command
        {
            UserId = userId,
            Kind = kind,
            Payload = payload,
            IdempotencyKey = idempotencyKey,
            State = CommandState.Pending,
        };
        db.Commands.Add(command);
        try
        {
            await db.SaveChangesAsync(ct);
            return command;
        }
        catch (DbUpdateException ex)
            when ((ex.InnerException as PostgresException)?.SqlState == PostgresErrorCodes.UniqueViolation)
        {
            // Two clients raced on the same key; the loser reports the winner's command.
            db.Entry(command).State = EntityState.Detached;
            return await db.Commands.AsNoTracking().FirstAsync(c => c.IdempotencyKey == idempotencyKey, ct);
        }
    }

    /// <summary>
    /// Hands the next commands to the bridge and marks them delivered in the same statement.
    /// SKIP LOCKED keeps two API instances from delivering the same command twice.
    /// </summary>
    public async Task<IReadOnlyList<Command>> ClaimAsync(int max, CancellationToken ct = default) =>
        await db.Commands.FromSql(
            $"""
             UPDATE commands SET state = 'delivered'
             WHERE id IN (SELECT id FROM commands WHERE state = 'pending'
                          ORDER BY seq LIMIT {max} FOR UPDATE SKIP LOCKED)
             RETURNING *
             """).AsNoTracking().ToListAsync(ct);

    /// <summary>
    /// Records the lab's command_ack. Already terminal commands are left alone, so a replayed
    /// ack after a reconnect changes nothing. One conditional UPDATE rather than a read then a
    /// write: two acks racing after a reconnect would both pass a read-then-write guard, and
    /// the loser would overwrite the state the winner already recorded.
    /// </summary>
    public async Task<bool> AckAsync(
        Guid commandId, CommandState state, JsonDocument? result, CancellationToken ct = default) =>
        await db.Commands
            .Where(c => c.Id == commandId
                && c.State != CommandState.Applied
                && c.State != CommandState.Failed
                && c.State != CommandState.Rejected)
            .ExecuteUpdateAsync(s => s
                .SetProperty(c => c.State, state)
                .SetProperty(c => c.Result, result)
                .SetProperty(c => c.AppliedAt, (DateTimeOffset?)DateTimeOffset.UtcNow), ct) > 0;
}
