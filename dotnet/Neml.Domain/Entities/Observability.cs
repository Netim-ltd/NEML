// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Neml.Domain.Enums;

namespace Neml.Domain.Entities;

/// <summary>
/// Table <c>telemetry</c> — keyless, PARTITION BY RANGE (ts). Section 7 declares no primary
/// key, so EF cannot insert it; use TelemetryRepository for both reads and writes.
/// </summary>
public class Telemetry
{
    public required DateTimeOffset Ts { get; set; }
    public required string RobotId { get; set; }
    public required string Metric { get; set; }
    public required double Value { get; set; }
    public JsonDocument? Tags { get; set; }
}

/// <summary>Table <c>approvals</c> — the section 5.2 human gate.</summary>
public class Approval
{
    public Guid Id { get; set; }
    public required int Level { get; set; }                 // 1..4
    public required string SubjectKind { get; set; }        // task | print | gerber | firmware
    public required string SubjectId { get; set; }
    public required JsonDocument Payload { get; set; }      // summary + preview path
    public DateTimeOffset RequestedAt { get; set; }
    public required DateTimeOffset ExpiresAt { get; set; }
    public DateTimeOffset? DecidedAt { get; set; }
    public string? DecidedBy { get; set; }
    public ApprovalDecision? Decision { get; set; }
    public string? Note { get; set; }
}

/// <summary>Table <c>safety_checks</c> — section 5.1 pre-session e-stop and watchdog record.</summary>
public class SafetyCheck
{
    public long Id { get; set; }
    public required string RobotId { get; set; }
    public required bool EstopOk { get; set; }
    public required bool WatchdogOk { get; set; }
    public required bool CurrentLimitOk { get; set; }
    public required string PerformedBy { get; set; }
    public DateTimeOffset PerformedAt { get; set; }
}

/// <summary>Table <c>audit_log</c>.</summary>
public class AuditLogEntry
{
    public long Id { get; set; }
    public DateTimeOffset Ts { get; set; }
    public required string Actor { get; set; }              // agent:mechanical | user:mg
    public required string Action { get; set; }
    public string? Target { get; set; }
    public string? ParamsHash { get; set; }
    public string? Outcome { get; set; }
    public int? DurationMs { get; set; }
    public Guid? ApprovalId { get; set; }
}

/// <summary>
/// Table <c>budget_usage</c> (ADR-011) — the section 14.4 daily counters, keyed by day and
/// resource so a new day is simply a new row and no reset job exists.
/// </summary>
public class BudgetUsage
{
    public required DateOnly Day { get; set; }
    public required string Resource { get; set; }           // config/budget.yaml names
    public decimal Used { get; set; }
}
