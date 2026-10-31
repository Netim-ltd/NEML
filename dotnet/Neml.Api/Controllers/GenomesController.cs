// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.Mvc;
using Neml.Domain.Dtos;
using Neml.Infrastructure.Repositories;

namespace Neml.Api.Controllers;

/// <summary>Spec 9.3 Genomes — the lineage tree the mobile app draws.</summary>
[Route("api/v1/genomes")]
[Tags("Genomes")]
public sealed class GenomesController(GenomeRepository genomes) : NemlController
{
    /// <summary>Roots first, children nested.</summary>
    [HttpGet("tree")]
    [ProducesResponseType<IReadOnlyList<GenomeNodeResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<GenomeNodeResponse>>> Tree(CancellationToken ct) =>
        Ok(await genomes.TreeAsync(ct));
}
