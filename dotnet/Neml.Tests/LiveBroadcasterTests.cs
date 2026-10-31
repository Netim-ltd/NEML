// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Neml.Api.Hubs;
using Neml.Api.Services;

namespace Neml.Tests;

/// <summary>T-053 — §9.4 group routing, the 1 Hz TelemetryTick throttle and event relay.</summary>
public sealed class LiveBroadcasterTests
{
    private readonly RecordingHubContext hub = new();
    private readonly LiveBroadcaster broadcaster;

    public LiveBroadcasterTests()
    {
        // No FCM credentials are configured, so PushNotifier is inert and the §10.4 triggers
        // cannot reach out of the test.
        var services = new ServiceCollection().BuildServiceProvider();
        var push = new PushNotifier(
            services.GetRequiredService<IServiceScopeFactory>(),
            new ConfigurationBuilder().Build(),
            NullLogger<PushNotifier>.Instance);

        broadcaster = new LiveBroadcaster(hub, push, new LabState(), NullLogger<LiveBroadcaster>.Instance);
    }

    [Fact]
    public async Task RobotState_reaches_the_robot_and_global_groups()
    {
        await broadcaster.RobotStateAsync(new RobotStatePayload("R01", "idle", 0.9m, DateTimeOffset.UtcNow));

        var sent = Assert.Single(hub.Sent);
        Assert.Equal(nameof(ILiveClient.RobotState), sent.Event);
        Assert.Equal(new[] { "robot:R01", "global" }, sent.Groups);
    }

    [Fact]
    public async Task TaskUpdated_reaches_the_global_group_only()
    {
        await broadcaster.TaskUpdatedAsync(new TaskUpdatedPayload(Guid.NewGuid(), "running", 0.5, null));

        var sent = Assert.Single(hub.Sent);
        Assert.Equal(new[] { "global" }, sent.Groups);
    }

    [Fact]
    public async Task Approval_events_reach_the_approvals_group_only()
    {
        var id = Guid.NewGuid();

        await broadcaster.ApprovalRequestedAsync(
            new ApprovalRequestedPayload(id, 2, "print:bracket", DateTimeOffset.UtcNow.AddHours(24), null));
        await broadcaster.ApprovalDecidedAsync(new ApprovalDecidedPayload(id, "approved", "user:mg"));

        Assert.Equal(2, hub.Sent.Count);
        Assert.All(hub.Sent, s => Assert.Equal(new[] { "approvals" }, s.Groups));
    }

    [Fact]
    public async Task CampaignProgress_reaches_the_campaign_and_global_groups()
    {
        var id = Guid.NewGuid();

        await broadcaster.CampaignProgressAsync(new CampaignProgressPayload(id, 3, 0.81m, 0.62m, 20));

        var sent = Assert.Single(hub.Sent);
        Assert.Equal(new[] { $"campaign:{id}", "global" }, sent.Groups);
    }

    [Fact]
    public async Task TelemetryTick_is_throttled_to_one_per_second_per_robot()
    {
        for (var i = 0; i < 20; i++)
        {
            await broadcaster.TelemetryTickAsync(Tick("R01"));
        }

        Assert.Single(hub.Sent);

        // A second robot has its own budget.
        await broadcaster.TelemetryTickAsync(Tick("R02"));
        Assert.Equal(2, hub.Sent.Count);

        // Past the window the next sample goes out again.
        await Task.Delay(TimeSpan.FromMilliseconds(1100));
        await broadcaster.TelemetryTickAsync(Tick("R01"));
        Assert.Equal(3, hub.Sent.Count);
        Assert.Equal(new[] { "robot:R01" }, hub.Sent[^1].Groups);
    }

