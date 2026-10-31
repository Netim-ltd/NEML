// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Neml.Domain.Enums;

namespace Neml.Domain.Entities;

/// <summary>Table <c>campaigns</c>.</summary>
public class Campaign
{
    public Guid Id { get; set; }
    public required string Name { get; set; }
    public required string Objective { get; set; }
    public required JsonDocument Weights { get; set; }      // fixed up front, never tuned mid run
    public required JsonDocument Budget { get; set; }       // section 14.4
    public required CampaignState State { get; set; }
    public DateTimeOffset StartedAt { get; set; }
    public DateTimeOffset? EndedAt { get; set; }
}

/// <summary>Table <c>candidates</c>.</summary>
public class Candidate
{
    public Guid Id { get; set; }
    public required Guid CampaignId { get; set; }
    public required int Generation { get; set; }
    public required string GenomeId { get; set; }
    public required CandidateOperator Operator { get; set; }
    public string? Rationale { get; set; }
    public string? LlmModel { get; set; }
    public string? PromptHash { get; set; }
    public decimal? Fitness { get; set; }
    public JsonDocument? FitnessParts { get; set; }
    public CandidateVerdict? Verdict { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
}

/// <summary>Table <c>sim_runs</c>.</summary>
public class SimRun
{
    public long Id { get; set; }
    public Guid? CandidateId { get; set; }
    public required string WorldId { get; set; }
    public required long Seed { get; set; }
    public required SimProfile Profile { get; set; }
    public required string SimVersion { get; set; }
    public decimal? DurationS { get; set; }
    public required JsonDocument Metrics { get; set; }
    public bool Deterministic { get; set; } = true;
    public DateTimeOffset RunAt { get; set; }
}
