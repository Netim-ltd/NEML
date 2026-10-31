// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Neml.Api.Contracts;
using Neml.Api.Controllers;
using CommandQueue = Neml.Api.Services.CommandQueue;
using Neml.Domain.Dtos;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;
using PasswordHasher = Neml.Infrastructure.Security.PasswordHasher;

namespace Neml.Tests;

/// <summary>
/// T-052 over the wire: the §9.3 endpoints hosted on the migrated database, so what is asserted
/// is the answer the client really gets rather than the shape of a method. Every test seeds its
/// own user, which also keeps the §5.5 ten commands a minute budget per test.
/// </summary>
[Collection(NemlCloud.Name)]
public sealed class ApiEndpointTests : IDisposable
{
    private readonly ApiFactory factory = new();

    public void Dispose() => factory.Dispose();

    // ---------- §5.5 auth, end to end ----------

    [ApiFact]
    public async Task Login_refresh_and_logout_round_trip()
    {
        const string password = "correct-horse-battery";
        await using var db = TestDb.Connect();
        var user = new User
        {
            Id = Guid.NewGuid(),
            Email = $"{Guid.NewGuid():N}@neml.test",
            PasswordHash = PasswordHasher.Hash(password),
            Role = UserRole.Operator,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();

        using var client = factory.CreateClient();

        var wrong = await client.PostAsJsonAsync("api/v1/auth/login", new LoginRequest(user.Email, "wrong-password!!"));
        Assert.Equal(HttpStatusCode.Unauthorized, wrong.StatusCode);

        var login = await client.PostAsJsonAsync("api/v1/auth/login", new LoginRequest(user.Email, password));
        login.EnsureSuccessStatusCode();
        var first = await login.Content.ReadFromJsonAsync<TokenResponse>();
        Assert.NotNull(first);
        Assert.NotEmpty(first.Access);

        var refresh = await client.PostAsJsonAsync("api/v1/auth/refresh", new RefreshRequest(first.Refresh));
        refresh.EnsureSuccessStatusCode();
        var second = await refresh.Content.ReadFromJsonAsync<TokenResponse>();
        Assert.NotEqual(first.Refresh, second!.Refresh);

        // §5.5 rotation: the spent token is dead, and so is the chain it leaked.
        var replay = await client.PostAsJsonAsync("api/v1/auth/refresh", new RefreshRequest(first.Refresh));
        Assert.Equal(HttpStatusCode.Unauthorized, replay.StatusCode);

        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", second.Access);
        var logout = await client.PostAsJsonAsync("api/v1/auth/logout", new LogoutRequest(second.Refresh));
        Assert.Equal(HttpStatusCode.NoContent, logout.StatusCode);
    }

    [ApiFact]
    public async Task Registering_a_device_twice_keeps_one_row()
    {
        using var client = await AuthenticatedAsync(UserRole.Viewer);
        var token = Guid.NewGuid().ToString("N");

        var first = await client.PostAsJsonAsync(
            "api/v1/auth/devices", new RegisterDeviceRequest(DevicePlatform.Android, token));
        first.EnsureSuccessStatusCode();
        var device = await first.Content.ReadFromJsonAsync<DeviceResponse>();

        var again = await client.PostAsJsonAsync(
            "api/v1/auth/devices", new RegisterDeviceRequest(DevicePlatform.Android, token));
        again.EnsureSuccessStatusCode();

        Assert.Equal(device!.Id, (await again.Content.ReadFromJsonAsync<DeviceResponse>())!.Id);
        Assert.NotNull(device.LastSeen);
    }

    // ---------- §9.3 robots ----------

    [ApiFact]
    public async Task Robots_are_listed_fetched_and_missing_ones_are_404()
    {
        var robot = await SeedRobotAsync();
        using var client = await AuthenticatedAsync(UserRole.Viewer);

        var list = await client.GetFromJsonAsync<List<RobotResponse>>("api/v1/robots");
        Assert.Contains(list!, r => r.Id == robot);

        var one = await client.GetFromJsonAsync<RobotResponse>($"api/v1/robots/{robot}");
        Assert.Equal(robot, one!.Id);

        using var missing = await client.GetAsync($"api/v1/robots/{Guid.NewGuid():N}");
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
    }

    [ApiFact]
    public async Task Telemetry_defaults_to_the_last_hour_and_refuses_an_unknown_aggregation()
    {
        var robot = await SeedRobotAsync();
        using var client = await AuthenticatedAsync(UserRole.Viewer);

        var points = await client.GetFromJsonAsync<List<TelemetryPointResponse>>(
            $"api/v1/robots/{robot}/telemetry?metric=battery_soc");
        Assert.Empty(points!);

        using var noMetric = await client.GetAsync($"api/v1/robots/{robot}/telemetry?metric=");
        Assert.Equal(HttpStatusCode.BadRequest, noMetric.StatusCode);

        using var badAgg = await client.GetAsync($"api/v1/robots/{robot}/telemetry?metric=battery_soc&agg=median");
        Assert.Equal(HttpStatusCode.BadRequest, badAgg.StatusCode);
    }

    [ApiFact]
    public async Task Estop_is_queued_rather_than_applied()
    {
        var robot = await SeedRobotAsync();
        using var client = await AuthenticatedAsync(UserRole.Operator);

        var response = await client.PostAsJsonAsync(
            $"api/v1/robots/{robot}/estop", new EstopRequest("obstacle in the cell"));

        Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);
        var accepted = await response.Content.ReadFromJsonAsync<CommandAccepted>();
        Assert.Equal("pending", accepted!.State);       // §19 risk 11: a receipt, never a done deed.
        Assert.True(accepted.Seq > 0);
    }

