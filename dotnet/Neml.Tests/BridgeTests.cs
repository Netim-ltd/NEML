// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.TestHost;
using Neml.Api.Auth;
using Neml.Api.Bridge;
using Neml.Api.Hubs;
using Neml.Api.Services;
using Neml.Domain.Dtos;
using Neml.Domain.Enums;

namespace Neml.Tests;

/// <summary>
/// §5.5 bridge authentication and the §9.5 catch-up endpoints. The key, the node header and the
/// address allow list are the whole gate between the public internet and the lab, so each one is
/// checked on its own, and the §3.1 replay guard is checked on the events path it protects.
/// </summary>
public sealed class BridgeTests : IDisposable
{
    private readonly ApiFactory factory = new();

    public void Dispose() => factory.Dispose();

    private static BridgeEnvelope Envelope(long seq, string key, string robot) => new(
        1,
        seq,
        DateTimeOffset.UtcNow,
        BridgeMessage.Telemetry,
        key,
        JsonDocument.Parse(
            $$"""
            {"samples":[{"ts":"{{DateTimeOffset.UtcNow:O}}","robotId":"{{robot}}",
            "metric":"battery_soc","value":42,"tags":null}]}
            """));

    private HttpClient BridgeClient(string? key = ApiFactory.BridgeKey, string? node = ApiFactory.BridgeNode)
    {
        var client = factory.CreateClient();
        if (key is not null)
        {
            client.DefaultRequestHeaders.Add(BridgeAuthenticationHandler.KeyHeader, key);
        }

        if (node is not null)
        {
            client.DefaultRequestHeaders.Add(BridgeAuthenticationHandler.NodeHeader, node);
        }

        return client;
    }

