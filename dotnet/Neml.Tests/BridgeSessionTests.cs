// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net.WebSockets;
using System.Text.Json;
using Microsoft.AspNetCore.TestHost;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Neml.Api.Auth;
using Neml.Api.Bridge;
using Neml.Api.Hubs;
using Neml.Api.Services;
using Neml.Domain.Dtos;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using ApiQueue = Neml.Api.Services.CommandQueue;
using Queue = Neml.Infrastructure.Repositories.CommandQueue;

namespace Neml.Tests;

/// <summary>
/// T-055 over the real socket: §9.5 from the moment the lab dials in. The server never opens
/// this connection, it only answers one, and everything it puts on the wire is a row the
/// command queue already held (§3.1, §19 risk 11).
/// </summary>
[Collection(NemlCloud.Name)]
public sealed class BridgeSessionTests : IDisposable
{
    private static readonly TimeSpan Patience = TimeSpan.FromSeconds(20);

    private readonly ApiFactory factory = new();
    private long seq = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

    public void Dispose() => factory.Dispose();

    [ApiFact]
    public async Task A_queued_command_goes_down_the_socket_and_its_ack_comes_back_up()
    {
        using var cts = new CancellationTokenSource(Patience);
        await using var db = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(db);
        var queued = await new Queue(db).EnqueueAsync(
            user, ApiQueue.RobotEstop, JsonDocument.Parse("""{"robotId":"R01"}"""),
            Guid.NewGuid().ToString("N"));

        using var socket = await ConnectAsync(cts.Token);

        // The write loop claims from the queue every 500 ms; nothing else can put a frame here.
        var envelope = await ReceiveUntilAsync(
            socket,
            e => e.Type == BridgeMessage.Command
                && e.Payload.RootElement.GetProperty("id").GetGuid() == queued.Id,
            cts.Token);

        Assert.Equal(1, envelope.V);
        Assert.Equal(ApiQueue.RobotEstop, envelope.Payload.RootElement.GetProperty("kind").GetString());
        Assert.Equal(queued.Seq, envelope.Payload.RootElement.GetProperty("seq").GetInt64());
        Assert.Equal(
            queued.IdempotencyKey,
            envelope.Payload.RootElement.GetProperty("idempotency_key").GetString());

        // Claiming marked it delivered in the same statement (§9.5).
        await using var check = TestDb.Connect();
        Assert.Equal(
            CommandState.Delivered,
            (await check.Commands.AsNoTracking().FirstAsync(c => c.Id == queued.Id, cts.Token)).State);

        await SendAsync(socket, BridgeMessage.CommandAck, new
        {
            commandId = queued.Id,
            state = "applied",
            result = new { ok = true },
        }, cts.Token);

        var applied = await EventuallyAsync(
            async () => (await CommandAsync(queued.Id)).State == CommandState.Applied, cts.Token);
        Assert.True(applied, "the command_ack never reached the queue");

        // §9.5 replay after a reconnect: the same ack again changes nothing.
        await SendAsync(socket, BridgeMessage.CommandAck, new
        {
            commandId = queued.Id,
            state = "failed",
            result = (object?)null,
        }, cts.Token);
        await Task.Delay(TimeSpan.FromMilliseconds(500), cts.Token);
        Assert.Equal(CommandState.Applied, (await CommandAsync(queued.Id)).State);
    }

