// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Buffers;
using System.Data.Common;
using System.Net.WebSockets;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Neml.Api.Hubs;
using Neml.Api.Services;
using Neml.Domain.Dtos;
using Neml.Domain.Entities;
using Neml.Infrastructure.Repositories;
using CommandQueue = Neml.Api.Services.CommandQueue;

namespace Neml.Api.Bridge;

/// <summary>
/// Server side of the lab bridge (spec 3.1, 9.5). The server never dials the lab: this class
/// only ever runs on a socket the lab opened itself. Everything it sends down is a row the
/// command queue already held, so the API still cannot reach a robot on its own.
/// </summary>
public sealed class BridgeSession(
    IServiceScopeFactory scopes,
    LiveBroadcaster live,
    LabState lab,
    ILogger<BridgeSession> log)
{
    private static readonly TimeSpan PingInterval = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan InboundTimeout = TimeSpan.FromSeconds(45);
    private static readonly TimeSpan ClaimInterval = TimeSpan.FromMilliseconds(500);

    private const int MaxMessageBytes = 4 * 1024 * 1024;
    private const int ClaimBatch = 32;

    private long _outboundSeq;
    private DateTimeOffset _lastInbound = DateTimeOffset.UtcNow;

    public async Task RunAsync(WebSocket socket, string node, CancellationToken ct)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct);
        lab.SetBridgeConnected(true);
        log.LogInformation("Bridge node {Node} connected.", node);

        using (var scope = scopes.CreateScope())
        {
            var requeued = await scope.ServiceProvider.GetRequiredService<CommandQueue>().RequeueLostAsync(ct);
            if (requeued > 0)
            {
                log.LogInformation("Requeued {Count} commands the lab lost in a restart.", requeued);
            }
        }

        try
        {
            await Task.WhenAny(ReadLoopAsync(socket, node, linked.Token), WriteLoopAsync(socket, linked.Token));
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            log.LogWarning(ex, "Bridge node {Node} failed.", node);
        }
        finally
        {
            await linked.CancelAsync();
            lab.SetBridgeConnected(false);

            // Spec 9.5: a dead bridge is published as BrainStatus{online:false}.
            await live.BrainStatusAsync(
                new BrainStatusPayload(false, lab.Brain?.Model, null, lab.Brain?.BudgetUsed ?? 0m),
                CancellationToken.None);
            log.LogInformation("Bridge node {Node} disconnected.", node);

            // CloseReceived belongs here too: RFC 6455 wants a close frame back, and the lab
            // waits for one before it starts the spec 3.1 backoff. Skipping the reply left a
            // politely closing lab blocked until its own socket timed out.
            if (socket.State is WebSocketState.Open or WebSocketState.CloseReceived)
            {
                await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "closing", CancellationToken.None);
            }
        }
    }

    /// <summary>
    /// Applies one envelope that arrived over the socket or through POST /bridge/events.
    /// False means spec 3.1 says to ignore it: a stale seq or a replayed idempotency key.
    /// </summary>
    public async Task<bool> AcceptAsync(BridgeEnvelope envelope, string node, CancellationToken ct)
    {
        if (!lab.TryAccept(node, envelope.Seq, envelope.IdempotencyKey))
        {
            return false;
        }

        try
        {
            await DispatchAsync(envelope, ct);
            return true;
        }
        catch (JsonException ex)
        {
            log.LogWarning(ex, "Bridge node {Node} sent a malformed {Type} payload; dropped.", node, envelope.Type);
            return false;
        }
    }

    /// <summary>The preview PNG path lives inside approvals.payload (spec 7, 9.3).</summary>
    public static string? PreviewUrl(JsonDocument payload) =>
        payload.RootElement.ValueKind == JsonValueKind.Object
        && payload.RootElement.TryGetProperty("preview_url", out var url)
            ? url.GetString()
            : null;

    private static Task SendAsync(WebSocket socket, BridgeEnvelope envelope, CancellationToken ct) =>
        socket.SendAsync(
            JsonSerializer.SerializeToUtf8Bytes(envelope, JsonSerializerOptions.Web),
            WebSocketMessageType.Text,
            endOfMessage: true,
            ct);

    private static T Read<T>(JsonDocument payload) =>
        payload.Deserialize<T>(JsonSerializerOptions.Web) ?? throw new JsonException($"Empty {typeof(T).Name}.");

    private async Task ReadLoopAsync(WebSocket socket, string node, CancellationToken ct)
    {
        var buffer = ArrayPool<byte>.Shared.Rent(32 * 1024);
        try
        {
            while (!ct.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
                using var message = new MemoryStream();
                WebSocketReceiveResult result;
                do
                {
                    result = await socket.ReceiveAsync(buffer, ct);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        return;
                    }

                    message.Write(buffer, 0, result.Count);
                    if (message.Length > MaxMessageBytes)
                    {
                        log.LogWarning("Bridge node {Node} sent an oversized message; closing.", node);
                        return;
                    }
                }
                while (!result.EndOfMessage);

                _lastInbound = DateTimeOffset.UtcNow;
                lab.Touch();

                BridgeEnvelope? envelope;
                try
                {
                    envelope = JsonSerializer.Deserialize<BridgeEnvelope>(message.ToArray(), JsonSerializerOptions.Web);
                }
                catch (JsonException ex)
                {
                    log.LogWarning(ex, "Bridge node {Node} sent malformed JSON; dropped.", node);
                    continue;
                }

                if (envelope is not null)
                {
                    await AcceptAsync(envelope, node, ct);
                }
            }
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private async Task WriteLoopAsync(WebSocket socket, CancellationToken ct)
    {
        var lastPing = DateTimeOffset.UtcNow;
        using var timer = new PeriodicTimer(ClaimInterval);

        while (await timer.WaitForNextTickAsync(ct))
        {
            // Spec 9.5: 45 s without a word from the lab means the link is gone.
            if (DateTimeOffset.UtcNow - _lastInbound > InboundTimeout)
            {
                log.LogWarning("Bridge silent for {Seconds} s; closing.", InboundTimeout.TotalSeconds);
                return;
            }

            using (var scope = scopes.CreateScope())
            {
                var queue = scope.ServiceProvider.GetRequiredService<CommandQueue>();
                foreach (var command in await queue.ClaimAsync(ClaimBatch, ct))
                {
                    await SendAsync(socket, Envelope(command), ct);
                }
            }

            if (DateTimeOffset.UtcNow - lastPing >= PingInterval)
            {
                lastPing = DateTimeOffset.UtcNow;
                await SendAsync(socket, NewEnvelope(BridgeMessage.Ping, JsonDocument.Parse("{}")), ct);
            }
        }
    }

    /// <summary>approval_decision travels as its own spec 9.5 type; every other kind is a command.</summary>
    private BridgeEnvelope Envelope(Command command) =>
        command.Kind == CommandQueue.ApprovalDecision
            ? NewEnvelope(BridgeMessage.ApprovalDecision, command.Payload)
            : NewEnvelope(BridgeMessage.Command, JsonSerializer.SerializeToDocument(
                new CommandEnvelope(command.Id, command.Seq, command.Kind, command.Payload, command.IdempotencyKey),
                JsonSerializerOptions.Web));

    private BridgeEnvelope NewEnvelope(string type, JsonDocument payload) => new(
        1,
        Interlocked.Increment(ref _outboundSeq),
        DateTimeOffset.UtcNow,
        type,
        Guid.NewGuid().ToString("N"),
        payload);

    private async Task DispatchAsync(BridgeEnvelope envelope, CancellationToken ct)
    {
        using var scope = scopes.CreateScope();
        var services = scope.ServiceProvider;

        switch (envelope.Type)
        {
            case BridgeMessage.Telemetry:
                var batch = Read<TelemetryBatchRequest>(envelope.Payload);
                await services.GetRequiredService<TelemetryRepository>().InsertBatchAsync(batch.Samples, ct);
                break;

            case BridgeMessage.State:
                var state = Read<RobotStatePayload>(envelope.Payload);
                await services.GetRequiredService<MirrorWriter>().UpdateRobotStateAsync(state, ct);
                await live.RobotStateAsync(state, ct);
                break;

            case BridgeMessage.Event:
                var relayed = Read<LiveEventMessage>(envelope.Payload);
                if (relayed.Name == BridgeMessage.MirrorEvent)
                {
                    try
                    {
                        await services.GetRequiredService<MirrorWriter>().UpsertAsync(relayed.Data, ct);
                    }
                    catch (Exception ex) when (ex is DbException or DbUpdateException)
                    {
                        // A row that lost a race with its parent is re-sent by the lab's timer.
                        log.LogWarning(ex, "Mirror batch was not applied; the lab will send it again.");
                    }

                    break;
                }

                await live.DispatchAsync(relayed.Name, relayed.Data, ct);
                break;

            case BridgeMessage.CommandAck:
                await AckAsync(services, Read<CommandAck>(envelope.Payload), ct);
                break;

            case BridgeMessage.ApprovalRequest:
                await ApprovalRequestedAsync(services, Read<ApprovalRequest>(envelope.Payload), ct);
                break;

            case BridgeMessage.Log:
                var entry = Read<LogMessage>(envelope.Payload);
                log.LogInformation("lab[{Level}] {Message}", entry.Level, entry.Message);
                if (entry.Audit is { Count: > 0 })
                {
                    await services.GetRequiredService<MirrorWriter>().InsertAuditAsync(entry.Audit, ct);
                }

                break;

            default:
                log.LogWarning("Unknown bridge envelope type {Type}; dropped.", envelope.Type);
                break;
        }
    }

    private async Task AckAsync(IServiceProvider services, CommandAck ack, CancellationToken ct)
    {
        await services.GetRequiredService<CommandQueue>()
            .AckAsync(ack.CommandId, ack.State, ack.Result?.GetRawText(), ct);

        // Spec 9.4 defines no dedicated ack event, so the finished round trip is announced on
        // the Alert channel rather than by inventing an eleventh event.
        await live.AlertAsync(
            new AlertPayload(ack.State == "applied" ? "info" : "error", $"command.{ack.State}", ack.CommandId.ToString()),
            ct);
    }

    private async Task ApprovalRequestedAsync(IServiceProvider services, ApprovalRequest request, CancellationToken ct)
    {
        await services.GetRequiredService<MirrorWriter>().InsertApprovalRequestAsync(request, ct);

        await live.ApprovalRequestedAsync(
            new ApprovalRequestedPayload(
                request.ApprovalId,
                request.Level,
                $"{request.SubjectKind}:{request.SubjectId}",
                request.ExpiresAt,
                PreviewUrl(request.Payload)),
            ct);
    }
}
