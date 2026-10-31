// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.SignalR;
using Neml.Api.Hubs;

namespace Neml.Tests;

/// <summary>Records what LiveBroadcaster sends, and to which §9.4 groups.</summary>
public sealed class RecordingHubContext : IHubContext<LiveHub, ILiveClient>
{
    public List<(IReadOnlyList<string> Groups, string Event, object Payload)> Sent { get; } = [];

    public IHubClients<ILiveClient> Clients => new Router(this);

    public IGroupManager Groups => throw new NotSupportedException("LiveBroadcaster must not manage groups.");

    private void Record(IReadOnlyList<string> groups, string name, object payload) => Sent.Add((groups, name, payload));

    private sealed class Router(RecordingHubContext owner) : IHubClients<ILiveClient>
    {
        public ILiveClient All => new Recorder(owner, ["*all*"]);

        public ILiveClient AllExcept(IReadOnlyList<string> excludedConnectionIds) => All;

        public ILiveClient Client(string connectionId) => new Recorder(owner, [$"connection:{connectionId}"]);

        public ILiveClient Clients(IReadOnlyList<string> connectionIds) => new Recorder(owner, [.. connectionIds]);

        public ILiveClient Group(string groupName) => new Recorder(owner, [groupName]);

        public ILiveClient Groups(IReadOnlyList<string> groupNames) => new Recorder(owner, [.. groupNames]);

        public ILiveClient GroupExcept(string groupName, IReadOnlyList<string> excludedConnectionIds) => Group(groupName);

        public ILiveClient User(string userId) => new Recorder(owner, [$"user:{userId}"]);

        public ILiveClient Users(IReadOnlyList<string> userIds) => new Recorder(owner, [.. userIds]);
    }

    private sealed class Recorder(RecordingHubContext owner, IReadOnlyList<string> groups) : ILiveClient
    {
        public Task RobotState(RobotStatePayload payload) => Send(nameof(RobotState), payload);

        public Task TelemetryTick(TelemetryTickPayload payload) => Send(nameof(TelemetryTick), payload);

        public Task TaskUpdated(TaskUpdatedPayload payload) => Send(nameof(TaskUpdated), payload);

        public Task TaskRunEvent(TaskRunEventPayload payload) => Send(nameof(TaskRunEvent), payload);

        public Task CampaignProgress(CampaignProgressPayload payload) => Send(nameof(CampaignProgress), payload);

        public Task ApprovalRequested(ApprovalRequestedPayload payload) => Send(nameof(ApprovalRequested), payload);

        public Task ApprovalDecided(ApprovalDecidedPayload payload) => Send(nameof(ApprovalDecided), payload);

        public Task PrintProgress(PrintProgressPayload payload) => Send(nameof(PrintProgress), payload);

        public Task BrainStatus(BrainStatusPayload payload) => Send(nameof(BrainStatus), payload);

        public Task Alert(AlertPayload payload) => Send(nameof(Alert), payload);

        private Task Send(string name, object payload)
        {
            owner.Record(groups, name, payload);
            return Task.CompletedTask;
        }
    }
}