    [ApiFact]
    public async Task The_lab_pushes_state_telemetry_approvals_and_logs_up_one_socket()
    {
        using var cts = new CancellationTokenSource(Patience);
        var robot = await SeedRobotAsync();
        var approvalId = Guid.NewGuid();

        using var socket = await ConnectAsync(cts.Token);

        await SendAsync(socket, BridgeMessage.State, new
        {
            robotId = robot,
            state = "fault",
            batterySoc = 0.42m,
            lastSeen = DateTimeOffset.UtcNow,
        }, cts.Token);

        await SendAsync(socket, BridgeMessage.Telemetry, new
        {
            samples = new[] { new { ts = DateTimeOffset.UtcNow, robotId = robot, metric = "battery_soc", value = 0.42, tags = (object?)null } },
        }, cts.Token);

        await SendAsync(socket, BridgeMessage.ApprovalRequest, new
        {
            approvalId,
            level = 3,
            subjectKind = "task",
            subjectId = robot,
            expiresAt = DateTimeOffset.UtcNow.AddHours(24),
            payload = new { summary = "serbest çalışma", preview_url = "/previews/x.png" },
        }, cts.Token);

        await SendAsync(socket, BridgeMessage.Event, new
        {
            name = nameof(ILiveClient.TaskUpdated),
            data = new { taskId = Guid.NewGuid(), state = "running", progress = 0.5, message = (string?)null },
        }, cts.Token);

        await SendAsync(socket, BridgeMessage.Log, new { level = "warning", message = "gpu lock devraldı" }, cts.Token);

        // The mirror (§9.5 state) and the approvals table are what the mobile app reads.
        var mirrored = await EventuallyAsync(
            async () =>
            {
                await using var db = TestDb.Connect();
                var row = await db.Robots.AsNoTracking().FirstAsync(r => r.Id == robot, cts.Token);
                return row.State == RobotState.Fault && row.BatterySoc == 0.42m;
            },
            cts.Token);
        Assert.True(mirrored, "the state envelope never reached the robots mirror");

        var stored = await EventuallyAsync(
            async () =>
            {
                await using var db = TestDb.Connect();
                return await db.Approvals.AsNoTracking().AnyAsync(a => a.Id == approvalId, cts.Token);
            },
            cts.Token);
        Assert.True(stored, "the approval_request envelope never reached the approvals table");

        await using var final = TestDb.Connect();
        var approval = await final.Approvals.AsNoTracking().FirstAsync(a => a.Id == approvalId, cts.Token);
        Assert.Equal(3, approval.Level);
        Assert.Equal("/previews/x.png", BridgeSession.PreviewUrl(approval.Payload));

        // The same approval_request arriving again is not a second row (§3.1).
        await SendAsync(socket, BridgeMessage.ApprovalRequest, new
        {
            approvalId,
            level = 3,
            subjectKind = "task",
            subjectId = robot,
            expiresAt = DateTimeOffset.UtcNow.AddHours(24),
            payload = new { summary = "tekrar" },
        }, cts.Token);
        await Task.Delay(TimeSpan.FromMilliseconds(500), cts.Token);

        await using var recount = TestDb.Connect();
        Assert.Equal(1, await recount.Approvals.CountAsync(a => a.Id == approvalId, cts.Token));
    }

    [ApiFact]
    public async Task Rubbish_on_the_wire_is_dropped_without_killing_the_link()
    {
        using var cts = new CancellationTokenSource(Patience);
        await using var seed = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(seed);

        using var socket = await ConnectAsync(cts.Token);

        await RawAsync(socket, "{ this is not json", cts.Token);
        await RawAsync(socket, "null", cts.Token);
        await SendAsync(socket, "telemetry", new { samples = "not a list" }, cts.Token);
        await SendAsync(socket, "invented_type", new { }, cts.Token);

        // Same seq twice, and a key that was already used: both are §3.1 replays.
        var replayedSeq = ++seq;
        var key = Guid.NewGuid().ToString("N");
        await RawAsync(socket, Envelope(replayedSeq, BridgeMessage.Log, new { level = "info", message = "bir" }, key), cts.Token);
        await RawAsync(socket, Envelope(replayedSeq, BridgeMessage.Log, new { level = "info", message = "iki" }, key), cts.Token);

        // Still alive: a command queued now still reaches the lab over this same socket.
        var queued = await new Queue(seed).EnqueueAsync(
            user, ApiQueue.BrainCommand, JsonDocument.Parse("""{"text":"hâlâ buradayım"}"""),
            Guid.NewGuid().ToString("N"));

        var envelope = await ReceiveUntilAsync(
            socket,
            e => e.Type == BridgeMessage.Command
                && e.Payload.RootElement.GetProperty("id").GetGuid() == queued.Id,
            cts.Token);

        Assert.Equal(BridgeMessage.Command, envelope.Type);
    }

