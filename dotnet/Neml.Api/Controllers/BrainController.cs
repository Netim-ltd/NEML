// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Neml.Api.Auth;
using Neml.Api.Contracts;
using Neml.Api.Hubs;
using Neml.Api.Services;
using Neml.Domain.Dtos;

namespace Neml.Api.Controllers;

/// <summary>
/// Spec 9.3 Brain. No model runs here: the text is queued, the lab picks it up and
/// neml-brain classifies it under the constrained generation rules of spec 4.3.
/// </summary>
[Route("api/v1/brain")]
[Tags("Brain")]
public sealed class BrainController(CommandQueue queue, LabState lab) : NemlController
{
    /// <summary>Queues a natural language command and answers with its command_id.</summary>
    [HttpPost("command")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Command(BrainCommandRequest request, CancellationToken ct)
    {
        // Spec 5.4: user text is untrusted input. It is stored and forwarded verbatim and is
        // never read as an instruction by anything in this process.
        var payload = JsonSerializer.Serialize(new { text = request.Text }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.BrainCommand, payload, IdempotencyKey(), ct));
    }

    /// <summary>How a queued command ended up: delivered, applied, failed or rejected.</summary>
    [HttpGet("command/{id:guid}")]
    [ProducesResponseType<CommandDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<CommandDto>> CommandStatus(Guid id, CancellationToken ct)
    {
        var command = await queue.GetAsync(id, ct);
        return command is null ? NotFound() : command;
    }

    /// <summary>Brain liveness, model and GPU owner. Offline whenever the bridge is down.</summary>
    [HttpGet("status")]
    [ProducesResponseType<BrainStatusPayload>(StatusCodes.Status200OK)]
    public ActionResult<BrainStatusPayload> Status() => lab.Status();
}
