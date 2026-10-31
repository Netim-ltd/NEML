// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Neml.Infrastructure.Persistence;

namespace Neml.Api.Controllers;

/// <summary>Spec 10.2 screen 12: the mirrored lab audit log, newest first.</summary>
[Route("api/v1/audit")]
[Tags("Audit")]
public sealed class AuditController(NemlDbContext db) : NemlController
{
    public const int MaxLimit = 500;

    [HttpGet]
    [ProducesResponseType<IReadOnlyList<AuditResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<AuditResponse>>> List(
        [FromQuery] string? actor,
        [FromQuery] string? outcome,
        [FromQuery] int limit,
        CancellationToken ct)
    {
        var query = db.AuditLog.AsNoTracking().AsQueryable();
        if (!string.IsNullOrEmpty(actor))
        {
            query = query.Where(a => a.Actor == actor);
        }

        if (!string.IsNullOrEmpty(outcome))
        {
            query = query.Where(a => a.Outcome == outcome);
        }

        return await query
            .OrderByDescending(a => a.Ts)
            .Take(limit is > 0 and <= MaxLimit ? limit : 100)
            .Select(a => new AuditResponse(
                a.Id, a.Ts, a.Actor, a.Action, a.Target, a.Outcome, a.DurationMs, a.ApprovalId))
            .ToListAsync(ct);
    }
}

public record AuditResponse(
    long Id,
    DateTimeOffset Ts,
    string Actor,
    string Action,
    string? Target,
    string? Outcome,
    int? DurationMs,
    Guid? ApprovalId);
