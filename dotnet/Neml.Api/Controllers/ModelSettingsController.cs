// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Security.Claims;
using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.IdentityModel.JsonWebTokens;
using Neml.Api.Auth;
using Neml.Api.Contracts;
using Neml.Api.Services;

namespace Neml.Api.Controllers;

/// <summary>
/// The admin screen's per-model and lab-wide settings (MTBF, filament prices, ...). The values
/// live in the lab database, so this server holds nothing: a read or a write is a queued
/// command, and the lab answers with a command_ack whose result is the field catalogue
/// (required / recommended, ranges, current values). The client polls
/// GET /api/v1/brain/command/{id} for it, like every other lab round trip (spec 3.1).
/// </summary>
[Route("api/v1/model-settings")]
[Tags("ModelSettings")]
public sealed class ModelSettingsController(CommandQueue queue) : NemlController
{
    public const string Get = "model_settings.get";
    public const string Put = "model_settings.put";

    /// <summary>Every model and how many required fields are still open. "_lab" is the lab-wide set.</summary>
    [HttpGet]
    [Authorize(Policy = Policies.Operator)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> List(CancellationToken ct) =>
        Accepted(await queue.EnqueueAsync(UserId, Get, "{}", Guid.NewGuid().ToString("N"), ct));

    /// <summary>The field catalogue of one model with its current values.</summary>
    [HttpGet("{modelId}")]
    [Authorize(Policy = Policies.Operator)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Read(string modelId, CancellationToken ct) =>
        Accepted(await queue.EnqueueAsync(
            UserId, Get, JsonSerializer.Serialize(new { modelId }, JsonSerializerOptions.Web),
            Guid.NewGuid().ToString("N"), ct));

    /// <summary>Owner only. A null value clears a field; the lab validates ranges and answers in the ack.</summary>
    [HttpPut("{modelId}")]
    [Authorize(Policy = Policies.Owner)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Write(
        string modelId, ModelSettingsRequest request, CancellationToken ct)
    {
        var by = User.FindFirstValue(JwtRegisteredClaimNames.Email) ?? UserId.ToString();
        var payload = JsonSerializer.Serialize(
            new { modelId, values = request.Values, by }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, Put, payload, IdempotencyKey(), ct));
    }
}

/// <summary>PUT /model-settings/{modelId}: field key to number, or null to clear it.</summary>
public record ModelSettingsRequest(Dictionary<string, double?> Values);
