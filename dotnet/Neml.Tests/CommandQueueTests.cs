// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.EntityFrameworkCore;
using Neml.Api.Services;

namespace Neml.Tests;

/// <summary>
/// T-055 — the §7 commands table is the only path from the cloud to the lab. The queue leans
/// on BIGSERIAL, a unique index on idempotency_key and UPDATE … RETURNING with SKIP LOCKED,
/// so it is verified against the real PostgreSQL TestDb starts (§18.1 integration level).
/// </summary>
[Collection(NemlCloud.Name)]
public sealed class CommandQueueTests
{
    [Fact]
    public async Task A_duplicate_idempotency_key_applies_once()
    {
        await using var db = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(db);
        var queue = new CommandQueue(db);
        var key = Guid.NewGuid().ToString("N");

        var first = await queue.EnqueueAsync(user, CommandQueue.TaskCancel, """{"taskId":"a"}""", key, default);
        var second = await queue.EnqueueAsync(user, CommandQueue.TaskCancel, """{"taskId":"b"}""", key, default);

        Assert.Equal(first.CommandId, second.CommandId);
        Assert.Equal(first.Seq, second.Seq);

        await using var fresh = TestDb.Connect();
        Assert.Equal(1, await fresh.Commands.CountAsync(c => c.IdempotencyKey == key));

        // The first write wins; the replay never overwrites the stored payload.
        var stored = await fresh.Commands.AsNoTracking().FirstAsync(c => c.IdempotencyKey == key);
        Assert.Equal("a", stored.Payload.RootElement.GetProperty("taskId").GetString());
    }

    [Fact]
    public async Task Seq_is_monotonic()
    {
        await using var db = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(db);
        var queue = new CommandQueue(db);

        var seqs = new List<long>();
        for (var i = 0; i < 5; i++)
        {
            var accepted = await queue.EnqueueAsync(
                user, CommandQueue.BrainCommand, $$"""{"n":{{i}}}""", Guid.NewGuid().ToString("N"), default);
            seqs.Add(accepted.Seq);
        }

        Assert.Equal(seqs.Order().ToList(), seqs);
        Assert.Equal(seqs.Count, seqs.Distinct().Count());
    }

    [Fact]
    public async Task Claim_then_ack_completes_the_round_trip()
    {
        await using var db = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(db);
        var queue = new CommandQueue(db);

        var accepted = await queue.EnqueueAsync(
            user, CommandQueue.RobotEstop, """{"robotId":"R01"}""", Guid.NewGuid().ToString("N"), default);
        Assert.Equal("pending", accepted.State);

        var claimed = await queue.ClaimAsync(50, default);
        Assert.Contains(claimed, c => c.Id == accepted.CommandId);
        Assert.Equal("delivered", (await queue.GetAsync(accepted.CommandId, default))!.State);

        // Claiming again must not hand the same command to a second bridge.
        Assert.DoesNotContain(await queue.ClaimAsync(50, default), c => c.Id == accepted.CommandId);

        Assert.True(await queue.AckAsync(accepted.CommandId, "applied", """{"ok":true}""", default));

        var done = await queue.GetAsync(accepted.CommandId, default);
        Assert.Equal("applied", done!.State);
        Assert.NotNull(done.AppliedAt);

        // A replayed ack after a bridge reconnect changes nothing (§9.5 idempotency).
        Assert.False(await queue.AckAsync(accepted.CommandId, "failed", null, default));
        Assert.Equal("applied", (await queue.GetAsync(accepted.CommandId, default))!.State);
    }

    [Fact]
    public async Task An_unknown_command_or_state_is_refused()
    {
        await using var db = TestDb.Connect();
        var queue = new CommandQueue(db);

        Assert.Null(await queue.GetAsync(Guid.NewGuid(), default));
        Assert.False(await queue.AckAsync(Guid.NewGuid(), "applied", null, default));

        var user = await TestDb.SeedUserAsync(db);
        var accepted = await queue.EnqueueAsync(
            user, CommandQueue.PrintCancel, "{}", Guid.NewGuid().ToString("N"), default);

        // The bridge cannot invent a commands.state value outside the §7 CHECK constraint.
        Assert.False(await queue.AckAsync(accepted.CommandId, "half-applied", null, default));
        Assert.Equal("pending", (await queue.GetAsync(accepted.CommandId, default))!.State);
    }
}
