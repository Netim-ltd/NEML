// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using System.Text.Json.Serialization;
using Neml.Domain.Enums;

namespace Neml.Domain.Dtos;

// Request and response shapes for every NEML_SPEC.md section 9.3 endpoint.
// ponytail: wire names come from the ASP.NET Core / SignalR default camelCase property
// policy, so PascalCase members serialize as robotId, batterySoc, ... If the API ever
// changes JsonSerializerOptions.PropertyNamingPolicy, add [JsonPropertyName] here instead.

// ---------- Auth ----------

/// <summary>POST /auth/login</summary>
public record LoginRequest(string Email, string Password);

/// <summary>POST /auth/login and /auth/refresh both return this.</summary>
public record TokenResponse(string Access, string Refresh);

/// <summary>POST /auth/refresh</summary>
public record RefreshRequest(string Refresh);

/// <summary>POST /auth/logout</summary>
public record LogoutRequest(string Refresh);

/// <summary>POST /auth/devices</summary>
public record RegisterDeviceRequest(DevicePlatform Platform, string? PushToken);

public record DeviceResponse(Guid Id, DevicePlatform Platform, string? PushToken, DateTimeOffset? LastSeen);

// ---------- Paging ----------

public record PagedResponse<T>(IReadOnlyList<T> Items, int Page, int PageSize, int Total);

// ---------- Robots ----------

/// <summary>GET /robots and GET /robots/{id}</summary>
public record RobotResponse(
    string Id,
    string GenomeId,
    string Namespace,
    string Hostname,
    RobotState State,
    decimal? BatterySoc,
    DateTimeOffset? LastSeen,
    DateTimeOffset? CalibratedAt,
    decimal? RealityGap);

/// <summary>
/// GET /robots/{id}/telemetry?metric=&amp;from=&amp;to=&amp;agg=.
/// Agg is one of raw, avg, min, max, sum, count; anything else is rejected by the repository.
/// </summary>
public record TelemetryQuery(string Metric, DateTimeOffset From, DateTimeOffset To, string Agg = "avg");

public record TelemetryPointResponse(DateTimeOffset Ts, double Value);

/// <summary>
/// Everything that reaches hardware goes through the command queue, never straight to the lab:
/// POST /robots/{id}/estop and POST /brain/command both answer with this.
/// </summary>
public record CommandAcceptedResponse(
    [property: JsonPropertyName("command_id")] Guid CommandId,
    CommandState State,
    long Seq);

// ---------- Tasks ----------

/// <summary>GET /tasks?state=&amp;kind=&amp;robot=&amp;page=</summary>
public record TaskQuery(
    TaskState? State, TaskKind? Kind, string? Robot, int Page = 1, int PageSize = 50, string? SourcePrefix = null);

public record TaskResponse(
    Guid Id,
    string Title,
    TaskKind Kind,
    string Source,
    decimal Priority,
    TaskState State,
    string? RobotId,
    JsonDocument Spec,
    JsonDocument? Result,
    DateTimeOffset? Deadline,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);

/// <summary>POST /tasks</summary>
public record CreateTaskRequest(
    string Title,
    TaskKind Kind,
    string Source,
    decimal Priority,
    string? RobotId,
    JsonDocument Spec,
    DateTimeOffset? Deadline);

/// <summary>PATCH /tasks/{id} — every field optional, only what is present is applied.</summary>
public record UpdateTaskRequest(
    string? Title,
    decimal? Priority,
    TaskState? State,
    string? RobotId,
    DateTimeOffset? Deadline);

/// <summary>GET /tasks/{id}/runs</summary>
public record TaskRunResponse(
    long Id,
    Guid TaskId,
    int Attempt,
    TaskRunEnv Env,
    long? Seed,
    DateTimeOffset StartedAt,
    DateTimeOffset? EndedAt,
    TaskOutcome? Outcome,
    JsonDocument? Metrics,
    string? RosbagPath);

// ---------- Brain ----------

/// <summary>POST /brain/command</summary>
public record BrainCommandRequest(string Text);

/// <summary>GET /brain/command/{id}</summary>
public record BrainCommandResponse(
    [property: JsonPropertyName("command_id")] Guid CommandId,
    string Kind,
    CommandState State,
    JsonDocument? Result,
    DateTimeOffset CreatedAt,
    DateTimeOffset? AppliedAt);

/// <summary>GET /brain/status, and the payload of the section 9.4 BrainStatus event.</summary>
public record BrainStatusResponse(bool Online, string? Model, string? GpuOwner, decimal BudgetUsed);

// ---------- Campaigns, skills, genomes ----------

public record CampaignResponse(
    Guid Id,
    string Name,
    string Objective,
    JsonDocument Weights,
    JsonDocument Budget,
    CampaignState State,
    DateTimeOffset StartedAt,
    DateTimeOffset? EndedAt);

/// <summary>POST /campaigns — weights and budget are fixed up front (section 14.4).</summary>
public record CreateCampaignRequest(string Name, string Objective, JsonDocument Weights, JsonDocument Budget);

/// <summary>GET /campaigns/{id}/generations — the fitness series.</summary>
public record GenerationPointResponse(int Generation, decimal? Best, decimal? Mean, int CandidatesDone);

/// <summary>GET /campaigns/{id}/candidates</summary>
public record CandidateResponse(
    Guid Id,
    int Generation,
    string GenomeId,
    CandidateOperator Operator,
    string? Rationale,
    decimal? Fitness,
    CandidateVerdict? Verdict,
    DateTimeOffset CreatedAt,
    JsonDocument? FitnessParts = null);

/// <summary>GET /skills and GET /skills/{key}/versions</summary>
public record SkillResponse(
    string Id,
    string SkillKey,
    int Version,
    string GenomeId,
    string BtPath,
    JsonDocument Parameters,
    JsonDocument Preconditions,
    SkillStatus Status,
    string? Supersedes,
    DateTimeOffset CreatedAt);

/// <summary>GET /genomes/tree — one lineage node, children nested for mobile rendering.</summary>
public record GenomeNodeResponse(
    string Id,
    string Name,
    int Version,
    GenomeStatus Status,
    string? ParentId,
    decimal? FitnessScore,
    IReadOnlyList<GenomeNodeResponse> Children);

// ---------- Approvals ----------

/// <summary>GET /approvals and GET /approvals/{id}</summary>
public record ApprovalResponse(
    Guid Id,
    int Level,
    string SubjectKind,
    string SubjectId,
    JsonDocument Payload,
    DateTimeOffset RequestedAt,
    DateTimeOffset ExpiresAt,
    DateTimeOffset? DecidedAt,
    string? DecidedBy,
    ApprovalDecision? Decision,
    string? Note);

/// <summary>POST /approvals/{id}/approve and /reject</summary>
public record ApprovalDecisionRequest(string? Note);

// ---------- Manufacturing ----------

/// <summary>GET /print-jobs</summary>
public record PrintJobResponse(
    Guid Id,
    Guid ArtifactId,
    string PrinterId,
    string ProfileId,
    Guid ApprovalId,
    decimal? EstTimeH,
    decimal? EstFilamentG,
    decimal? EstCostTry,
    PrintJobState State,
    JsonDocument? Qc,
    DateTimeOffset? StartedAt,
    DateTimeOffset? EndedAt);

/// <summary>
/// GET /printers/{id}/status. Section 9.3 names the endpoint but not the body; these are the
/// fields the PrusaLink status call of section 6.4 actually returns.
/// </summary>
public record PrinterStatusResponse(
    string PrinterId,
    bool Online,
    string? State,
    Guid? JobId,
    double? Pct,
    double? NozzleC,
    double? BedC);