    [ApiFact]
    public async Task The_bridge_gate_refuses_everything_but_the_configured_key_and_node()
    {
        var batch = new TelemetryBatchRequest([new TelemetrySample(DateTimeOffset.UtcNow, "R01", "m", 1, null)]);

        using var anonymous = factory.CreateClient();
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await anonymous.PostAsJsonAsync("bridge/telemetry/batch", batch)).StatusCode);

        using var wrongKey = BridgeClient(key: "not-the-key");
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await wrongKey.PostAsJsonAsync("bridge/telemetry/batch", batch)).StatusCode);

        using var noNode = BridgeClient(node: null);
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await noNode.PostAsJsonAsync("bridge/telemetry/batch", batch)).StatusCode);

        using var unknownNode = BridgeClient(node: "lab-99");
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await unknownNode.PostAsJsonAsync("bridge/telemetry/batch", batch)).StatusCode);

        // A user token grants no bridge rights, however senior the role (§5.5).
        using var owner = factory.CreateClient();
        owner.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(UserRole.Owner));
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await owner.PostAsJsonAsync("bridge/telemetry/batch", batch)).StatusCode);
    }

    [ApiFact]
    public async Task An_address_outside_the_allow_list_is_refused()
    {
        using var restricted = factory.WithWebHostBuilder(
            builder => builder.UseSetting("Bridge:AllowedIps:0", "203.0.113.7"));
        using var client = restricted.CreateClient();
        client.DefaultRequestHeaders.Add(BridgeAuthenticationHandler.KeyHeader, ApiFactory.BridgeKey);
        client.DefaultRequestHeaders.Add(BridgeAuthenticationHandler.NodeHeader, ApiFactory.BridgeNode);

        var response = await client.PostAsJsonAsync(
            "bridge/telemetry/batch",
            new TelemetryBatchRequest([new TelemetrySample(DateTimeOffset.UtcNow, "R01", "m", 1, null)]));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [ApiFact]
    public async Task A_buffered_telemetry_batch_is_written_once()
    {
        var robot = $"R{Guid.NewGuid():N}"[..12];
        using var client = BridgeClient();

        var response = await client.PostAsJsonAsync("bridge/telemetry/batch", new TelemetryBatchRequest(
        [
            new TelemetrySample(DateTimeOffset.UtcNow, robot, "battery_soc", 41, null),
            new TelemetrySample(DateTimeOffset.UtcNow, robot, "battery_soc", 42, null),
        ]));

        Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);
        var ack = await response.Content.ReadFromJsonAsync<BridgeAckResponse>();
        Assert.Equal(2, ack!.Accepted);
        Assert.Equal(0, ack.Ignored);
    }

    [ApiFact]
    public async Task A_replayed_envelope_is_ignored_rather_than_applied_twice()
    {
        var robot = $"R{Guid.NewGuid():N}"[..12];
        var key = Guid.NewGuid().ToString("N");
        var seq = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        using var client = BridgeClient();

        var first = await client.PostAsJsonAsync(
            "bridge/events", new BridgeEventsRequest([Envelope(seq, key, robot)]));
        Assert.Equal(HttpStatusCode.Accepted, first.StatusCode);
        Assert.Equal(1, (await first.Content.ReadFromJsonAsync<BridgeAckResponse>())!.Accepted);

        // §3.1: the same key, and a seq that does not move forward, are both dropped.
        var replay = await client.PostAsJsonAsync("bridge/events", new BridgeEventsRequest(
        [
            Envelope(seq, key, robot),
            Envelope(seq - 1, Guid.NewGuid().ToString("N"), robot),
        ]));
        var ack = await replay.Content.ReadFromJsonAsync<BridgeAckResponse>();
        Assert.Equal(0, ack!.Accepted);
        Assert.Equal(2, ack.Ignored);
    }

    [ApiFact]
    public async Task The_websocket_route_refuses_a_plain_get()
    {
        using var client = BridgeClient();

        using var response = await client.GetAsync("bridge/ws");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    // ---------- §3.1 replay guard, on its own ----------

    [Fact]
    public void Lab_state_accepts_a_node_envelope_once_and_only_moving_forward()
    {
        var lab = new LabState();

        Assert.True(lab.TryAccept("lab-01", 1, "k1"));
        Assert.False(lab.TryAccept("lab-01", 1, "k2"));      // seq must increase.
        Assert.False(lab.TryAccept("lab-01", 0, "k3"));      // seq is 1 based.
        Assert.False(lab.TryAccept("lab-01", 2, ""));        // the key is what makes a replay free.
        Assert.True(lab.TryAccept("lab-01", 2, "k4"));
        Assert.False(lab.TryAccept("lab-01", 3, "k4"));      // the key was already used.

        // Another node keeps its own counter.
        Assert.True(lab.TryAccept("lab-02", 1, "k5"));
    }

    [Fact]
    public void Brain_is_offline_whenever_the_bridge_is_down()
    {
        var lab = new LabState();

        Assert.False(lab.Status().Online);
        Assert.Null(lab.LastSeen);

        lab.SetBrain(new BrainStatusPayload(true, "qwen", "brain", 0.25m));
        Assert.False(lab.Status().Online);                   // The lab says yes, the link says no.

        lab.SetBridgeConnected(true);
        var status = lab.Status();
        Assert.True(status.Online);
        Assert.Equal("qwen", status.Model);
        Assert.Equal(0.25m, status.BudgetUsed);
        Assert.NotNull(lab.LastSeen);

        var seen = lab.LastSeen;
        lab.Touch();
        Assert.True(lab.LastSeen >= seen);

        lab.SetBridgeConnected(false);
        Assert.False(lab.Status().Online);
    }

    [Fact]
    public void Printer_status_is_the_last_progress_the_lab_pushed()
    {
        var lab = new LabState();
        var job = Guid.NewGuid();

        var unknown = lab.PrinterStatus("prusa-1", null);
        Assert.False(unknown.Online);
        Assert.Null(unknown.Pct);

        Assert.Null(lab.PrinterStatus("prusa-1", Guid.NewGuid()).State);

        lab.SetBridgeConnected(true);
        lab.SetPrintProgress(new PrintProgressPayload(job, 42, 7, 12, 215, 60));

        var status = lab.PrinterStatus("prusa-1", job);
        Assert.True(status.Online);
        Assert.Equal("printing", status.State);
        Assert.Equal(42, status.Pct);
        Assert.Equal(215, status.NozzleC);
    }
}
