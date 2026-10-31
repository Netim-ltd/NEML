// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Collections.Concurrent;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.SignalR;

namespace Neml.Api.Hubs;

/// <summary>
/// /hubs/live (spec 9.4). Read only: the hub has no method that changes lab state,
/// commands go through CommandQueue over REST.
/// </summary>
[Authorize]
public sealed class LiveHub : Hub<ILiveClient>
{
    // ponytail: per-connection group memberships live in this process. Ceiling: a SignalR
    // backplane would be needed before running more than one API instance, and the
    // backplane also replaces this dictionary.
    private static readonly ConcurrentDictionary<string, ConcurrentDictionary<string, byte>> Subscriptions = new();

    public override async Task OnConnectedAsync()
    {
        Subscriptions[Context.ConnectionId] = new ConcurrentDictionary<string, byte>();
        await Groups.AddToGroupAsync(Context.ConnectionId, LiveGroups.Global);
        await Groups.AddToGroupAsync(Context.ConnectionId, LiveGroups.Approvals);
        await base.OnConnectedAsync();
    }

    public override async Task OnDisconnectedAsync(Exception? exception)
    {
        Subscriptions.TryRemove(Context.ConnectionId, out _);
        await base.OnDisconnectedAsync(exception);
    }

    public Task SubscribeRobot(string robotId) => Join(LiveGroups.Robot(robotId));

    public Task SubscribeCampaign(Guid campaignId) => Join(LiveGroups.Campaign(campaignId));

    public async Task UnsubscribeAll()
    {
        if (!Subscriptions.TryGetValue(Context.ConnectionId, out var groups))
        {
            return;
        }

        foreach (var group in groups.Keys)
        {
            await Groups.RemoveFromGroupAsync(Context.ConnectionId, group);
            groups.TryRemove(group, out _);
        }
    }

    private async Task Join(string group)
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, group);
        Subscriptions.GetOrAdd(Context.ConnectionId, _ => new ConcurrentDictionary<string, byte>())[group] = 0;
    }
}
