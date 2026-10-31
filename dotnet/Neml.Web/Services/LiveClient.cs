// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.SignalR.Client;

namespace Neml.Web.Services;

/// <summary>
/// Owns the single §9.4 /hubs/live connection for the tab. Pages attach their own handlers
/// with <c>Hub.On&lt;T&gt;(...)</c> and dispose the returned subscription.
/// </summary>
/// <remarks>
/// ponytail: the global and approvals groups are joined by the hub itself at connect time —
/// §9.4 defines no client-to-server method for them, only SubscribeRobot/SubscribeCampaign.
/// If the hub ever stops auto-joining, add the explicit invoke here.
/// </remarks>
public sealed class LiveClient(TokenStore tokens, Uri baseAddress) : IAsyncDisposable
{
    private HubConnection? hub;

    public HubConnection Hub => hub ??= new HubConnectionBuilder()
        .WithUrl(new Uri(baseAddress, "hubs/live"), options =>
            options.AccessTokenProvider = () => Task.FromResult(tokens.Access))
        .WithAutomaticReconnect()
        .Build();

    public bool IsConnected => hub?.State == HubConnectionState.Connected;

    public async Task EnsureStartedAsync()
    {
        if (Hub.State == HubConnectionState.Disconnected)
        {
            await Hub.StartAsync();
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (hub is not null)
        {
            await hub.DisposeAsync();
        }
    }
}
