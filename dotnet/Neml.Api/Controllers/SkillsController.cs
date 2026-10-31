// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Neml.Domain.Dtos;
using Neml.Infrastructure.Persistence;

namespace Neml.Api.Controllers;

/// <summary>Spec 9.3 Skills.</summary>
[Route("api/v1/skills")]
[Tags("Skills")]
public sealed class SkillsController(NemlDbContext db) : NemlController
{
    /// <summary>Newest version of every skill key.</summary>
    [HttpGet]
    [ProducesResponseType<IReadOnlyList<SkillResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<SkillResponse>>> List(CancellationToken ct) =>
        await Project(db.Skills.AsNoTracking()
                .Where(s => !db.Skills.Any(o => o.SkillKey == s.SkillKey && o.Version > s.Version))
                .OrderBy(s => s.SkillKey))
            .ToListAsync(ct);

    /// <summary>Every version of one skill key, newest first.</summary>
    [HttpGet("{key}/versions")]
    [ProducesResponseType<IReadOnlyList<SkillResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<SkillResponse>>> Versions(string key, CancellationToken ct) =>
        await Project(db.Skills.AsNoTracking()
                .Where(s => s.SkillKey == key)
                .OrderByDescending(s => s.Version))
            .ToListAsync(ct);

    private static IQueryable<SkillResponse> Project(IQueryable<Domain.Entities.Skill> skills) =>
        skills.Select(s => new SkillResponse(
            s.Id, s.SkillKey, s.Version, s.GenomeId, s.BtPath, s.Parameters, s.Preconditions,
            s.Status, s.Supersedes, s.CreatedAt));
}
