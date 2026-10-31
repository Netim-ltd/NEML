// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json.Serialization;

namespace Neml.Domain.Enums;

// Every enum here mirrors one CHECK constraint from NEML_SPEC.md section 7.
// The [JsonStringEnumMemberName] value IS the database string: it is the single
// source of truth for both the wire format and the EF value converter
// (Neml.Infrastructure.Persistence.PgEnum). Never rely on the integer ordinal.

/// <summary>genomes.status</summary>
[JsonConverter(typeof(JsonStringEnumConverter<GenomeStatus>))]
public enum GenomeStatus
{
    [JsonStringEnumMemberName("draft")] Draft,
    [JsonStringEnumMemberName("testing")] Testing,
    [JsonStringEnumMemberName("active")] Active,
    [JsonStringEnumMemberName("deprecated")] Deprecated,
}

/// <summary>robots.state</summary>
[JsonConverter(typeof(JsonStringEnumConverter<RobotState>))]
public enum RobotState
{
    [JsonStringEnumMemberName("offline")] Offline,
    [JsonStringEnumMemberName("idle")] Idle,
    [JsonStringEnumMemberName("charging")] Charging,
    [JsonStringEnumMemberName("running")] Running,
    [JsonStringEnumMemberName("fault")] Fault,
    [JsonStringEnumMemberName("estop")] Estop,
    [JsonStringEnumMemberName("maintenance")] Maintenance,
}

/// <summary>skills.status</summary>
[JsonConverter(typeof(JsonStringEnumConverter<SkillStatus>))]
public enum SkillStatus
{
    [JsonStringEnumMemberName("candidate")] Candidate,
    [JsonStringEnumMemberName("validated")] Validated,
    [JsonStringEnumMemberName("retired")] Retired,
}

/// <summary>skill_validations.env and skill_runs.env (ADR-011) — the same two values.</summary>
[JsonConverter(typeof(JsonStringEnumConverter<ValidationEnv>))]
public enum ValidationEnv
{
    [JsonStringEnumMemberName("sim")] Sim,
    [JsonStringEnumMemberName("real")] Real,
}

/// <summary>tasks.kind</summary>
[JsonConverter(typeof(JsonStringEnumConverter<TaskKind>))]
public enum TaskKind
{
    [JsonStringEnumMemberName("human")] Human,
    [JsonStringEnumMemberName("repair")] Repair,
    [JsonStringEnumMemberName("exploration")] Exploration,
    [JsonStringEnumMemberName("evolution")] Evolution,
    [JsonStringEnumMemberName("maintenance")] Maintenance,
    [JsonStringEnumMemberName("calibration")] Calibration,
}

/// <summary>tasks.state</summary>
[JsonConverter(typeof(JsonStringEnumConverter<TaskState>))]
public enum TaskState
{
    [JsonStringEnumMemberName("queued")] Queued,
    [JsonStringEnumMemberName("planning")] Planning,
    [JsonStringEnumMemberName("awaiting_approval")] AwaitingApproval,
    [JsonStringEnumMemberName("running")] Running,
    [JsonStringEnumMemberName("paused")] Paused,
    [JsonStringEnumMemberName("succeeded")] Succeeded,
    [JsonStringEnumMemberName("failed")] Failed,
    [JsonStringEnumMemberName("cancelled")] Cancelled,
}

/// <summary>task_runs.env — the section 5.2 deployment gates.</summary>
[JsonConverter(typeof(JsonStringEnumConverter<TaskRunEnv>))]
public enum TaskRunEnv
{
    [JsonStringEnumMemberName("sim")] Sim,
    [JsonStringEnumMemberName("bench")] Bench,
    [JsonStringEnumMemberName("tethered")] Tethered,
    [JsonStringEnumMemberName("free")] Free,
}

/// <summary>task_runs.outcome</summary>
[JsonConverter(typeof(JsonStringEnumConverter<TaskOutcome>))]
public enum TaskOutcome
{
    [JsonStringEnumMemberName("success")] Success,
    [JsonStringEnumMemberName("failure")] Failure,
    [JsonStringEnumMemberName("aborted")] Aborted,
    [JsonStringEnumMemberName("timeout")] Timeout,
}

/// <summary>campaigns.state</summary>
[JsonConverter(typeof(JsonStringEnumConverter<CampaignState>))]
public enum CampaignState
{
    [JsonStringEnumMemberName("active")] Active,
    [JsonStringEnumMemberName("stopped")] Stopped,
    [JsonStringEnumMemberName("completed")] Completed,
}

