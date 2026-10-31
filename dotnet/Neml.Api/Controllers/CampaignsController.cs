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

/// <summary>Spec 9.3 training and evolution campaigns.</summary>
[Route("api/v1/campaigns")]
[Tags("Campaigns")]
public sealed class CampaignsController(NemlDbContext db, CommandQueue queue) : NemlController
{
    [HttpGet]
    [ProducesResponseType<IReadOnlyList<CampaignResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<CampaignResponse>>> List(CancellationToken ct) =>
        await Project(db.Campaigns.AsNoTracking().OrderByDescending(c => c.StartedAt)).ToListAsync(ct);

    [HttpGet("{id:guid}")]
    [ProducesResponseType<CampaignResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<CampaignResponse>> Get(Guid id, CancellationToken ct)
    {
        var campaign = await Project(db.Campaigns.AsNoTracking().Where(c => c.Id == id)).FirstOrDefaultAsync(ct);
        return campaign is null ? NotFound() : campaign;
    }

    /// <summary>Fitness series per generation (spec 9.3, 14.3).</summary>
    [HttpGet("{id:guid}/generations")]
    [ProducesResponseType<IReadOnlyList<GenerationPointResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<GenerationPointResponse>>> Generations(
        Guid id, CancellationToken ct) =>
        await db.Candidates.AsNoTracking()
            .Where(c => c.CampaignId == id)
            .GroupBy(c => c.Generation)
            .OrderBy(g => g.Key)
            .Select(g => new GenerationPointResponse(
                g.Key,
                g.Max(c => c.Fitness),
                g.Average(c => c.Fitness),
                g.Count(c => c.Fitness != null)))
            .ToListAsync(ct);

    /// <summary>Candidates of one campaign, best first; the evolution screen's candidate list.</summary>
    [HttpGet("{id:guid}/candidates")]
    [ProducesResponseType<IReadOnlyList<CandidateResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<CandidateResponse>>> Candidates(Guid id, CancellationToken ct) =>
        await db.Candidates.AsNoTracking()
            .Where(c => c.CampaignId == id)
            .OrderByDescending(c => c.Generation)
            .ThenByDescending(c => c.Fitness)
            .Take(300)
            .Select(c => new CandidateResponse(
                c.Id, c.Generation, c.GenomeId, c.Operator, c.Rationale, c.Fitness, c.Verdict, c.CreatedAt, c.FitnessParts))
            .ToListAsync(ct);

    [HttpPost]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Create(CreateCampaignRequest request, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(request, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.CampaignCreate, payload, IdempotencyKey(), ct));
    }

    [HttpPost("{id:guid}/stop")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Stop(Guid id, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(new { campaignId = id }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.CampaignStop, payload, IdempotencyKey(), ct));
    }

    private static IQueryable<CampaignResponse> Project(IQueryable<Domain.Entities.Campaign> campaigns) =>
        campaigns.Select(c => new CampaignResponse(
            c.Id, c.Name, c.Objective, c.Weights, c.Budget, c.State, c.StartedAt, c.EndedAt));
}