    [Fact]
    public async Task The_throttle_holds_when_several_publishers_push_at_once()
    {
        // §9.4 fixes TelemetryTick at 1 Hz. The lab can push from more than one place at a
        // time, so the budget has to be spent atomically rather than read then written.
        await Parallel.ForEachAsync(
            Enumerable.Range(0, 64),
            async (_, _) => await broadcaster.TelemetryTickAsync(Tick("R-parallel")));

        Assert.Single(hub.Sent);
        Assert.Equal(new[] { "robot:R-parallel" }, hub.Sent[0].Groups);
    }

    [Fact]
    public async Task TelemetryTick_never_reaches_the_global_group()
    {
        await broadcaster.TelemetryTickAsync(Tick("R01"));

        // A tick is the loudest stream there is; §9.4 gives it the robot group alone, so a
        // dashboard watching one robot cannot be flooded by the rest of the fleet.
        Assert.DoesNotContain(hub.Sent, s => s.Groups.Contains("global"));
    }

    [Fact]
    public async Task A_robot_fault_is_pushed_but_an_idle_robot_is_not()
    {
        // §10.4 wakes the phone for fault and estop only. PushNotifier is inert here, so what
        // is asserted is the branch being taken and the event still reaching its §9.4 groups.
        foreach (var state in (string[])["idle", "running", "fault", "estop", "charging"])
        {
            await broadcaster.RobotStateAsync(new RobotStatePayload("R01", state, 0.5m, null));
        }

        Assert.Equal(5, hub.Sent.Count);
        Assert.All(hub.Sent, s => Assert.Equal(new[] { "robot:R01", "global" }, s.Groups));
    }

    [Fact]
    public async Task A_task_is_only_pushed_once_it_has_failed_three_times()
    {
        var id = Guid.NewGuid();

        await broadcaster.TaskRunEventAsync(new TaskRunEventPayload(id, 1, "sim", "failure", "walk"));
        await broadcaster.TaskRunEventAsync(new TaskRunEventPayload(id, 3, "sim", "success", "walk"));
        await broadcaster.TaskRunEventAsync(new TaskRunEventPayload(id, 3, "sim", "failure", "walk"));

        Assert.Equal(3, hub.Sent.Count);
        Assert.All(hub.Sent, s => Assert.Equal(new[] { "global" }, s.Groups));
    }

    [Fact]
    public async Task Only_a_level_three_or_four_approval_wakes_the_phone()
    {
        foreach (var level in (int[])[1, 2, 3, 4])
        {
            await broadcaster.ApprovalRequestedAsync(new ApprovalRequestedPayload(
                Guid.NewGuid(), level, $"print:{level}", DateTimeOffset.UtcNow.AddHours(24), null));
        }

        Assert.Equal(4, hub.Sent.Count);
        Assert.All(hub.Sent, s => Assert.Equal(new[] { "approvals" }, s.Groups));
    }

    [Fact]
    public async Task A_finished_print_is_announced_once_however_often_100_percent_is_reported()
    {
        var job = Guid.NewGuid();

        await broadcaster.PrintProgressAsync(new PrintProgressPayload(job, 99, 210, 2, 215, 60));
        await broadcaster.PrintProgressAsync(new PrintProgressPayload(job, 100, 212, 0, 215, 60));
        await broadcaster.PrintProgressAsync(new PrintProgressPayload(job, 100, 212, 0, 40, 25));

        // Every sample is still broadcast; it is the §10.4 push that must not repeat.
        Assert.Equal(3, hub.Sent.Count);
        Assert.All(hub.Sent, s => Assert.Equal(new[] { "global" }, s.Groups));
    }

    [Fact]
    public async Task The_budget_warning_fires_on_the_crossing_not_on_every_report()
    {
        foreach (var used in (decimal[])[0.5m, 0.89m, 0.90m, 0.95m, 0.2m, 0.99m])
        {
            await broadcaster.BrainStatusAsync(new BrainStatusPayload(true, "qwen", "llm", used));
        }

        Assert.Equal(6, hub.Sent.Count);
        Assert.All(hub.Sent, s => Assert.Equal(new[] { "global" }, s.Groups));
    }