/// <summary>candidates.operator</summary>
[JsonConverter(typeof(JsonStringEnumConverter<CandidateOperator>))]
public enum CandidateOperator
{
    [JsonStringEnumMemberName("mutation")] Mutation,
    [JsonStringEnumMemberName("crossover")] Crossover,
    [JsonStringEnumMemberName("llm_guided")] LlmGuided,
    [JsonStringEnumMemberName("seed")] Seed,
}

/// <summary>candidates.verdict</summary>
[JsonConverter(typeof(JsonStringEnumConverter<CandidateVerdict>))]
public enum CandidateVerdict
{
    [JsonStringEnumMemberName("pending")] Pending,
    [JsonStringEnumMemberName("sim_pass")] SimPass,
    [JsonStringEnumMemberName("sim_fail")] SimFail,
    [JsonStringEnumMemberName("real_pass")] RealPass,
    [JsonStringEnumMemberName("real_fail")] RealFail,
    [JsonStringEnumMemberName("accepted")] Accepted,
    [JsonStringEnumMemberName("rejected")] Rejected,
}

/// <summary>sim_runs.profile</summary>
[JsonConverter(typeof(JsonStringEnumConverter<SimProfile>))]
public enum SimProfile
{
    [JsonStringEnumMemberName("fast")] Fast,
    [JsonStringEnumMemberName("lidar")] Lidar,
    [JsonStringEnumMemberName("visual")] Visual,
}

/// <summary>artifacts.kind</summary>
[JsonConverter(typeof(JsonStringEnumConverter<ArtifactKind>))]
public enum ArtifactKind
{
    [JsonStringEnumMemberName("cad_src")] CadSrc,
    [JsonStringEnumMemberName("step")] Step,
    [JsonStringEnumMemberName("stl")] Stl,
    [JsonStringEnumMemberName("3mf")] ThreeMf,
    [JsonStringEnumMemberName("gcode")] Gcode,
    [JsonStringEnumMemberName("kicad")] Kicad,
    [JsonStringEnumMemberName("gerber")] Gerber,
    [JsonStringEnumMemberName("bom")] Bom,
    [JsonStringEnumMemberName("urdf")] Urdf,
    [JsonStringEnumMemberName("bt")] Bt,
}

/// <summary>print_jobs.state</summary>
[JsonConverter(typeof(JsonStringEnumConverter<PrintJobState>))]
public enum PrintJobState
{
    [JsonStringEnumMemberName("queued")] Queued,
    [JsonStringEnumMemberName("printing")] Printing,
    [JsonStringEnumMemberName("done")] Done,
    [JsonStringEnumMemberName("failed")] Failed,
    [JsonStringEnumMemberName("cancelled")] Cancelled,
}

/// <summary>approvals.decision</summary>
[JsonConverter(typeof(JsonStringEnumConverter<ApprovalDecision>))]
public enum ApprovalDecision
{
    [JsonStringEnumMemberName("approved")] Approved,
    [JsonStringEnumMemberName("rejected")] Rejected,
    [JsonStringEnumMemberName("expired")] Expired,
}

/// <summary>users.role — section 5.5 authority model.</summary>
[JsonConverter(typeof(JsonStringEnumConverter<UserRole>))]
public enum UserRole
{
    [JsonStringEnumMemberName("owner")] Owner,
    [JsonStringEnumMemberName("operator")] Operator,
    [JsonStringEnumMemberName("viewer")] Viewer,
}

/// <summary>devices.platform</summary>
[JsonConverter(typeof(JsonStringEnumConverter<DevicePlatform>))]
public enum DevicePlatform
{
    [JsonStringEnumMemberName("android")] Android,
    [JsonStringEnumMemberName("ios")] Ios,
    [JsonStringEnumMemberName("web")] Web,
}

/// <summary>commands.state</summary>
[JsonConverter(typeof(JsonStringEnumConverter<CommandState>))]
public enum CommandState
{
    [JsonStringEnumMemberName("pending")] Pending,
    [JsonStringEnumMemberName("delivered")] Delivered,
    [JsonStringEnumMemberName("applied")] Applied,
    [JsonStringEnumMemberName("failed")] Failed,
    [JsonStringEnumMemberName("rejected")] Rejected,
}
