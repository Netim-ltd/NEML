// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Neml.Api.Auth;
using Neml.Api.Contracts;
using Neml.Api.Services;

namespace Neml.Api.Controllers;

/// <summary>Open-source designs from GitHub: list what a repository offers, then import chosen files into a robot model.</summary>
[Route("api/v1/imports")]
[Tags("Imports")]
public sealed class ImportsController(CommandQueue queue) : NemlController
{
    /// <summary>Lists the importable files (STL, STEP, KiCad, URDF) of a public GitHub repository with its licence.</summary>
    [HttpPost("scan")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Scan(ImportScanRequest request, CancellationToken ct)
    {
        // Spec 5.4: the address is untrusted data, forwarded verbatim; the lab validates it.
        var payload = JsonSerializer.Serialize(new { repo = request.Repo }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ImportScan, payload, IdempotencyKey(), ct));
    }

    /// <summary>Takes a model's imports again with the lab's current pipeline (poses, primitives, compact meshes).</summary>
    [HttpPost("refresh")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Refresh(ImportRefreshRequest request, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(new { genomeId = request.GenomeId, repo = request.Repo }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ImportRefresh, payload, IdempotencyKey(), ct));
    }

    /// <summary>Imports the chosen files into a new robot workspace or into an existing model, as a draft design.</summary>
    [HttpPost("github")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    public async Task<ActionResult<CommandAccepted>> Import(ImportRequest request, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(
            new { repo = request.Repo, branch = request.Branch, paths = request.Paths ?? [], all = request.All, ack = request.Ack, genomeId = request.GenomeId, newName = request.NewName },
            JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(UserId, CommandQueue.ImportGithub, payload, IdempotencyKey(), ct));
    }
}

/// <summary>POST /imports/refresh</summary>
public record ImportRefreshRequest(string GenomeId, string? Repo);

/// <summary>POST /imports/scan</summary>
public record ImportScanRequest(string Repo);

/// <summary>POST /imports/github</summary>
public record ImportRequest(string Repo, string? Branch, string[]? Paths, bool Ack, string? GenomeId, string? NewName, bool All = false);
