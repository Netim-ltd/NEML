// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;

namespace Neml.Api.Bridge;

/// <summary>Envelope types of NEML_SPEC.md 9.5. The envelope itself is Neml.Domain.Dtos.BridgeEnvelope.</summary>
public static class BridgeMessage
{
    // Lab to server.
    public const string Telemetry = "telemetry";
    public const string State = "state";
    public const string Event = "event";
    public const string CommandAck = "command_ack";
    public const string ApprovalRequest = "approval_request";
    public const string Log = "log";

    // Server to lab.
    public const string Command = "command";
    public const string ApprovalDecision = "approval_decision";
    public const string Ping = "ping";

    /// <summary>The six types a lab node is allowed to send.</summary>
    /// <summary>
    /// Name of the <c>event</c> that carries lab table rows for the app to read (see MirrorWriter).
    /// Not one of the ten spec 9.4 live events: it is applied to the database, never relayed.
    /// </summary>
    public const string MirrorEvent = "MirrorRows";

    public static readonly string[] FromLab = [Telemetry, State, Event, CommandAck, ApprovalRequest, Log];
}

/// <summary>Payload of an <c>event</c> envelope: one of the ten spec 9.4 events plus its payload.</summary>
public record LiveEventMessage(string Name, JsonElement Data);

/// <summary>Payload of a <c>command_ack</c> envelope — how the lab applied a queued command.</summary>
public record CommandAck(Guid CommandId, string State, JsonElement? Result);

/// <summary>Payload of an <c>approval_request</c> envelope (spec 9.5, lab to server).</summary>
public record ApprovalRequest(
    Guid ApprovalId,
    int Level,
    string SubjectKind,
    string SubjectId,
    DateTimeOffset ExpiresAt,
    JsonDocument Payload);

/// <summary>Payload of a <c>log</c> envelope. Level "audit" carries lab audit_log rows to mirror.</summary>
public record LogMessage(string Level, string Message, IReadOnlyList<AuditPayload>? Audit = null);

/// <summary>One lab audit_log row on the wire (params_hash stays in the lab).</summary>
public record AuditPayload(
    DateTimeOffset Ts,
    string Actor,
    string Action,
    string? Target,
    string? Outcome,
    int? DurationMs,
    Guid? ApprovalId);
