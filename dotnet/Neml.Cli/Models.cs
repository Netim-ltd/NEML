// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;

namespace Neml.Cli;

// Wire shapes for the §9.3 endpoints the CLI touches, mirroring Neml.Api.Contracts.
// Thin client: no logic lives here.

public sealed record LoginRequest(string Email, string Password);

public sealed record TokenPair(string Access, string Refresh);

public sealed record RefreshRequest(string Refresh);

public sealed record Paged<T>(IReadOnlyList<T> Items, int Page, int PageSize);

public sealed record BrainStatus(bool Online, string? Model, string? GpuOwner, double? BudgetUsed, DateTimeOffset? LastSeen);

public sealed record Robot(string Id, string State, decimal? BatterySoc, DateTimeOffset? LastSeen, decimal? RealityGap);

public sealed record TaskItem(
    Guid Id,
    string Title,
    string Kind,
    string Source,
    decimal Priority,
    string State,
    string? RobotId,
    JsonElement? Spec,
    JsonElement? Result);

public sealed record Approval(
    Guid Id,
    int Level,
    string SubjectKind,
    string SubjectId,
    JsonElement? Payload,
    DateTimeOffset RequestedAt,
    DateTimeOffset ExpiresAt,
    string? DecidedBy,
    string? Decision,
    string? Note,
    string? PreviewUrl);

public sealed record ApprovalDecision(string? Note, string? Confirmation);
