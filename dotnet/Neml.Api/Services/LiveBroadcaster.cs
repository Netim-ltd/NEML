// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.AspNetCore.SignalR;
using Neml.Api.Hubs;

namespace Neml.Api.Services;

/// <summary>
/// Single funnel for the ten spec 9.4 events: picks the groups, throttles telemetry and fires
/// the spec 10.4 push triggers. Nothing else in the API touches IHubContext.
/// </summary>
public sealed class LiveBroadcaster(
    IHubContext<LiveHub, ILiveClient> hub,
    PushNotifier push,
    LabState lab,
    ILogger<LiveBroadcaster> log)
{
    /// <summary>Spec 9.4: TelemetryTick is 1 Hz. Enforced here, never trusted from the publisher.</summary>
    private static readonly long TickIntervalTicks = TimeSpan.FromSeconds(1).Ticks;

    private const string CampaignCompletedCode = "campaign_completed";

    private readonly ConcurrentDictionary<string, long> _lastTick = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<Guid, byte> _printFinished = new();
    private decimal _lastBudgetUsed;

    public async Task RobotStateAsync(RobotStatePayload payload, CancellationToken ct = default)
    {
        await hub.Clients.Groups(LiveGroups.Robot(payload.RobotId), LiveGroups.Global).RobotState(payload);

        if (payload.State is "fault" or "estop")
        {
            await push.NotifyAsync(
                PushTrigger.RobotFault,
                $"{payload.RobotId} durumu: {payload.State}",
                "Robot güvenli duruma geçti, müdahale gerekebilir.",
                ct);
        }
    }

    public Task TelemetryTickAsync(TelemetryTickPayload payload)
    {
        var now = DateTimeOffset.UtcNow.UtcTicks;
        var previous = _lastTick.GetOrAdd(payload.RobotId, 0);
        if (now - previous < TickIntervalTicks || !_lastTick.TryUpdate(payload.RobotId, now, previous))
        {
            return Task.CompletedTask;
        }

        return hub.Clients.Group(LiveGroups.Robot(payload.RobotId)).TelemetryTick(payload);
    }

    public Task TaskUpdatedAsync(TaskUpdatedPayload payload) =>
        hub.Clients.Group(LiveGroups.Global).TaskUpdated(payload);

    public async Task TaskRunEventAsync(TaskRunEventPayload payload, CancellationToken ct = default)
    {
        await hub.Clients.Group(LiveGroups.Global).TaskRunEvent(payload);

        if (payload is { Outcome: "failure", Attempt: >= 3 })
        {
            await push.NotifyAsync(
                PushTrigger.TaskFailed,
                "Görev başarısız",
                $"{payload.TaskId} görevi {payload.Attempt}. denemede de başarısız oldu.",
                ct);
        }
    }

    // A connection in both named groups still receives one copy: SignalR fans a multi group
    // send out per connection, not per group.
    public Task CampaignProgressAsync(CampaignProgressPayload payload) =>
        hub.Clients.Groups(LiveGroups.Campaign(payload.CampaignId), LiveGroups.Global).CampaignProgress(payload);

    public async Task ApprovalRequestedAsync(ApprovalRequestedPayload payload, CancellationToken ct = default)
    {
        await hub.Clients.Group(LiveGroups.Approvals).ApprovalRequested(payload);

        // Spec 10.4: only levels 3 and 4 wake the phone.
        if (payload.Level >= 3)
        {
            await push.NotifyAsync(
                PushTrigger.ApprovalRequested,
                $"Onay bekleniyor (seviye {payload.Level})",
                payload.Subject,
                ct);
        }
    }

    public Task ApprovalDecidedAsync(ApprovalDecidedPayload payload) =>
        hub.Clients.Group(LiveGroups.Approvals).ApprovalDecided(payload);

    public async Task PrintProgressAsync(PrintProgressPayload payload, CancellationToken ct = default)
    {
        lab.SetPrintProgress(payload);
        await hub.Clients.Group(LiveGroups.Global).PrintProgress(payload);

        if (payload.Pct >= 100 && _printFinished.TryAdd(payload.JobId, 0))
        {
            await push.NotifyAsync(PushTrigger.PrintFinished, "Baskı bitti", payload.JobId.ToString(), ct);
        }
    }

    public async Task BrainStatusAsync(BrainStatusPayload payload, CancellationToken ct = default)
    {
        lab.SetBrain(payload);
        await hub.Clients.Group(LiveGroups.Global).BrainStatus(payload);

        var crossed = payload.BudgetUsed >= 0.9m && _lastBudgetUsed < 0.9m;
        _lastBudgetUsed = payload.BudgetUsed;
        if (crossed)
        {
            await push.NotifyAsync(
                PushTrigger.BudgetWarning,
                "Bütçe uyarısı",
                $"Günlük bütçenin %{payload.BudgetUsed * 100:F0} kadarı kullanıldı.",
                ct);
        }
    }

    public async Task AlertAsync(AlertPayload payload, CancellationToken ct = default)
    {
        await hub.Clients.Group(LiveGroups.Global).Alert(payload);

        // Spec 9.4 carries no campaign completion event, so the lab signals it as an alert.
        if (payload.Code == CampaignCompletedCode)
        {
            await push.NotifyAsync(PushTrigger.CampaignCompleted, "Kampanya tamamlandı", payload.Message, ct);
        }
    }

    /// <summary>
    /// Relays one event that arrived from the lab. Only the ten spec 9.4 names are accepted
    /// and a malformed payload is dropped, so the bridge cannot invent a client method.
    /// </summary>
    public async Task<bool> DispatchAsync(string name, JsonElement data, CancellationToken ct = default)
    {
        try
        {
            switch (name)
            {
                case nameof(ILiveClient.RobotState):
                    await RobotStateAsync(Read<RobotStatePayload>(data), ct);
                    return true;
                case nameof(ILiveClient.TelemetryTick):
                    await TelemetryTickAsync(Read<TelemetryTickPayload>(data));
                    return true;
                case nameof(ILiveClient.TaskUpdated):
                    await TaskUpdatedAsync(Read<TaskUpdatedPayload>(data));
                    return true;
                case nameof(ILiveClient.TaskRunEvent):
                    await TaskRunEventAsync(Read<TaskRunEventPayload>(data), ct);
                    return true;
                case nameof(ILiveClient.CampaignProgress):
                    await CampaignProgressAsync(Read<CampaignProgressPayload>(data));
                    return true;
                case nameof(ILiveClient.ApprovalRequested):
                    await ApprovalRequestedAsync(Read<ApprovalRequestedPayload>(data), ct);
                    return true;
                case nameof(ILiveClient.ApprovalDecided):
                    await ApprovalDecidedAsync(Read<ApprovalDecidedPayload>(data));
                    return true;
                case nameof(ILiveClient.PrintProgress):
                    await PrintProgressAsync(Read<PrintProgressPayload>(data), ct);
                    return true;
                case nameof(ILiveClient.BrainStatus):
                    await BrainStatusAsync(Read<BrainStatusPayload>(data), ct);
                    return true;
                case nameof(ILiveClient.Alert):
                    await AlertAsync(Read<AlertPayload>(data), ct);
                    return true;
                default:
                    log.LogWarning("Unknown live event {Name} from the lab; dropped.", name);
                    return false;
            }
        }
        catch (JsonException ex)
        {
            log.LogWarning(ex, "Malformed payload for live event {Name}; dropped.", name);
            return false;
        }
    }

    private static T Read<T>(JsonElement data) =>
        data.Deserialize<T>(JsonSerializerOptions.Web) ?? throw new JsonException($"Empty {typeof(T).Name}.");
}
