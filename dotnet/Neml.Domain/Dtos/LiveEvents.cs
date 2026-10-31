// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Neml.Domain.Enums;

namespace Neml.Domain.Dtos;

// Server to client payloads of the section 9.4 SignalR hub /hubs/live.
// The record name is irrelevant on the wire, the hub method name is the event name.
// Field names are exactly the ones in the section 9.4 table.

/// <summary>Event <c>RobotState</c>. Group robot:{id}.</summary>
public record RobotStateEvent(string RobotId, RobotState State, decimal? BatterySoc, DateTimeOffset? LastSeen);

/// <summary>Event <c>TelemetryTick</c> — 1 Hz, throttled. Group robot:{id}.</summary>
public record TelemetryTickEvent(string RobotId, IReadOnlyDictionary<string, double> Metrics, DateTimeOffset Ts);

/// <summary>Event <c>TaskUpdated</c>. Group global.</summary>
public record TaskUpdatedEvent(Guid TaskId, TaskState State, double Progress, string? Message);

/// <summary>Event <c>TaskRunEvent</c>.</summary>
public record TaskRunEvent(Guid TaskId, int Attempt, TaskRunEnv Env, TaskOutcome? Outcome, string Step);

/// <summary>Event <c>CampaignProgress</c>. Group campaign:{id}.</summary>
public record CampaignProgressEvent(Guid CampaignId, int Generation, decimal? Best, decimal? Mean, int CandidatesDone);

/// <summary>Event <c>ApprovalRequested</c>. Group approvals.</summary>
public record ApprovalRequestedEvent(Guid ApprovalId, int Level, string Subject, DateTimeOffset ExpiresAt, string? PreviewUrl);

/// <summary>Event <c>ApprovalDecided</c>. Group approvals.</summary>
public record ApprovalDecidedEvent(Guid ApprovalId, ApprovalDecision Decision, string By);

/// <summary>Event <c>PrintProgress</c>.</summary>
public record PrintProgressEvent(Guid JobId, double Pct, int Layer, double EtaMin, double NozzleC, double BedC);

/// <summary>Event <c>Alert</c>. Group global.</summary>
public record AlertEvent(string Severity, string Code, string Message);

// Event BrainStatus reuses BrainStatusResponse: the section 9.3 body and the section 9.4
// payload are field for field identical.
