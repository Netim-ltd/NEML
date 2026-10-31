// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;

namespace Neml.Web;

// Wire shapes for §9.3 / §9.4, mirroring Neml.Api.Contracts. Kept local to the client on
// purpose: the web app talks JSON to a remote API, so a compile-time link to the server's
// DTOs would only couple the two release cycles.

public sealed record LoginRequest(string Email, string Password);

public sealed record TokenPair(string Access, string Refresh);

public sealed record RefreshRequest(string Refresh);

/// <summary>Envelope the §9.3 list endpoints use when they page.</summary>
public sealed record Paged<T>(IReadOnlyList<T> Items, int Page, int PageSize);

/// <summary>GET /brain/status.</summary>
public sealed record BrainStatus(bool Online, string? Model, string? GpuOwner, double? BudgetUsed, DateTimeOffset? LastSeen);

/// <summary>§7 robots.</summary>
public sealed record Robot(
    string Id,
    string Namespace,
    string State,
    decimal? BatterySoc,
    DateTimeOffset? LastSeen,
    decimal? RealityGap)
{
    public string? GenomeId { get; init; }
    public string? Hostname { get; init; }
    public DateTimeOffset? CalibratedAt { get; init; }
}

public sealed record TelemetryPoint(DateTimeOffset Ts, double Value);

/// <summary>§9.4 Alert.</summary>
public sealed record Alert(string Severity, string Code, string Message);

/// <summary>§9.4 RobotState.</summary>
public sealed record RobotStateEvent(string RobotId, string State, decimal? BatterySoc, DateTimeOffset? LastSeen);

/// <summary>§9.4 TaskUpdated.</summary>
public sealed record TaskUpdatedEvent(Guid TaskId, string State, double Progress, string? Message);

/// <summary>§9.4 ApprovalRequested.</summary>
public sealed record ApprovalRequestedEvent(Guid ApprovalId, int Level, string Subject, DateTimeOffset ExpiresAt, string? PreviewUrl);

/// <summary>
/// §7 tasks. Progress is not a column — it only ever arrives on the §9.4 TaskUpdated
/// event, so it stays 0 until one does.
/// </summary>
public sealed record TaskItem(
    Guid Id,
    string Title,
    string Kind,
    string Source,
    decimal Priority,
    string State,
    string? RobotId,
    JsonElement? Spec,
    JsonElement? Result,
    DateTimeOffset? Deadline,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt)
{
    public double Progress { get; init; }
}

/// <summary>§7 task_runs.</summary>
public sealed record TaskRun(
    long Id,
    int Attempt,
    string Env,
    long? Seed,
    DateTimeOffset StartedAt,
    DateTimeOffset? EndedAt,
    string? Outcome,
    string? RosbagPath);

/// <summary>§7 approvals. PreviewUrl is lifted out of payload by the API (§9.3).</summary>
public sealed record Approval(
    Guid Id,
    int Level,
    string SubjectKind,
    string SubjectId,
    JsonElement? Payload,
    DateTimeOffset RequestedAt,
    DateTimeOffset ExpiresAt,
    DateTimeOffset? DecidedAt,
    string? DecidedBy,
    string? Decision,
    string? Note,
    string? PreviewUrl);

/// <summary>Confirmation carries the §10.2 screen 10 level 4 phrase.</summary>
public sealed record ApprovalDecision(string? Note, string? Confirmation);

/// <summary>Receipt for anything that reaches the lab (§3.1 command queue).</summary>
public sealed record CommandAccepted(Guid CommandId, string State);

/// <summary>GET /brain/command/{id}: how a queued command ended (§3.1).</summary>
public sealed record CommandResult(Guid CommandId, string Kind, string State, JsonElement? Result);

/// <summary>GET /bot/manifest: what a bot may call.</summary>
public sealed record BotToolView(string Name, string Method, string Path, string Description);

public sealed record BotManifestView(string Login, string Refresh, BotToolView[] Tools, string[] Rules);

/// <summary>POST /bot/accounts: shown once.</summary>
public sealed record BotAccountView(string Email, string Password, string Role);

/// <summary>§7 campaigns.</summary>
public sealed record Campaign(
    Guid Id, string Name, string Objective, string State, DateTimeOffset StartedAt, DateTimeOffset? EndedAt,
    JsonElement? Weights = null, JsonElement? Budget = null);

/// <summary>Fitness series point per generation (§9.3).</summary>
public sealed record GenerationPoint(int Generation, double? Best, double? Mean, int CandidatesDone);

/// <summary>§7 candidates.</summary>
public sealed record Candidate(
    Guid Id, int Generation, string GenomeId, string Operator, string? Rationale, double? Fitness, string? Verdict,
    DateTimeOffset? CreatedAt = null, JsonElement? FitnessParts = null);

/// <summary>GET /genomes/tree node, children nested.</summary>
public sealed record GenomeNode(
    string Id, string Name, int Version, string Status, string? ParentId, double? FitnessScore,
    IReadOnlyList<GenomeNode> Children);

/// <summary>§7 skills.</summary>
public sealed record Skill(string Id, string SkillKey, int Version, string GenomeId, string Status, DateTimeOffset CreatedAt);

/// <summary>§7 print_jobs.</summary>
public sealed record PrintJob(
    Guid Id, string PrinterId, string ProfileId, double? EstTimeH, double? EstFilamentG, double? EstCostTry,
    string State, JsonElement? Qc, DateTimeOffset? StartedAt, DateTimeOffset? EndedAt);

/// <summary>GET /printers/{id}/status.</summary>
public sealed record PrinterStatus(string PrinterId, bool Online, string? State, Guid? JobId, double? Pct, double? NozzleC, double? BedC);

/// <summary>§7 audit_log.</summary>
public sealed record AuditEntry(
    long Id, DateTimeOffset Ts, string Actor, string Action, string? Target, string? Outcome, int? DurationMs)
{
    public bool IsToolCall => Actor.StartsWith("agent:", StringComparison.Ordinal);

    public bool IsError => Outcome is "error" or "failure";
}

/// <summary>Registered device of the signed-in user.</summary>
public sealed record Device(Guid Id, string Platform, DateTimeOffset? LastSeen);

/// <summary>POST /tasks body (§9.3).</summary>
public sealed record NewTask(string Title, string Kind, string Source, decimal Priority, string? RobotId, JsonElement Spec);

/// <summary>§12.5 quality form as the mobile screen already sends it.</summary>
public sealed record QcForm(
    double Dim1Mm, double Dim2Mm, double Dim3Mm,
    double Dim1NominalMm, double Dim2NominalMm, double Dim3NominalMm,
    double MassG, double MassNominalG, double WarpMm, bool HoleGaugeOk, bool LayerAdhesionOk)
{
    /// <summary>The snake_case keys the lab's print.qc handler reads.</summary>
    public Dictionary<string, object> ToWire() => new()
    {
        ["dim_1_mm"] = Dim1Mm, ["dim_2_mm"] = Dim2Mm, ["dim_3_mm"] = Dim3Mm,
        ["dim_1_nominal_mm"] = Dim1NominalMm, ["dim_2_nominal_mm"] = Dim2NominalMm, ["dim_3_nominal_mm"] = Dim3NominalMm,
        ["mass_g"] = MassG, ["mass_nominal_g"] = MassNominalG, ["warp_mm"] = WarpMm,
        ["hole_gauge_ok"] = HoleGaugeOk, ["layer_adhesion_ok"] = LayerAdhesionOk,
    };
}
