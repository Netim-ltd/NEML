// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Neml.Domain.Dtos;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;
using Neml.Infrastructure.Repositories;

namespace Neml.Tests;

/// <summary>
/// The §9.3 read paths that only exist as SQL: paging and filtering, the §5.2 expiry sweep,
/// the lineage tree and the partitioned telemetry table. Every case runs against the real
/// PostgreSQL TestDb provisions, because none of this survives an in-memory provider.
/// </summary>
public sealed class RepositoryTests
{
    private static JsonDocument Json(string raw = "{}") => JsonDocument.Parse(raw);

    // ---------- tasks ----------

    [Fact]
    public async Task Tasks_are_filtered_paged_and_ordered_by_priority()
    {
        await using var db = TestDb.Connect();
        var robot = await SeedRobotAsync(db);
        var other = await SeedRobotAsync(db);

        for (var i = 0; i < 5; i++)
        {
            db.Tasks.Add(NewTask(robot, priority: i, state: i < 3 ? TaskState.Queued : TaskState.Running));
        }

        // A task on another robot must never leak into the filtered page.
        db.Tasks.Add(NewTask(other, priority: 99, state: TaskState.Queued));
        await db.SaveChangesAsync();

        var repository = new TaskRepository(db);

        var all = await repository.QueryAsync(new TaskQuery(null, null, robot));
        Assert.Equal(5, all.Total);
        Assert.Equal([4m, 3m, 2m, 1m, 0m], all.Items.Select(t => t.Priority));

        var queued = await repository.QueryAsync(new TaskQuery(TaskState.Queued, null, robot));
        Assert.Equal(3, queued.Total);
        Assert.All(queued.Items, t => Assert.Equal(TaskState.Queued, t.State));

        var byKind = await repository.QueryAsync(new TaskQuery(null, TaskKind.Repair, robot));
        Assert.Equal(0, byKind.Total);

        // Page 2 of a 2 per page cut, and the out of range page and size are clamped, not thrown.
        var second = await repository.QueryAsync(new TaskQuery(null, null, robot, Page: 2, PageSize: 2));
        Assert.Equal([2m, 1m], second.Items.Select(t => t.Priority));
        Assert.Equal(5, second.Total);

        var clamped = await repository.QueryAsync(new TaskQuery(null, null, robot, Page: 0, PageSize: 10_000));
        Assert.Equal(1, clamped.Page);
        Assert.Equal(200, clamped.PageSize);
        Assert.Equal(5, clamped.Items.Count);
    }

    [Fact]
    public async Task Task_runs_come_back_in_attempt_order()
    {
        await using var db = TestDb.Connect();
        var task = NewTask(await SeedRobotAsync(db), priority: 1, state: TaskState.Running);
        db.Tasks.Add(task);
        foreach (var attempt in (int[])[3, 1, 2])
        {
            db.TaskRuns.Add(new TaskRun
            {
                TaskId = task.Id,
                Attempt = attempt,
                Env = TaskRunEnv.Sim,
                StartedAt = DateTimeOffset.UtcNow,
                Outcome = attempt == 3 ? TaskOutcome.Success : TaskOutcome.Failure,
                Metrics = Json("""{"ok":true}"""),
            });
        }

        await db.SaveChangesAsync();

        var runs = await new TaskRepository(db).RunsAsync(task.Id);

        Assert.Equal([1, 2, 3], runs.Select(r => r.Attempt));
        Assert.Equal(TaskOutcome.Success, runs[^1].Outcome);
        Assert.Empty(await new TaskRepository(db).RunsAsync(Guid.NewGuid()));
    }

    // ---------- approvals (§5.2) ----------

    [Fact]
    public async Task An_overdue_approval_is_expired_and_drops_out_of_pending()
    {
        await using var db = TestDb.Connect();
        var subject = Guid.NewGuid().ToString("N");
        var live = NewApproval(subject, DateTimeOffset.UtcNow.AddMinutes(30));
        var overdue = NewApproval(subject, DateTimeOffset.UtcNow.AddMinutes(-1));
        db.Approvals.AddRange(live, overdue);
        await db.SaveChangesAsync();

        var repository = new ApprovalRepository(db);

        var pendingBefore = await repository.PendingAsync();
        Assert.Contains(pendingBefore, a => a.Id == live.Id);
        Assert.DoesNotContain(pendingBefore, a => a.Id == overdue.Id);   // Already past its deadline.

        // A parallel test's API host sweeps at start-up (ApprovalExpiryService), so this call may find
        // nothing left to do; what matters is that the row ends up expired.
        await repository.ExpireOverdueAsync();

        await using var fresh = TestDb.Connect();
        var stored = await fresh.Approvals.FindAsync(overdue.Id);
        Assert.Equal(ApprovalDecision.Expired, stored!.Decision);
        Assert.NotNull(stored.DecidedAt);

        // The sweep is idempotent and never touches an approval that still has time.
        Assert.Equal(0, await repository.ExpireOverdueAsync());
        Assert.Contains(await repository.PendingAsync(), a => a.Id == live.Id);
    }

    [Fact]
    public async Task Pending_approvals_are_soonest_to_expire_first()
    {
        await using var db = TestDb.Connect();
        var subject = Guid.NewGuid().ToString("N");
        var late = NewApproval(subject, DateTimeOffset.UtcNow.AddHours(4));
        var soon = NewApproval(subject, DateTimeOffset.UtcNow.AddHours(1));
        db.Approvals.AddRange(late, soon);
        await db.SaveChangesAsync();

        var mine = (await new ApprovalRepository(db).PendingAsync())
            .Where(a => a.SubjectId == subject)
            .ToList();

        Assert.Equal([soon.Id, late.Id], mine.Select(a => a.Id));
    }

