// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Collections.Concurrent;
using Neml.Api.Hubs;
using Neml.Domain.Dtos;

namespace Neml.Api.Services;

/// <summary>
/// Volatile view of the lab: bridge liveness, last brain status, last print progress, and the
/// spec 3.1 replay guards (monotonic seq per node, seen idempotency keys).
/// ponytail: in memory on purpose — none of it is worth a table and all of it is refreshed
/// within one bridge heartbeat (15 s). Ceiling: a second API instance would keep its own
/// copy, so move the seq and key guards into a table before running more than one.
/// </summary>
public sealed class LabState
{
    private const int MaxRememberedKeys = 10_000;

    private static readonly TimeSpan PrinterFreshness = TimeSpan.FromMinutes(1);

    private readonly ConcurrentDictionary<string, long> _lastSeq = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, byte> _seenKeys = new(StringComparer.Ordinal);
    private readonly ConcurrentQueue<string> _keyOrder = new();
    private readonly ConcurrentDictionary<Guid, (PrintProgressPayload Progress, DateTimeOffset At)> _prints = new();

    public bool BridgeConnected { get; private set; }

    public DateTimeOffset? LastSeen { get; private set; }

    public BrainStatusPayload? Brain { get; private set; }

    public void SetBridgeConnected(bool connected)
    {
        BridgeConnected = connected;
        if (connected)
        {
            LastSeen = DateTimeOffset.UtcNow;
        }
    }

    public void Touch() => LastSeen = DateTimeOffset.UtcNow;

    public void SetBrain(BrainStatusPayload status) => Brain = status;

    public void SetPrintProgress(PrintProgressPayload progress) =>
        _prints[progress.JobId] = (progress, DateTimeOffset.UtcNow);

    /// <summary>GET /brain/status — offline whenever the bridge is down, whatever the lab last said.</summary>
    public BrainStatusPayload Status() => new(
        BridgeConnected && Brain?.Online == true,
        Brain?.Model,
        Brain?.GpuOwner,
        Brain?.BudgetUsed ?? 0m);

    /// <summary>
    /// GET /printers/{id}/status — the last PrintProgress the lab pushed for that job. The API
    /// never calls PrusaLink itself; the printer is only ever reachable from the lab.
    /// </summary>
    public PrinterStatusResponse PrinterStatus(string printerId, Guid? jobId)
    {
        if (jobId is null || !_prints.TryGetValue(jobId.Value, out var entry))
        {
            return new PrinterStatusResponse(printerId, BridgeConnected, null, jobId, null, null, null);
        }

        var fresh = DateTimeOffset.UtcNow - entry.At < PrinterFreshness;
        var p = entry.Progress;
        return new PrinterStatusResponse(
            printerId, BridgeConnected && fresh, fresh ? "printing" : null, p.JobId, p.Pct, p.NozzleC, p.BedC);
    }

    /// <summary>
    /// Spec 3.1: seq must increase per node and a repeated idempotency key is silently
    /// dropped. False means the envelope must be ignored.
    /// </summary>
    public bool TryAccept(string node, long seq, string idempotencyKey)
    {
        if (seq <= 0 || string.IsNullOrEmpty(idempotencyKey))
        {
            return false;
        }

        var accepted = true;
        _lastSeq.AddOrUpdate(node, seq, (_, previous) =>
        {
            if (seq <= previous)
            {
                accepted = false;
                return previous;
            }

            return seq;
        });

        if (!accepted || !_seenKeys.TryAdd(idempotencyKey, 0))
        {
            return false;
        }

        _keyOrder.Enqueue(idempotencyKey);
        while (_keyOrder.Count > MaxRememberedKeys && _keyOrder.TryDequeue(out var oldest))
        {
            _seenKeys.TryRemove(oldest, out _);
        }

        return true;
    }
}
