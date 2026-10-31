// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Neml.Api.Services;
using Neml.Domain.Dtos;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;

namespace Neml.Api.Controllers;

/// <summary>
/// Spec 9.3 manufacturing — printer status. The API never calls PrusaLink; it reports the
/// last PrintProgress the lab pushed over the bridge for whatever job that printer is running.
/// </summary>
[Route("api/v1/printers")]
[Tags("Printers")]
public sealed class PrintersController(NemlDbContext db, LabState lab) : NemlController
{
    [HttpGet("{id}/status")]
    [ProducesResponseType<PrinterStatusResponse>(StatusCodes.Status200OK)]
    public async Task<ActionResult<PrinterStatusResponse>> Status(string id, CancellationToken ct)
    {
        var jobId = await db.PrintJobs.AsNoTracking()
            .Where(j => j.PrinterId == id && j.State == PrintJobState.Printing)
            .OrderByDescending(j => j.StartedAt)
            .Select(j => (Guid?)j.Id)
            .FirstOrDefaultAsync(ct);

        return lab.PrinterStatus(id, jobId);
    }
}