    [Fact]
    public async Task A_campaign_completed_alert_is_the_only_alert_that_is_pushed()
    {
        await broadcaster.AlertAsync(new AlertPayload("warning", "gpu_busy", "vLLM durduruldu"));
        await broadcaster.AlertAsync(new AlertPayload("info", "campaign_completed", "gen 4 bitti"));

        Assert.Equal(2, hub.Sent.Count);
        Assert.All(hub.Sent, s => Assert.Equal(new[] { "global" }, s.Groups));
    }

    [Fact]
    public async Task Every_spec_9_4_event_relays_from_the_bridge()
    {
        var names = typeof(ILiveClient).GetMethods().Select(m => m.Name).ToArray();
        Assert.Equal(10, names.Length);

        foreach (var name in names)
        {
            Assert.True(await broadcaster.DispatchAsync(name, Payload(name)), $"{name} relayed nothing.");
        }

        // One event in, one event out: nothing is dropped on the way through.
        Assert.Equal(names.Length, hub.Sent.Count);
        Assert.Equal(names.Order().ToArray(), hub.Sent.Select(s => s.Event).Order().ToArray());
    }

    [Fact]
    public async Task An_unknown_event_name_is_dropped()
    {
        Assert.False(await broadcaster.DispatchAsync("DropTheTable", Json("{}")));
        Assert.Empty(hub.Sent);
    }

    [Fact]
    public async Task A_malformed_payload_is_dropped()
    {
        Assert.False(await broadcaster.DispatchAsync(nameof(ILiveClient.RobotState), Json("\"not an object\"")));
        Assert.Empty(hub.Sent);
    }

    private static TelemetryTickPayload Tick(string robotId) =>
        new(robotId, new Dictionary<string, double> { ["battery_v"] = 24.1 }, DateTimeOffset.UtcNow);

    private static JsonElement Payload(string eventName) => Json(eventName switch
    {
        nameof(ILiveClient.RobotState) => """{"robotId":"R01","state":"idle","batterySoc":0.9,"lastSeen":null}""",
        nameof(ILiveClient.TelemetryTick) => """{"robotId":"R01","metrics":{"battery_v":24.1},"ts":"2026-09-15T10:00:00Z"}""",
        nameof(ILiveClient.TaskUpdated) => $$"""{"taskId":"{{Guid.NewGuid()}}","state":"running","progress":0.4,"message":null}""",
        nameof(ILiveClient.TaskRunEvent) => $$"""{"taskId":"{{Guid.NewGuid()}}","attempt":1,"env":"sim","outcome":null,"step":"plan"}""",
        nameof(ILiveClient.CampaignProgress) => $$"""{"campaignId":"{{Guid.NewGuid()}}","generation":1,"best":0.5,"mean":0.3,"candidatesDone":4}""",
        nameof(ILiveClient.ApprovalRequested) => $$"""{"approvalId":"{{Guid.NewGuid()}}","level":2,"subject":"task","expiresAt":"2026-09-16T10:00:00Z","previewUrl":null}""",
        nameof(ILiveClient.ApprovalDecided) => $$"""{"approvalId":"{{Guid.NewGuid()}}","decision":"approved","by":"user:mg"}""",
        nameof(ILiveClient.PrintProgress) => $$"""{"jobId":"{{Guid.NewGuid()}}","pct":12.5,"layer":8,"etaMin":90,"nozzleC":215,"bedC":60}""",
        nameof(ILiveClient.BrainStatus) => """{"online":true,"model":"qwen","gpuOwner":"llm","budgetUsed":0.1}""",
        nameof(ILiveClient.Alert) => """{"severity":"warning","code":"gpu_busy","message":"vLLM durduruldu"}""",
        _ => throw new ArgumentOutOfRangeException(nameof(eventName), eventName, "§9.4 has no such event."),
    });

    private static JsonElement Json(string payload) => JsonDocument.Parse(payload).RootElement.Clone();
}