    // ---------- genome lineage ----------

    [Fact]
    public async Task Genome_tree_nests_children_under_their_parent()
    {
        await using var db = TestDb.Connect();
        var tag = Guid.NewGuid().ToString("N")[..8];
        var root = NewGenome($"root-{tag}", null);
        var child = NewGenome($"child-{tag}", root.Id);
        var grandchild = NewGenome($"grand-{tag}", child.Id);

        db.Genomes.AddRange(root, child, grandchild);
        await db.SaveChangesAsync();

        var tree = await new GenomeRepository(db).TreeAsync();

        var rootNode = Assert.Single(tree, n => n.Id == root.Id);
        var childNode = Assert.Single(rootNode.Children);
        Assert.Equal(child.Id, childNode.Id);
        Assert.Equal(grandchild.Id, Assert.Single(childNode.Children).Id);

        // Only roots sit at the top level; a child never appears twice.
        Assert.DoesNotContain(tree, n => n.Id == child.Id);
        Assert.DoesNotContain(tree, n => n.Id == grandchild.Id);
    }

    // ---------- telemetry (keyless, partitioned) ----------

    [Fact]
    public async Task Telemetry_batch_round_trips_raw_and_aggregated()
    {
        await using var db = TestDb.Connect();
        var repository = new TelemetryRepository(db);
        var robot = $"R{Guid.NewGuid():N}"[..12];
        var minute = new DateTimeOffset(DateTime.UtcNow.Date.AddHours(3), TimeSpan.Zero);

        Assert.Equal(0, await repository.InsertBatchAsync([]));

        var samples = new List<TelemetrySample>
        {
            new(minute.AddSeconds(1), robot, "battery_soc", 10, Json("""{"unit":"%"}""")),
            new(minute.AddSeconds(2), robot, "battery_soc", 30, null),
            new(minute.AddMinutes(1), robot, "battery_soc", 50, null),
        };
        Assert.Equal(3, await repository.InsertBatchAsync(samples));

        var window = new TelemetryQuery("battery_soc", minute, minute.AddMinutes(5), "raw");
        var raw = await repository.RangeAsync(robot, window);
        Assert.Equal([10d, 30d, 50d], raw.Select(p => p.Value));

        var avg = await repository.RangeAsync(robot, window with { Agg = "avg" });
        Assert.Equal([20d, 50d], avg.Select(p => p.Value));

        var max = await repository.RangeAsync(robot, window with { Agg = "max" });
        Assert.Equal([30d, 50d], max.Select(p => p.Value));

        Assert.Equal([2d, 1d], (await repository.RangeAsync(robot, window with { Agg = "count" })).Select(p => p.Value));

        // Outside the window, and another robot's metric, stay out.
        Assert.Empty(await repository.RangeAsync(robot, window with { From = minute.AddHours(1), To = minute.AddHours(2) }));
        Assert.Empty(await repository.RangeAsync($"other-{robot}", window));
    }

    [Fact]
    public async Task An_unknown_aggregation_is_refused_before_any_sql_runs()
    {
        await using var db = TestDb.Connect();
        var query = new TelemetryQuery("battery_soc", DateTimeOffset.UtcNow.AddHours(-1), DateTimeOffset.UtcNow, "drop table");

        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(
            () => new TelemetryRepository(db).RangeAsync("R01", query));
    }

    // ---------- fixtures ----------

    /// <summary>tasks.robot_id is a real foreign key, and robots.genome_id is another one.</summary>
    private static async Task<string> SeedRobotAsync(NemlDbContext db)
    {
        var id = Guid.NewGuid().ToString("N")[..12];
        db.Genomes.Add(NewGenome($"genome-{id}", null));
        db.Robots.Add(new Robot
        {
            Id = $"R{id}",
            GenomeId = $"genome-{id}",
            Namespace = $"/r{id}",
            Hostname = $"{id}.lab",
            State = RobotState.Idle,
            CreatedAt = DateTimeOffset.UtcNow,
        });
        await db.SaveChangesAsync();
        return $"R{id}";
    }

    private static TaskItem NewTask(string robot, decimal priority, TaskState state) => new()
    {
        Id = Guid.NewGuid(),
        Title = $"task {priority}",
        Kind = TaskKind.Human,
        Source = "user:mg",
        Priority = priority,
        State = state,
        RobotId = robot,
        Spec = Json(),
        CreatedAt = DateTimeOffset.UtcNow,
        UpdatedAt = DateTimeOffset.UtcNow,
    };

    private static Approval NewApproval(string subjectId, DateTimeOffset expiresAt) => new()
    {
        Id = Guid.NewGuid(),
        Level = 2,
        SubjectKind = "task",
        SubjectId = subjectId,
        Payload = Json("""{"summary":"move"}"""),
        RequestedAt = DateTimeOffset.UtcNow,
        ExpiresAt = expiresAt,
    };

    private static Genome NewGenome(string id, string? parentId) => new()
    {
        Id = id,
        Name = id,
        Version = 1,
        Hash = id,
        ParentId = parentId,
        Status = GenomeStatus.Draft,
        Body = Json(),
        Limits = Json(),
        CreatedAt = DateTimeOffset.UtcNow,
    };
}
