// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.EntityFrameworkCore;
using Neml.Domain.Dtos;
using Neml.Infrastructure.Persistence;

namespace Neml.Infrastructure.Repositories;

/// <summary>GET /tasks and GET /tasks/{id}/runs of section 9.3.</summary>
public class TaskRepository(NemlDbContext db)
{
    public async Task<PagedResponse<TaskResponse>> QueryAsync(TaskQuery query, CancellationToken ct = default)
    {
        var page = Math.Max(query.Page, 1);
        var size = Math.Clamp(query.PageSize, 1, 200);

        var rows = db.Tasks.AsNoTracking();
        if (query.State is { } state) rows = rows.Where(t => t.State == state);
        if (query.Kind is { } kind) rows = rows.Where(t => t.Kind == kind);
        if (!string.IsNullOrWhiteSpace(query.Robot)) rows = rows.Where(t => t.RobotId == query.Robot);
        if (!string.IsNullOrWhiteSpace(query.SourcePrefix)) rows = rows.Where(t => t.Source.StartsWith(query.SourcePrefix));

        var total = await rows.CountAsync(ct);
        var items = await rows
            .OrderByDescending(t => t.Priority)             // matches the (state, priority DESC) index
            .ThenByDescending(t => t.CreatedAt)
            .Skip((page - 1) * size)
            .Take(size)
            .Select(t => new TaskResponse(
                t.Id, t.Title, t.Kind, t.Source, t.Priority, t.State, t.RobotId,
                t.Spec, t.Result, t.Deadline, t.CreatedAt, t.UpdatedAt))
            .ToListAsync(ct);

        return new PagedResponse<TaskResponse>(items, page, size, total);
    }

    public async Task<IReadOnlyList<TaskRunResponse>> RunsAsync(Guid taskId, CancellationToken ct = default) =>
        await db.TaskRuns.AsNoTracking()
            .Where(r => r.TaskId == taskId)
            .OrderBy(r => r.Attempt)
            .Select(r => new TaskRunResponse(
                r.Id, r.TaskId, r.Attempt, r.Env, r.Seed, r.StartedAt, r.EndedAt,
                r.Outcome, r.Metrics, r.RosbagPath))
            .ToListAsync(ct);
}
