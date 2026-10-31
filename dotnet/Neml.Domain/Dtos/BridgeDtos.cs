// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using System.Text.Json.Serialization;
using Neml.Domain.Enums;

namespace Neml.Domain.Dtos;

// Section 9.5 bridge protocol. Only the lab node speaks these, authenticated with the
// long lived API key and the X-NEML-Node header.

/// <summary>
/// The section 9.5 message envelope. Every message carries seq and idempotency_key so a
/// replay after a reconnect is silently ignored (section 3.1).
/// </summary>
public record BridgeEnvelope(
    int V,
    long Seq,
    DateTimeOffset Ts,
    string Type,                                            // telemetry|event|command_ack|state|log
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    JsonDocument Payload);

/// <summary>One telemetry sample, matching the telemetry table columns.</summary>
public record TelemetrySample(DateTimeOffset Ts, string RobotId, string Metric, double Value, JsonDocument? Tags);

/// <summary>POST /bridge/telemetry/batch — the outbox drained after an offline stretch.</summary>
public record TelemetryBatchRequest(IReadOnlyList<TelemetrySample> Samples);

/// <summary>POST /bridge/events</summary>
public record BridgeEventsRequest(IReadOnlyList<BridgeEnvelope> Events);

/// <summary>Answer to both bridge POSTs: how much was stored and how much was a replay.</summary>
public record BridgeAckResponse(int Accepted, int Ignored);

/// <summary>A queued command handed down to the lab over the websocket.</summary>
public record CommandEnvelope(
    Guid Id,
    long Seq,
    string Kind,
    JsonDocument Payload,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

/// <summary>command_ack coming back up from the lab.</summary>
public record CommandAckRequest(Guid CommandId, CommandState State, JsonDocument? Result);