    // ---------- §9.3 tasks ----------

    [ApiFact]
    public async Task Task_list_filters_are_validated_before_they_reach_sql()
    {
        var robot = await SeedRobotAsync();
        using var client = await AuthenticatedAsync(UserRole.Viewer);

        var page = await client.GetFromJsonAsync<PagedResponse<TaskResponse>>(
            $"api/v1/tasks?robot={robot}&state=queued&kind=human&page=0");
        Assert.Equal(0, page!.Total);
        Assert.Equal(1, page.Page);

        using var badState = await client.GetAsync("api/v1/tasks?state=napping");
        Assert.Equal(HttpStatusCode.BadRequest, badState.StatusCode);

        using var badKind = await client.GetAsync("api/v1/tasks?kind=knitting");
        Assert.Equal(HttpStatusCode.BadRequest, badKind.StatusCode);

        using var missing = await client.GetAsync($"api/v1/tasks/{Guid.NewGuid()}");
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);

        var runs = await client.GetFromJsonAsync<List<TaskRunResponse>>($"api/v1/tasks/{Guid.NewGuid()}/runs");
        Assert.Empty(runs!);
    }

    [ApiFact]
    public async Task Every_task_write_becomes_a_queued_command()
    {
        var robot = await SeedRobotAsync();
        using var client = await AuthenticatedAsync(UserRole.Operator);
        var id = Guid.NewGuid();

        var create = await client.PostAsJsonAsync("api/v1/tasks", new CreateTaskRequest(
            "survey the cell", TaskKind.Human, "user:mg", 5m, robot, JsonDocument.Parse("{}"), null));
        Assert.Equal(HttpStatusCode.Accepted, create.StatusCode);

        var patch = await client.PatchAsJsonAsync(
            $"api/v1/tasks/{id}", new UpdateTaskRequest("renamed", null, null, null, null));
        Assert.Equal(HttpStatusCode.Accepted, patch.StatusCode);

        var cancel = await client.PostAsJsonAsync($"api/v1/tasks/{id}/cancel", new CancelRequest("not needed"));
        Assert.Equal(HttpStatusCode.Accepted, cancel.StatusCode);

        // §3.1: repeating the Idempotency-Key repeats the receipt instead of queueing twice.
        client.DefaultRequestHeaders.Add(NemlController.IdempotencyHeader, Guid.NewGuid().ToString("N"));
        var once = await (await client.PostAsJsonAsync($"api/v1/tasks/{id}/cancel", new CancelRequest(null)))
            .Content.ReadFromJsonAsync<CommandAccepted>();
        var twice = await (await client.PostAsJsonAsync($"api/v1/tasks/{id}/cancel", new CancelRequest(null)))
            .Content.ReadFromJsonAsync<CommandAccepted>();
        Assert.Equal(once!.CommandId, twice!.CommandId);
        Assert.Equal(once.Seq, twice.Seq);
    }

    // ---------- admin settings (queued like every lab round trip) ----------

    [ApiFact]
    public async Task Model_settings_reads_and_writes_are_queued_and_only_the_owner_may_write()
    {
        using var owner = await AuthenticatedAsync(UserRole.Owner);
        var read = await owner.GetAsync("api/v1/model-settings/quadruped_v2");
        Assert.Equal(HttpStatusCode.Accepted, read.StatusCode);
        var readAccepted = await read.Content.ReadFromJsonAsync<CommandAccepted>();
        var readStatus = await owner.GetFromJsonAsync<CommandDto>($"api/v1/brain/command/{readAccepted!.CommandId}");
        Assert.Equal("model_settings.get", readStatus!.Kind);

        var write = await owner.PutAsJsonAsync(
            "api/v1/model-settings/quadruped_v2",
            new ModelSettingsRequest(new() { ["mtbf_min_hours"] = 400, ["max_payload_kg"] = null }));
        Assert.Equal(HttpStatusCode.Accepted, write.StatusCode);
        var writeAccepted = await write.Content.ReadFromJsonAsync<CommandAccepted>();
        var writeStatus = await owner.GetFromJsonAsync<CommandDto>($"api/v1/brain/command/{writeAccepted!.CommandId}");
        Assert.Equal("model_settings.put", writeStatus!.Kind);

        using var operatorClient = await AuthenticatedAsync(UserRole.Operator);
        Assert.Equal(HttpStatusCode.Accepted, (await operatorClient.GetAsync("api/v1/model-settings")).StatusCode);
        var denied = await operatorClient.PutAsJsonAsync(
            "api/v1/model-settings/quadruped_v2", new ModelSettingsRequest(new() { ["mtbf_min_hours"] = 1 }));
        Assert.Equal(HttpStatusCode.Forbidden, denied.StatusCode);

        using var viewer = await AuthenticatedAsync(UserRole.Viewer);
        Assert.Equal(HttpStatusCode.Forbidden, (await viewer.GetAsync("api/v1/model-settings")).StatusCode);
    }

    // ---------- §9.3 brain ----------

    [ApiFact]
    public async Task A_brain_command_is_queued_and_can_be_followed_up()
    {
        using var client = await AuthenticatedAsync(UserRole.Operator);

        var queued = await client.PostAsJsonAsync("api/v1/brain/command", new BrainCommandRequest("cancel task 7"));
        Assert.Equal(HttpStatusCode.Accepted, queued.StatusCode);
        var accepted = await queued.Content.ReadFromJsonAsync<CommandAccepted>();

        var status = await client.GetFromJsonAsync<CommandDto>($"api/v1/brain/command/{accepted!.CommandId}");
        Assert.Equal(CommandQueue.BrainCommand, status!.Kind);
        Assert.Equal("pending", status.State);
        Assert.Null(status.AppliedAt);

        using var unknown = await client.GetAsync($"api/v1/brain/command/{Guid.NewGuid()}");
        Assert.Equal(HttpStatusCode.NotFound, unknown.StatusCode);

        // The bridge is down in a test host, so the brain reports itself offline.
        var brain = await client.GetFromJsonAsync<BrainStatusResponse>("api/v1/brain/status");
        Assert.False(brain!.Online);
    }

    // ---------- §5.2 / §9.3 approvals ----------

    [ApiFact]
    public async Task An_approval_is_decided_once_and_then_conflicts()
    {
        var approval = await SeedApprovalAsync(level: 2);
        using var client = await AuthenticatedAsync(UserRole.Operator);

        var pending = await client.GetFromJsonAsync<List<ApprovalResponse>>("api/v1/approvals?pending=true");
        Assert.Contains(pending!, a => a.Id == approval);

        var detail = await client.GetFromJsonAsync<ApprovalResponse>($"api/v1/approvals/{approval}");
        Assert.Equal(2, detail!.Level);

        var approve = await client.PostAsJsonAsync(
            $"api/v1/approvals/{approval}/approve", new ApprovalDecisionRequest("looks right"));
        Assert.Equal(HttpStatusCode.Accepted, approve.StatusCode);

        var again = await client.PostAsJsonAsync(
            $"api/v1/approvals/{approval}/approve", new ApprovalDecisionRequest(null));
        Assert.Equal(HttpStatusCode.Conflict, again.StatusCode);

        using var missing = await client.PostAsJsonAsync(
            $"api/v1/approvals/{Guid.NewGuid()}/reject", new ApprovalDecisionRequest(null));
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
    }

    [ApiFact]
    public async Task Level_4_is_owner_only_and_an_expired_approval_cannot_be_decided()
    {
        var level4 = await SeedApprovalAsync(level: 4);
        var stale = await SeedApprovalAsync(level: 1, expiresAt: DateTimeOffset.UtcNow.AddMinutes(-1));

        using var operatorClient = await AuthenticatedAsync(UserRole.Operator);
        var refused = await operatorClient.PostAsJsonAsync(
            $"api/v1/approvals/{level4}/approve", new ApprovalDecisionRequest(null));
        Assert.Equal(HttpStatusCode.Forbidden, refused.StatusCode);   // §5.5: level 4 is owner only.

        using var ownerClient = await AuthenticatedAsync(UserRole.Owner);
        var allowed = await ownerClient.PostAsJsonAsync(
            $"api/v1/approvals/{level4}/approve", new ApprovalDecisionRequest(null));
        Assert.Equal(HttpStatusCode.Accepted, allowed.StatusCode);

        var expired = await ownerClient.PostAsJsonAsync(
            $"api/v1/approvals/{stale}/reject", new ApprovalDecisionRequest(null));
        Assert.Equal(HttpStatusCode.Conflict, expired.StatusCode);    // §5.2: out of time is not decidable.
    }

    // ---------- endpoints the app screens call ----------

    [ApiFact]
    public async Task Audit_lists_newest_first_and_filters_by_actor()
    {
        var actor = $"agent:{Guid.NewGuid():N}"[..20];
        await using (var db = TestDb.Connect())
        {
            db.AuditLog.AddRange(
                new AuditLogEntry { Actor = actor, Action = "old", Ts = DateTimeOffset.UtcNow.AddMinutes(-5), Outcome = "ok" },
                new AuditLogEntry { Actor = actor, Action = "new", Ts = DateTimeOffset.UtcNow, Outcome = "error" },
                new AuditLogEntry { Actor = "user:other", Action = "noise", Ts = DateTimeOffset.UtcNow });
            await db.SaveChangesAsync();
        }

        using var client = await AuthenticatedAsync(UserRole.Viewer);
        var rows = await client.GetFromJsonAsync<AuditResponse[]>($"api/v1/audit?actor={actor}");
        Assert.Equal(["new", "old"], rows!.Select(r => r.Action));

        var errors = await client.GetFromJsonAsync<AuditResponse[]>($"api/v1/audit?actor={actor}&outcome=error");
        Assert.Equal("new", Assert.Single(errors!).Action);
    }

    [ApiFact]
    public async Task Bridge_audit_log_message_is_mirrored_into_audit_log()
    {
        var actor = $"agent:{Guid.NewGuid():N}"[..20];
        await using var db = TestDb.Connect();
        var mirror = new Api.Services.MirrorWriter(db);
        await mirror.InsertAuditAsync(
            [new Api.Bridge.AuditPayload(DateTimeOffset.UtcNow, actor, "cad.generate", "bracket", "ok", 12, null)],
            CancellationToken.None);

        Assert.Equal(1, db.AuditLog.Count(a => a.Actor == actor));
    }

    [ApiFact]
    public async Task Devices_lists_only_the_callers_own_registrations()
    {
        using var client = await AuthenticatedAsync(UserRole.Viewer);
        using var other = await AuthenticatedAsync(UserRole.Viewer);
        var token = $"push-{Guid.NewGuid():N}";
        (await client.PostAsJsonAsync("api/v1/auth/devices", new { platform = "android", pushToken = token }))
            .EnsureSuccessStatusCode();

        var mine = await client.GetFromJsonAsync<DeviceResponse[]>("api/v1/auth/devices");
        Assert.Equal(token, Assert.Single(mine!).PushToken);
        Assert.Empty((await other.GetFromJsonAsync<DeviceResponse[]>("api/v1/auth/devices"))!);
    }

    [ApiFact]
    public async Task Candidates_come_back_per_campaign_best_first()
    {
        var robot = await SeedRobotAsync();
        var campaignId = Guid.NewGuid();
        await using (var db = TestDb.Connect())
        {
            db.Campaigns.Add(new Campaign
            {
                Id = campaignId, Name = "c", Objective = "o", Weights = JsonDocument.Parse("{}"),
                Budget = JsonDocument.Parse("{}"), State = CampaignState.Active,
            });
            foreach (var fitness in new[] { 0.2m, 0.9m })
            {
                db.Candidates.Add(new Candidate
                {
                    CampaignId = campaignId, Generation = 1, GenomeId = $"genome-{robot[1..]}",
                    Operator = CandidateOperator.Mutation, Fitness = fitness,
                });
            }

            await db.SaveChangesAsync();
        }

        using var client = await AuthenticatedAsync(UserRole.Viewer);
        var rows = await client.GetFromJsonAsync<CandidateResponse[]>($"api/v1/campaigns/{campaignId}/candidates");
        Assert.Equal([0.9m, 0.2m], rows!.Select(r => r.Fitness!.Value));
    }

    [ApiFact]
    public async Task Qc_form_is_queued_for_the_lab_and_unknown_jobs_are_404()
    {
        var robot = await SeedRobotAsync();
        var jobId = Guid.NewGuid();
        await using (var db = TestDb.Connect())
        {
            var artifact = new Artifact
            {
                Id = Guid.NewGuid(), Kind = Enum.GetValues<ArtifactKind>()[0], Path = "a", Sha256 = "s",
                GenomeId = $"genome-{robot[1..]}", Generator = "manual",
            };
            db.Artifacts.Add(artifact);
            db.PrintJobs.Add(new PrintJob
            {
                Id = jobId, ArtifactId = artifact.Id, PrinterId = "p1", ProfileId = "petg", ApprovalId = Guid.NewGuid(),
                State = PrintJobState.Done,
            });
            await db.SaveChangesAsync();
        }

        using var client = await AuthenticatedAsync(UserRole.Operator);
        var form = new { dim_1_mm = 10.0, mass_g = 50.0, hole_gauge_ok = true };
        var queued = await client.PostAsJsonAsync($"api/v1/print-jobs/{jobId}/qc", form);
        Assert.Equal(HttpStatusCode.Accepted, queued.StatusCode);
        Assert.Equal(HttpStatusCode.NotFound,
            (await client.PostAsJsonAsync($"api/v1/print-jobs/{Guid.NewGuid()}/qc", form)).StatusCode);

        using var viewer = await AuthenticatedAsync(UserRole.Viewer);
        Assert.Equal(HttpStatusCode.Forbidden,
            (await viewer.PostAsJsonAsync($"api/v1/print-jobs/{jobId}/qc", form)).StatusCode);
    }

    // ---------- fixtures ----------

    /// <summary>A client whose token belongs to a real users row, which every queued write needs.</summary>
    private async Task<HttpClient> AuthenticatedAsync(UserRole role)
    {
        await using var db = TestDb.Connect();
        var user = new User
        {
            Id = Guid.NewGuid(),
            Email = $"{Guid.NewGuid():N}@neml.test",
            PasswordHash = "x",
            Role = role,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();

        var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(role, user.Id));
        return client;
    }

    private static async Task<string> SeedRobotAsync()
    {
        await using var db = TestDb.Connect();
        var id = Guid.NewGuid().ToString("N")[..12];
        db.Genomes.Add(new Genome
        {
            Id = $"genome-{id}",
            Name = $"genome-{id}",
            Version = 1,
            Hash = id,
            Status = GenomeStatus.Draft,
            Body = JsonDocument.Parse("{}"),
            Limits = JsonDocument.Parse("{}"),
            CreatedAt = DateTimeOffset.UtcNow,
        });
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

    private static async Task<Guid> SeedApprovalAsync(int level, DateTimeOffset? expiresAt = null)
    {
        await using var db = TestDb.Connect();
        var approval = new Approval
        {
            Id = Guid.NewGuid(),
            Level = level,
            SubjectKind = "task",
            SubjectId = Guid.NewGuid().ToString("N"),
            Payload = JsonDocument.Parse("""{"summary":"move"}"""),
            RequestedAt = DateTimeOffset.UtcNow,
            ExpiresAt = expiresAt ?? DateTimeOffset.UtcNow.AddHours(1),
        };
        db.Approvals.Add(approval);
        await db.SaveChangesAsync();
        return approval.Id;
    }
}
