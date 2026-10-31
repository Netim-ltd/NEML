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

namespace Neml.Api.Controllers;

/// <summary>Spec 9.3 manufacturing — print jobs.</summary>
[Route("api/v1/print-jobs")]
[Tags("PrintJobs")]
public sealed class PrintJobsController(NemlDbContext db, CommandQueue queue) : NemlController
{
    [HttpGet]
    [ProducesResponseType<IReadOnlyList<PrintJobResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<PrintJobResponse>>> List(CancellationToken ct) =>
        await db.PrintJobs.AsNoTracking()
            .OrderByDescending(j => j.StartedAt)
            .Select(j => new PrintJobResponse(
                j.Id, j.ArtifactId, j.PrinterId, j.ProfileId, j.ApprovalId, j.EstTimeH, j.EstFilamentG,
                j.EstCostTry, j.State, j.Qc, j.StartedAt, j.EndedAt))
            .ToListAsync(ct);

    /// <summary>
    /// Cancelling only queues a command. Killing a running printer for real is the smart plug
    /// of spec 5.1, deliberately outside every software path.
    /// </summary>
    [HttpPost("{id:guid}/cancel")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Cancel(Guid id, CancelRequest request, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(new { jobId = id, request.Reason }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.PrintCancel, payload, IdempotencyKey(), ct));
    }

    /// <summary>
    /// Spec 12.5 quality form. The cloud only queues it: the lab stores the verdict, writes the
    /// measured mass back to the genome and may compensate the slicer profile.
    /// </summary>
    [HttpPost("{id:guid}/qc")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<CommandAccepted>> Qc(Guid id, JsonElement form, CancellationToken ct)
    {
        if (form.ValueKind != JsonValueKind.Object)
        {
            return Problem("QC form must be a JSON object", statusCode: StatusCodes.Status400BadRequest);
        }

        if (!await db.PrintJobs.AnyAsync(j => j.Id == id, ct))
        {
            return NotFound();
        }

        var payload = JsonSerializer.Serialize(new { jobId = id, form }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.PrintQc, payload, IdempotencyKey(), ct));
    }
}
