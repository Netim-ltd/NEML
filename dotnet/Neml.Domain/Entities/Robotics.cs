// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Neml.Domain.Enums;

namespace Neml.Domain.Entities;

// Columns follow NEML_SPEC.md section 7 one for one. No navigation properties:
// the API reads by foreign key and the genome tree is assembled in memory.

/// <summary>Table <c>genomes</c>.</summary>
public class Genome
{
    public required string Id { get; set; }                 // quadruped_v2@a3f91c7
    public required string Name { get; set; }
    public required int Version { get; set; }
    public required string Hash { get; set; }
    public string? ParentId { get; set; }
    public required GenomeStatus Status { get; set; }
    public required JsonDocument Body { get; set; }         // section 13 schema
    public required JsonDocument Limits { get; set; }       // immutable
    public decimal? FitnessScore { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
}

/// <summary>Table <c>robots</c>.</summary>
public class Robot
{
    public required string Id { get; set; }                 // R01
    public required string GenomeId { get; set; }
    public required string Namespace { get; set; }
    public required string Hostname { get; set; }
    public required RobotState State { get; set; }
    public decimal? BatterySoc { get; set; }
    public DateTimeOffset? LastSeen { get; set; }
    public DateTimeOffset? CalibratedAt { get; set; }
    public decimal? RealityGap { get; set; }                // section 11.3
    public DateTimeOffset CreatedAt { get; set; }
}

/// <summary>Table <c>skills</c>.</summary>
public class Skill
{
    public required string Id { get; set; }                 // climb_small_obstacle@3
    public required string SkillKey { get; set; }
    public required int Version { get; set; }
    public required string GenomeId { get; set; }
    public required string BtPath { get; set; }             // behavior tree xml
    public required JsonDocument Parameters { get; set; }
    public required JsonDocument Preconditions { get; set; }
    public required SkillStatus Status { get; set; }
    public string? Supersedes { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
}

/// <summary>Table <c>skill_validations</c>.</summary>
public class SkillValidation
{
    public long Id { get; set; }
    public required string SkillId { get; set; }
    public required ValidationEnv Env { get; set; }
    public required int Trials { get; set; }
    public required int Successes { get; set; }
    public required decimal Ci95Low { get; set; }
    public required decimal Ci95High { get; set; }
    public required int[] Seeds { get; set; }
    public JsonDocument? FailureModes { get; set; }
    public DateTimeOffset RunAt { get; set; }
}

/// <summary>
/// Table <c>skill_runs</c> (ADR-011) — one trial per row, where skill_validations only keeps
/// the trials/successes total. Section 14.2's "last 20 runs" is a query over this table, and
/// <see cref="Deterministic"/> is what lets section 11.2 rule 3 drop a run inside that query.
/// </summary>
public class SkillRun
{
    public long Id { get; set; }
    public required string SkillId { get; set; }
    public long? TaskRunId { get; set; }
    public required ValidationEnv Env { get; set; }
    public long? Seed { get; set; }
    public required bool Success { get; set; }
    public string? FailureMode { get; set; }                // one of the ten ADR-013 modes
    public bool Deterministic { get; set; } = true;
    public DateTimeOffset RunAt { get; set; }
}
