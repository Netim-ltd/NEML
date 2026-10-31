// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;
using Neml.Api.Auth;
using Neml.Api.Contracts;
using Neml.Api.Services;
using Neml.Domain.Dtos;
using Neml.Infrastructure.Persistence;
using Neml.Infrastructure.Repositories;
using CommandQueue = Neml.Api.Services.CommandQueue;

namespace Neml.Api.Controllers;

/// <summary>
/// Spec 9.3 Robots. Reads come from the neml_cloud mirror; e-stop goes to the command queue
/// like every other write.
/// </summary>
[Route("api/v1/robots")]
[Tags("Robots")]
public sealed class RobotsController(NemlDbContext db, TelemetryRepository telemetry, CommandQueue queue)
    : NemlController
{
    [HttpGet]
    [ProducesResponseType<IReadOnlyList<RobotResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<RobotResponse>>> List(CancellationToken ct) =>
        await Project(db.Robots.AsNoTracking().OrderBy(r => r.Id)).ToListAsync(ct);

    [HttpGet("{id}")]
    [ProducesResponseType<RobotResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<RobotResponse>> Get(string id, CancellationToken ct)
    {
        var robot = await Project(db.Robots.AsNoTracking().Where(r => r.Id == id)).FirstOrDefaultAsync(ct);
        return robot is null ? NotFound() : robot;
    }

    /// <summary>
    /// Telemetry series. agg is raw, avg (default), min, max, sum or count; aggregated queries
    /// bucket by minute. from defaults to one hour ago and to defaults to now.
    /// </summary>
    [HttpGet("{id}/telemetry")]
    [ProducesResponseType<IReadOnlyList<TelemetryPointResponse>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<IReadOnlyList<TelemetryPointResponse>>> Telemetry(
        string id,
        [FromQuery] string metric,
        [FromQuery] DateTimeOffset? from,
        [FromQuery] DateTimeOffset? to,
        [FromQuery] string? agg,
        CancellationToken ct)
    {
        // metric is non-nullable, so [ApiController]'s implicit Required answers an empty or
        // whitespace value with the validation problem before the action runs.
        var query = new TelemetryQuery(
            metric,
            from ?? DateTimeOffset.UtcNow.AddHours(-1),
            to ?? DateTimeOffset.UtcNow,
            string.IsNullOrWhiteSpace(agg) ? "avg" : agg);

        try
        {
            return Ok(await telemetry.RangeAsync(id, query, ct));
        }
        catch (ArgumentOutOfRangeException)
        {
            return Problem("agg must be raw, avg, min, max, sum or count", statusCode: StatusCodes.Status400BadRequest);
        }
    }

    /// <summary>
    /// Spec 9.3: e-stop is queued like every other command. This server cannot cut motor power
    /// itself — that is the hardware e-stop of spec 5.1, which no software path can reach.
    /// </summary>
    [HttpPost("{id}/estop")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Estop(string id, EstopRequest request, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(new { robotId = id, request.Reason }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.RobotEstop, payload, IdempotencyKey(), ct));
    }

    private static IQueryable<RobotResponse> Project(IQueryable<Domain.Entities.Robot> robots) =>
        robots.Select(r => new RobotResponse(
            r.Id, r.GenomeId, r.Namespace, r.Hostname, r.State, r.BatterySoc,
            r.LastSeen, r.CalibratedAt, r.RealityGap));
}
