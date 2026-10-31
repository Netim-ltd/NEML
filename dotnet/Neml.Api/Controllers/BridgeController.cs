// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net.WebSockets;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Neml.Api.Auth;
using Neml.Api.Bridge;
using Neml.Domain.Dtos;
using Neml.Infrastructure.Repositories;

namespace Neml.Api.Controllers;

/// <summary>
/// Spec 9.5, lab side only. Every route here uses the bridge API key scheme, so no user token
/// can reach them and the bridge holds no user role. The server never opens a connection
/// towards the lab: /bridge/ws only ever answers a dial the lab made (spec 3.1).
/// </summary>
[ApiController]
[Route("bridge")]
[Tags("Bridge")]
[Authorize(Policy = Policies.Bridge)]
[DisableRateLimiting]
[Produces("application/json")]
[ProducesResponseType(StatusCodes.Status401Unauthorized)]
public sealed class BridgeController(
    BridgeSession session, TelemetryRepository telemetry) : ControllerBase
{
    private string Node => User.FindFirst(BridgeAuthenticationHandler.NodeClaim)?.Value ?? "unknown";

    /// <summary>The persistent WSS link of spec 9.5, with permessage-deflate.</summary>
    [HttpGet("ws")]
    [ProducesResponseType(StatusCodes.Status101SwitchingProtocols)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> Socket()
    {
        if (!HttpContext.WebSockets.IsWebSocketRequest)
        {
            return Problem("websocket upgrade required", statusCode: StatusCodes.Status400BadRequest);
        }

        using var socket = await HttpContext.WebSockets.AcceptWebSocketAsync(
            new WebSocketAcceptContext { DangerousEnableCompression = true });

        await session.RunAsync(socket, Node, HttpContext.RequestAborted);
        return new EmptyResult();
    }

    /// <summary>The lab stores one recording (a GIF of a simulation run) for the panel to show.</summary>
    [HttpPut("media/{name}")]
    [RequestSizeLimit(MediaStore.MaxBytes)]
    [ProducesResponseType<MediaStored>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<MediaStored>> PutMedia(
        string name, [FromServices] IConfiguration configuration, CancellationToken ct)
    {
        if (!MediaStore.IsValidName(name))
        {
            return Problem("media name must be 24 hex characters and .gif or .png", statusCode: StatusCodes.Status400BadRequest);
        }

        var directory = MediaStore.Directory(configuration);
        Directory.CreateDirectory(directory);
        await using var file = System.IO.File.Create(Path.Combine(directory, name));
        await Request.Body.CopyToAsync(file, ct);
        return new MediaStored($"/api/v1/media/{name}");
    }

    /// <summary>Catch-up path for telemetry the lab buffered while offline (spec 3.1).</summary>
    [HttpPost("telemetry/batch")]
    [ProducesResponseType<BridgeAckResponse>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<BridgeAckResponse>> TelemetryBatch(
        TelemetryBatchRequest request, CancellationToken ct)
    {
        var written = await telemetry.InsertBatchAsync(request.Samples, ct);
        return Accepted(new BridgeAckResponse(written, request.Samples.Count - written));
    }

    /// <summary>
    /// Catch-up path for buffered lab envelopes. Each one goes through the same seq and
    /// idempotency guards as the socket, so a replay after a reconnect changes nothing.
    /// </summary>
    [HttpPost("events")]
    [ProducesResponseType<BridgeAckResponse>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<BridgeAckResponse>> Events(BridgeEventsRequest request, CancellationToken ct)
    {
        var accepted = 0;
        foreach (var envelope in request.Events)
        {
            if (await session.AcceptAsync(envelope, Node, ct))
            {
                accepted++;
            }
        }

        return Accepted(new BridgeAckResponse(accepted, request.Events.Count - accepted));
    }
}

/// <summary>Where a stored recording can be read.</summary>
public record MediaStored(string Url);
