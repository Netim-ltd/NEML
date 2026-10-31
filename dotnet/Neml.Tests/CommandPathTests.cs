// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Reflection;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Routing;
using Microsoft.EntityFrameworkCore;
using Neml.Api.Contracts;
using Neml.Api.Controllers;
using Neml.Domain.Dtos;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using ApiQueue = Neml.Api.Services.CommandQueue;
using Queue = Neml.Infrastructure.Repositories.CommandQueue;

namespace Neml.Tests;

/// <summary>
/// §3.1 and §19 risk 11: the commands table is the only way from this server to a robot, and
/// it has to survive a bridge that reconnects and replays. Every case here runs against the
/// real PostgreSQL, because the guarantees are the unique index, BIGSERIAL, SKIP LOCKED and
/// row locking rather than anything C# does.
/// </summary>
[Collection(NemlCloud.Name)]
public sealed class CommandPathTests : IDisposable
{
    private readonly ApiFactory factory = new();

    public void Dispose() => factory.Dispose();

    private static JsonDocument Json(string raw = "{}") => JsonDocument.Parse(raw);

    // ---------- §19 risk 11: no path to hardware but the queue ----------

    /// <summary>
    /// Nothing in Neml.Api can open a connection towards the lab. §3.1 gives the server no
    /// route inwards at all — the bridge dials out — so a type here that held an HttpClient or
    /// a client socket would be the beginning of one.
    /// </summary>
    [ApiFact]
    public void Nothing_in_the_api_can_dial_out_towards_a_robot()
    {
        Type[] dialers =
        [
            typeof(HttpClient),
            typeof(IHttpClientFactory),
            typeof(System.Net.WebSockets.ClientWebSocket),
            typeof(System.Net.Sockets.Socket),
            typeof(System.Net.Sockets.TcpClient),
        ];

        var found = new List<string>();
        foreach (var type in ApiSurface.Assembly.GetTypes().Where(t => !t.Name.StartsWith('<')))
        {
            const BindingFlags All = BindingFlags.Public | BindingFlags.NonPublic
                | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

            var used = type.GetFields(All).Select(f => f.FieldType)
                .Concat(type.GetProperties(All).Select(p => p.PropertyType))
                .Concat(type.GetConstructors(All).SelectMany(c => c.GetParameters()).Select(p => p.ParameterType))
                .Concat(type.GetMethods(All).SelectMany(m => m.GetParameters()).Select(p => p.ParameterType));

            found.AddRange(used.Where(dialers.Contains).Select(t => $"{type.FullName} holds {t.Name}"));
        }

        Assert.True(found.Count == 0, string.Join(Environment.NewLine, found.Distinct()));
    }

