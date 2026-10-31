// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

namespace Neml.Api.Hubs;

// The ten server to client events of NEML_SPEC.md 9.4. Field names and order are the ones in
// that table; the enum-backed fields travel as the spec 7 text values, not as ordinals.

/// <summary><c>RobotState</c> — {robotId, state, batterySoc, lastSeen}.</summary>
public record RobotStatePayload(string RobotId, string State, decimal? BatterySoc, DateTimeOffset? LastSeen);

/// <summary><c>TelemetryTick</c> — {robotId, metrics, ts}. 1 Hz, throttled by LiveBroadcaster.</summary>
public record TelemetryTickPayload(string RobotId, IReadOnlyDictionary<string, double> Metrics, DateTimeOffset Ts);

/// <summary><c>TaskUpdated</c> — {taskId, state, progress, message}.</summary>
public record TaskUpdatedPayload(Guid TaskId, string State, double Progress, string? Message);

/// <summary><c>TaskRunEvent</c> — {taskId, attempt, env, outcome?, step}.</summary>
public record TaskRunEventPayload(Guid TaskId, int Attempt, string Env, string? Outcome, string Step);

/// <summary><c>CampaignProgress</c> — {campaignId, generation, best, mean, candidatesDone}.</summary>
public record CampaignProgressPayload(Guid CampaignId, int Generation, decimal? Best, decimal? Mean, int CandidatesDone);

/// <summary><c>ApprovalRequested</c> — {approvalId, level, subject, expiresAt, previewUrl}.</summary>
public record ApprovalRequestedPayload(Guid ApprovalId, int Level, string Subject, DateTimeOffset ExpiresAt, string? PreviewUrl);

/// <summary><c>ApprovalDecided</c> — {approvalId, decision, by}.</summary>
public record ApprovalDecidedPayload(Guid ApprovalId, string Decision, string By);

/// <summary><c>PrintProgress</c> — {jobId, pct, layer, etaMin, nozzleC, bedC}.</summary>
public record PrintProgressPayload(Guid JobId, double Pct, int Layer, double EtaMin, double NozzleC, double BedC);

/// <summary><c>BrainStatus</c> — {online, model, gpuOwner, budgetUsed}. Also the GET /brain/status body.</summary>
public record BrainStatusPayload(bool Online, string? Model, string? GpuOwner, decimal BudgetUsed);

/// <summary><c>Alert</c> — {severity, code, message}.</summary>
public record AlertPayload(string Severity, string Code, string Message);

/// <summary>
/// The client side of /hubs/live. The method name is the event name, and these ten are the
/// only methods a client will ever be called on — the bridge cannot invent an eleventh.
/// </summary>
public interface ILiveClient
{
    Task RobotState(RobotStatePayload payload);

    Task TelemetryTick(TelemetryTickPayload payload);

    Task TaskUpdated(TaskUpdatedPayload payload);

    Task TaskRunEvent(TaskRunEventPayload payload);

    Task CampaignProgress(CampaignProgressPayload payload);

    Task ApprovalRequested(ApprovalRequestedPayload payload);

    Task ApprovalDecided(ApprovalDecidedPayload payload);

    Task PrintProgress(PrintProgressPayload payload);

    Task BrainStatus(BrainStatusPayload payload);

    Task Alert(AlertPayload payload);
}

/// <summary>The four group names of spec 9.4.</summary>
public static class LiveGroups
{
    public const string Approvals = "approvals";
    public const string Global = "global";

    public static string Robot(string robotId) => $"robot:{robotId}";

    public static string Campaign(Guid campaignId) => $"campaign:{campaignId}";
}
