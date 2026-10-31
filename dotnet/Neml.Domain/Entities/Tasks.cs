// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Neml.Domain.Enums;

namespace Neml.Domain.Entities;

/// <summary>Table <c>tasks</c>. Named TaskItem so it never collides with System.Threading.Tasks.Task.</summary>
public class TaskItem
{
    public Guid Id { get; set; }
    public required string Title { get; set; }
    public required TaskKind Kind { get; set; }
    public required string Source { get; set; }             // user:mg | auto:failure | auto:coverage
    public required decimal Priority { get; set; }          // section 14.2 formula
    public required TaskState State { get; set; }
    public string? RobotId { get; set; }
    public required JsonDocument Spec { get; set; }
    public JsonDocument? Result { get; set; }
    public DateTimeOffset? Deadline { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
}

/// <summary>Table <c>task_runs</c>.</summary>
public class TaskRun
{
    public long Id { get; set; }
    public required Guid TaskId { get; set; }
    public required int Attempt { get; set; }
    public required TaskRunEnv Env { get; set; }
    public long? Seed { get; set; }
    public required DateTimeOffset StartedAt { get; set; }
    public DateTimeOffset? EndedAt { get; set; }
    public TaskOutcome? Outcome { get; set; }
    public JsonDocument? Metrics { get; set; }
    public string? RosbagPath { get; set; }
}
