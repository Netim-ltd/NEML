// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Neml.Domain.Enums;

namespace Neml.Domain.Entities;

/// <summary>Table <c>artifacts</c>.</summary>
public class Artifact
{
    public Guid Id { get; set; }
    public required ArtifactKind Kind { get; set; }
    public required string Path { get; set; }
    public required string Sha256 { get; set; }
    public string? GenomeId { get; set; }
    public required string Generator { get; set; }          // template_id or manual
    public string? InputHash { get; set; }
    public string? LlmModel { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
}

/// <summary>Table <c>print_jobs</c>.</summary>
public class PrintJob
{
    public Guid Id { get; set; }
    public required Guid ArtifactId { get; set; }
    public required string PrinterId { get; set; }
    public required string ProfileId { get; set; }
    public required Guid ApprovalId { get; set; }           // section 7 declares no FK on this column
    public decimal? EstTimeH { get; set; }
    public decimal? EstFilamentG { get; set; }
    public decimal? EstCostTry { get; set; }
    public required PrintJobState State { get; set; }
    public JsonDocument? Qc { get; set; }                   // section 12.4 measurements
    public DateTimeOffset? StartedAt { get; set; }
    public DateTimeOffset? EndedAt { get; set; }
}

/// <summary>Table <c>bom_items</c>.</summary>
public class BomItem
{
    public long Id { get; set; }
    public required string GenomeId { get; set; }
    public required string Ref { get; set; }
    public required string PartNumber { get; set; }
    public required int Qty { get; set; }
    public decimal? UnitCostTry { get; set; }
    public string? Supplier { get; set; }
    public int? LeadTimeDays { get; set; }
}
