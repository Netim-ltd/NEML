// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.IdentityModel.JsonWebTokens;

namespace Neml.Api.Controllers;

/// <summary>Shared plumbing for the /api/v1 controllers of spec 9.3.</summary>
[ApiController]
[Authorize]
[Route("api/v1")]
[Produces("application/json")]
[ProducesResponseType(StatusCodes.Status401Unauthorized)]
[ProducesResponseType(StatusCodes.Status403Forbidden)]
public abstract class NemlController : ControllerBase
{
    /// <summary>Clients may replay a write safely by repeating this header (spec 3.1).</summary>
    public const string IdempotencyHeader = "Idempotency-Key";

    protected Guid UserId =>
        Guid.TryParse(User.FindFirstValue(JwtRegisteredClaimNames.Sub), out var id)
            ? id
            : throw new InvalidOperationException("Authenticated principal has no usable subject claim.");

    protected string IdempotencyKey() =>
        Request.Headers.TryGetValue(IdempotencyHeader, out var supplied) && !string.IsNullOrWhiteSpace(supplied)
            ? supplied.ToString()
            : Guid.NewGuid().ToString("N");
}