    [ApiFact]
    public async Task When_the_lab_hangs_up_the_brain_is_published_offline()
    {
        using var cts = new CancellationTokenSource(Patience);
        var lab = factory.Services.GetRequiredService<LabState>();
        lab.SetBrain(new BrainStatusPayload(true, "qwen2.5-1.5b", "llm", 0.1m));

        using (var socket = await ConnectAsync(cts.Token))
        {
            Assert.True(
                await EventuallyAsync(() => Task.FromResult(lab.BridgeConnected), cts.Token),
                "the session never marked the bridge up");
            Assert.True(lab.Status().Online);

            await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "bye", cts.Token);
        }

        Assert.True(
            await EventuallyAsync(() => Task.FromResult(!lab.BridgeConnected), cts.Token),
            "the session never marked the bridge down");

        // §9.5: a dead link is BrainStatus{online:false}, whatever the lab last claimed.
        Assert.False(lab.Status().Online);
        Assert.Equal("qwen2.5-1.5b", lab.Status().Model);
    }

    // ---------- plumbing ----------

    private async Task<WebSocket> ConnectAsync(CancellationToken ct)
    {
        var client = factory.Server.CreateWebSocketClient();
        client.ConfigureRequest = request =>
        {
            request.Headers[BridgeAuthenticationHandler.KeyHeader] = ApiFactory.BridgeKey;
            request.Headers[BridgeAuthenticationHandler.NodeHeader] = ApiFactory.BridgeNode;
        };

        return await client.ConnectAsync(new Uri(factory.Server.BaseAddress, "bridge/ws"), ct);
    }

    private Task SendAsync(WebSocket socket, string type, object payload, CancellationToken ct) =>
        RawAsync(socket, Envelope(++seq, type, payload, Guid.NewGuid().ToString("N")), ct);

    private static string Envelope(long seq, string type, object payload, string key) =>
        JsonSerializer.Serialize(
            new
            {
                v = 1,
                seq,
                ts = DateTimeOffset.UtcNow,
                type,
                idempotency_key = key,
                payload,
            },
            JsonSerializerOptions.Web);

    private static Task RawAsync(WebSocket socket, string text, CancellationToken ct) =>
        socket.SendAsync(
            System.Text.Encoding.UTF8.GetBytes(text), WebSocketMessageType.Text, endOfMessage: true, ct);

    private static async Task<BridgeEnvelope> ReceiveUntilAsync(
        WebSocket socket, Func<BridgeEnvelope, bool> wanted, CancellationToken ct)
    {
        var buffer = new byte[64 * 1024];
        while (!ct.IsCancellationRequested)
        {
            using var message = new MemoryStream();
            WebSocketReceiveResult result;
            do
            {
                result = await socket.ReceiveAsync(buffer, ct);
                Assert.NotEqual(WebSocketMessageType.Close, result.MessageType);
                message.Write(buffer, 0, result.Count);
            }
            while (!result.EndOfMessage);

            var envelope = JsonSerializer.Deserialize<BridgeEnvelope>(message.ToArray(), JsonSerializerOptions.Web);
            if (envelope is not null && wanted(envelope))
            {
                return envelope;
            }
        }

        throw new TimeoutException("the frame never arrived");
    }

    /// <summary>Polls a condition the bridge satisfies asynchronously, rather than sleeping blind.</summary>
    private static async Task<bool> EventuallyAsync(Func<Task<bool>> condition, CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            if (await condition())
            {
                return true;
            }

            await Task.Delay(TimeSpan.FromMilliseconds(100), CancellationToken.None);
        }

        return false;
    }

    private static async Task<Command> CommandAsync(Guid id)
    {
        await using var db = TestDb.Connect();
        return await db.Commands.AsNoTracking().FirstAsync(c => c.Id == id);
    }

    private static async Task<string> SeedRobotAsync()
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
            Body = JsonDocument.Parse("{}"),
            Limits = JsonDocument.Parse("{}"),
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
        return $"R{id}";
    }
}
