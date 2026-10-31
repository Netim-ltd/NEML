// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;
using Neml.Api.Auth;
using Neml.Api.Contracts;
using Neml.Api.Services;
using Neml.Domain.Dtos;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;
using Neml.Infrastructure.Repositories;
using CommandQueue = Neml.Api.Services.CommandQueue;

namespace Neml.Api.Controllers;

/// <summary>
/// Spec 9.3 Tasks. The lab owns the tasks table; the cloud copy is a mirror, so every write
/// here becomes a queued command instead of an UPDATE.
/// </summary>
[Route("api/v1/tasks")]
[Tags("Tasks")]
public sealed class TasksController(NemlDbContext db, TaskRepository tasks, CommandQueue queue) : NemlController
{
    /// <summary>state and kind are the spec 7 text values, e.g. awaiting_approval, calibration; source filters by prefix, e.g. user:.</summary>
    [HttpGet]
    [ProducesResponseType<PagedResponse<TaskResponse>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<PagedResponse<TaskResponse>>> List(
        [FromQuery] string? state,
        [FromQuery] string? kind,
        [FromQuery] string? robot,
        [FromQuery] string? source,
        [FromQuery] int page,
        CancellationToken ct)
    {
        TaskState? parsedState = null;
        if (!string.IsNullOrEmpty(state))
        {
            if (!EnumText.TryParse<TaskState>(state, out var value))
            {
                return Problem($"unknown state '{state}'", statusCode: StatusCodes.Status400BadRequest);
            }

            parsedState = value;
        }

        TaskKind? parsedKind = null;
        if (!string.IsNullOrEmpty(kind))
        {
            if (!EnumText.TryParse<TaskKind>(kind, out var value))
            {
                return Problem($"unknown kind '{kind}'", statusCode: StatusCodes.Status400BadRequest);
            }

            parsedKind = value;
        }

        return Ok(await tasks.QueryAsync(new TaskQuery(parsedState, parsedKind, robot, Math.Max(page, 1), SourcePrefix: source), ct));
    }

    [HttpGet("{id:guid}")]
    [ProducesResponseType<TaskResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<TaskResponse>> Get(Guid id, CancellationToken ct)
    {
        var task = await db.Tasks.AsNoTracking()
            .Where(t => t.Id == id)
            .Select(t => new TaskResponse(
                t.Id, t.Title, t.Kind, t.Source, t.Priority, t.State, t.RobotId,
                t.Spec, t.Result, t.Deadline, t.CreatedAt, t.UpdatedAt))
            .FirstOrDefaultAsync(ct);

        return task is null ? NotFound() : task;
    }

    [HttpGet("{id:guid}/runs")]
    [ProducesResponseType<IReadOnlyList<TaskRunResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<TaskRunResponse>>> Runs(Guid id, CancellationToken ct) =>
        Ok(await tasks.RunsAsync(id, ct));

    [HttpPost]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public Task<ActionResult<CommandAccepted>> Create(CreateTaskRequest request, CancellationToken ct) =>
        EnqueueAsync(CommandQueue.TaskCreate, request, ct);

    [HttpPatch("{id:guid}")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public Task<ActionResult<CommandAccepted>> Update(Guid id, UpdateTaskRequest request, CancellationToken ct) =>
        EnqueueAsync(
            CommandQueue.TaskUpdate,
            new { taskId = id, request.Title, request.Priority, request.State, request.RobotId, request.Deadline },
            ct);

    [HttpPost("{id:guid}/cancel")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public Task<ActionResult<CommandAccepted>> Cancel(Guid id, CancelRequest request, CancellationToken ct) =>
        EnqueueAsync(CommandQueue.TaskCancel, new { taskId = id, request.Reason }, ct);

    private async Task<ActionResult<CommandAccepted>> EnqueueAsync(string kind, object payload, CancellationToken ct)
    {
        var accepted = await queue.EnqueueAsync(
            UserId, kind, JsonSerializer.Serialize(payload, JsonSerializerOptions.Web), IdempotencyKey(), ct);
        return Accepted(accepted);
    }
}