    /// <summary>
    /// Every §9.3 write answers with a queue receipt. An action that answered with anything
    /// else would be doing the work here instead of handing it to the lab.
    /// </summary>
    [ApiFact]
    public void Every_mutating_endpoint_answers_with_a_queue_receipt()
    {
        // AuthController only manages this server's own session, BotController only creates this
        // server's own bot logins (no lab state), and BridgeController is the lab end of the queue
        // rather than a user of it.
        string[] exempt = ["AuthController", "BotController", "BridgeController"];

        var wrong = new List<string>();
        foreach (var controller in ApiSurface.Controllers.Where(c => !exempt.Contains(c.Name)))
        {
            foreach (var action in controller.GetMethods(
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            {
                var verbs = action.GetCustomAttributes<HttpMethodAttribute>()
                    .SelectMany(v => v.HttpMethods)
                    .Where(m => m is not ("GET" or "HEAD" or "OPTIONS"))
                    .ToArray();

                if (verbs.Length == 0)
                {
                    continue;
                }

                var returns = action.ReturnType;
                if (returns.IsGenericType && returns.GetGenericTypeDefinition() == typeof(Task<>))
                {
                    returns = returns.GetGenericArguments()[0];
                }

                var payload = returns.IsGenericType ? returns.GetGenericArguments()[0] : returns;
                if (payload != typeof(CommandAccepted))
                {
                    wrong.Add($"{controller.Name}.{action.Name} -> {payload.Name}");
                }
            }
        }

        Assert.True(wrong.Count == 0, string.Join(Environment.NewLine, wrong));
    }

    /// <summary>
    /// The same guarantee at run time: an e-stop is the most urgent write §9.3 has, and even
    /// that one only leaves a pending row behind. The robot is not touched.
    /// </summary>
    [ApiFact]
    public async Task An_estop_leaves_a_pending_row_and_never_changes_the_robot()
    {
        var (robot, before) = await SeedRobotAsync();
        using var client = await OperatorClientAsync();

        var response = await client.PostAsJsonAsync($"api/v1/robots/{robot}/estop", new EstopRequest("kaza"));
        var accepted = await response.Content.ReadFromJsonAsync<CommandAccepted>();

        await using var db = TestDb.Connect();
        var stored = await db.Commands.AsNoTracking().FirstAsync(c => c.Id == accepted!.CommandId);
        Assert.Equal(ApiQueue.RobotEstop, stored.Kind);
        Assert.Equal(CommandState.Pending, stored.State);
        Assert.Null(stored.AppliedAt);

        var after = await db.Robots.AsNoTracking().FirstAsync(r => r.Id == robot);
        Assert.Equal(before, after.State);       // Still whatever the lab last said it was.
        Assert.Null(after.LastSeen);
    }

    // ---------- §3.1 idempotency under concurrency ----------

    /// <summary>
    /// Two clients racing on one Idempotency-Key. The loser's INSERT blocks on the unique
    /// index until the winner commits, so it can only ever find out afterwards — the branch
    /// the pre-flight SELECT cannot cover.
    /// </summary>
    [Fact]
    public async Task Two_writers_racing_on_one_idempotency_key_store_one_command()
    {
        await using var winner = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(winner);
        var key = Guid.NewGuid().ToString("N");

        await using var transaction = await winner.Database.BeginTransactionAsync();
        var first = await new Queue(winner).EnqueueAsync(user, ApiQueue.TaskCancel, Json("""{"who":"winner"}"""), key);

        await using var loser = TestDb.Connect();
        var race = Task.Run(() =>
            new Queue(loser).EnqueueAsync(user, ApiQueue.TaskCancel, Json("""{"who":"loser"}"""), key));

        // Long enough for the loser to get past its SELECT and block on the index.
        await Task.Delay(TimeSpan.FromMilliseconds(500));
        await transaction.CommitAsync();

        var second = await race;
        Assert.Equal(first.Id, second.Id);
        Assert.Equal(first.Seq, second.Seq);

        await using var fresh = TestDb.Connect();
        Assert.Equal(1, await fresh.Commands.CountAsync(c => c.IdempotencyKey == key));
        var stored = await fresh.Commands.AsNoTracking().FirstAsync(c => c.IdempotencyKey == key);
        Assert.Equal("winner", stored.Payload.RootElement.GetProperty("who").GetString());
    }

    [Fact]
    public async Task Parallel_writers_get_distinct_seq_values_that_only_go_up()
    {
        await using var seed = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(seed);
        var floor = await seed.Commands.AnyAsync()
            ? await seed.Commands.MaxAsync(c => c.Seq)
            : 0L;

        var seqs = new ConcurrentBag<long>();
        await Parallel.ForEachAsync(Enumerable.Range(0, 16), async (i, ct) =>
        {
            await using var db = TestDb.Connect();
            var command = await new Queue(db).EnqueueAsync(
                user, ApiQueue.BrainCommand, Json($$"""{"n":{{i}}}"""), Guid.NewGuid().ToString("N"), ct);
            seqs.Add(command.Seq);
        });

        Assert.Equal(16, seqs.Count);
        Assert.Equal(16, seqs.Distinct().Count());       // BIGSERIAL hands out no duplicates.
        Assert.All(seqs, seq => Assert.True(seq > floor, "seq went backwards"));
    }

    // ---------- §9.5 claim / ack races ----------

    [Fact]
    public async Task Two_bridges_claiming_at_once_never_get_the_same_command()
    {
        await using var seed = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(seed);
        var mine = new HashSet<Guid>();
        for (var i = 0; i < 12; i++)
        {
            var command = await new Queue(seed).EnqueueAsync(
                user, ApiQueue.TaskUpdate, Json($$"""{"n":{{i}}}"""), Guid.NewGuid().ToString("N"));
            mine.Add(command.Id);
        }

        var claimed = new ConcurrentBag<Guid>();
        await Parallel.ForEachAsync(Enumerable.Range(0, 4), async (_, ct) =>
        {
            await using var db = TestDb.Connect();
            foreach (var command in await new Queue(db).ClaimAsync(50, ct))
            {
                claimed.Add(command.Id);
            }
        });

        var ours = claimed.Where(mine.Contains).ToList();
        Assert.Equal(12, ours.Count);                    // Nothing was left behind …
        Assert.Equal(12, ours.Distinct().Count());       // … and nothing went out twice.
    }

    /// <summary>
    /// A reconnecting bridge can deliver the same ack twice, and the two can land at once. The
    /// second must change nothing: whichever outcome was recorded first is the one that stands.
    /// </summary>
    [Fact]
    public async Task Two_acks_landing_together_apply_once()
    {
        await using var seed = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(seed);
        var command = await new Queue(seed).EnqueueAsync(
            user, ApiQueue.RobotEstop, Json(), Guid.NewGuid().ToString("N"));

        var winners = new ConcurrentBag<CommandState>();
        await Parallel.ForEachAsync(
            new[] { CommandState.Applied, CommandState.Failed },
            async (state, ct) =>
            {
                await using var db = TestDb.Connect();
                if (await new Queue(db).AckAsync(command.Id, state, Json($$"""{"by":"{{state}}"}"""), ct))
                {
                    winners.Add(state);
                }
            });

        var winner = Assert.Single(winners);

        await using var fresh = TestDb.Connect();
        var stored = await fresh.Commands.AsNoTracking().FirstAsync(c => c.Id == command.Id);
        Assert.Equal(winner, stored.State);
        Assert.Equal(winner.ToString(), stored.Result!.RootElement.GetProperty("by").GetString());
        Assert.NotNull(stored.AppliedAt);
    }

    // ---------- §3.1 reconnect reconciliation ----------

    /// <summary>
    /// The bridge drops mid-flight: some commands are delivered but unacked, some are still
    /// pending. On reconnect it must be handed only the pending ones, and the acks it buffered
    /// for the delivered ones must still land.
    /// </summary>
    [Fact]
    public async Task A_reconnecting_bridge_resumes_without_replaying_or_losing_a_command()
    {
        await using var db = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(db);
        var queue = new Queue(db);

        var inFlight = await queue.EnqueueAsync(user, ApiQueue.TaskCreate, Json(), Guid.NewGuid().ToString("N"));
        var claimed = await queue.ClaimAsync(100);
        Assert.Contains(claimed, c => c.Id == inFlight.Id);

        // The link dies here. A command queued while the lab is away simply waits.
        var queuedOffline = await queue.EnqueueAsync(
            user, ApiQueue.CampaignStop, Json(), Guid.NewGuid().ToString("N"));

        // Reconnect: the delivered command is not handed out again, the waiting one is.
        var second = await queue.ClaimAsync(100);
        Assert.DoesNotContain(second, c => c.Id == inFlight.Id);
        Assert.Contains(second, c => c.Id == queuedOffline.Id);

        // The ack the lab buffered while offline still applies, and its replay does not.
        Assert.True(await queue.AckAsync(inFlight.Id, CommandState.Applied, Json("""{"ok":true}"""), default));
        Assert.False(await queue.AckAsync(inFlight.Id, CommandState.Failed, null, default));

        await using var fresh = TestDb.Connect();
        var stored = await fresh.Commands.AsNoTracking().FirstAsync(c => c.Id == inFlight.Id);
        Assert.Equal(CommandState.Applied, stored.State);
        Assert.True(stored.Result!.RootElement.GetProperty("ok").GetBoolean());
    }

    [ApiFact]
    public async Task One_idempotency_key_over_the_wire_queues_one_command_however_often_it_arrives()
    {
        using var client = await OperatorClientAsync();
        var key = Guid.NewGuid().ToString("N");
        client.DefaultRequestHeaders.Add(NemlController.IdempotencyHeader, key);

        var receipts = new List<CommandAccepted>();
        for (var i = 0; i < 5; i++)
        {
            var response = await client.PostAsJsonAsync(
                "api/v1/brain/command", new BrainCommandRequest($"aynı komut {i}"));
            Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);
            receipts.Add((await response.Content.ReadFromJsonAsync<CommandAccepted>())!);
        }

        Assert.Single(receipts.Select(r => r.CommandId).Distinct());

        await using var db = TestDb.Connect();
        Assert.Equal(1, await db.Commands.CountAsync(c => c.IdempotencyKey == key));

        // The first text is the one the lab will see; the four repeats never overwrote it.
        var stored = await db.Commands.AsNoTracking().FirstAsync(c => c.IdempotencyKey == key);
        Assert.Equal("aynı komut 0", stored.Payload.RootElement.GetProperty("text").GetString());
    }

    // ---------- fixtures ----------

    private async Task<HttpClient> OperatorClientAsync()
    {
        await using var db = TestDb.Connect();
        var user = new User
        {
            Id = Guid.NewGuid(),
            Email = $"{Guid.NewGuid():N}@neml.test",
            PasswordHash = "x",
            Role = UserRole.Operator,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();

        var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(UserRole.Operator, user.Id));
        return client;
    }

    private static async Task<(string Id, RobotState State)> SeedRobotAsync()
    {
        await using var db = TestDb.Connect();
        var id = Guid.NewGuid().ToString("N")[..12];
        db.Genomes.Add(new Genome
        {
            Id = $"genome-{id}",
            Name = $"genome-{id}",
            Version = 1,
            Hash = id,
            Status = GenomeStatus.Draft,
            Body = Json(),
            Limits = Json(),
            CreatedAt = DateTimeOffset.UtcNow,
        });
        db.Robots.Add(new Robot
        {
            Id = $"R{id}",
            GenomeId = $"genome-{id}",
            Namespace = $"/r{id}",
            Hostname = $"{id}.lab",
            State = RobotState.Idle,
            CreatedAt = DateTimeOffset.UtcNow,
        });
        await db.SaveChangesAsync();
        return ($"R{id}", RobotState.Idle);
    }
}
