// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Neml.Api.Auth;
using Neml.Domain.Dtos;
using Neml.Domain.Entities;
using Neml.Infrastructure.Persistence;
using RefreshTokenStore = Neml.Infrastructure.Security.RefreshTokenStore;

namespace Neml.Api.Controllers;

/// <summary>
/// Spec 9.3 Auth. HS256 access token with a 15 minute life plus a rotating 30 day refresh
/// token, Argon2id passwords, three roles (spec 5.5).
/// </summary>
[Route("api/v1/auth")]
[Tags("Auth")]
public sealed class AuthController(NemlDbContext db, JwtIssuer jwt, RefreshTokenStore refreshTokens) : NemlController
{
    /// <summary>Exchanges e-mail and password for an access and refresh token pair.</summary>
    [HttpPost("login")]
    [AllowAnonymous]
    [ProducesResponseType<TokenResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    public async Task<ActionResult<TokenResponse>> Login(LoginRequest request, CancellationToken ct)
    {
        var user = await db.Users.AsNoTracking().FirstOrDefaultAsync(u => u.Email == request.Email, ct);

        // The Argon2id parameters live in Neml.Infrastructure.Security, defined once.
        if (user is null || !PasswordHasher.Verify(user.PasswordHash, request.Password))
        {
            return Unauthorized();
        }

        return await IssueAsync(user, ct);
    }

    /// <summary>Rotates the refresh token: the presented one is spent and can never be reused.</summary>
    [HttpPost("refresh")]
    [AllowAnonymous]
    [ProducesResponseType<TokenResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    public async Task<ActionResult<TokenResponse>> Refresh(RefreshRequest request, CancellationToken ct)
    {
        var rotated = JwtIssuer.NewRefreshToken();
        var stored = await refreshTokens.RotateAsync(request.Refresh, rotated, ct);
        if (stored is null)
        {
            return Unauthorized();
        }

        var user = await db.Users.AsNoTracking().FirstOrDefaultAsync(u => u.Id == stored.UserId, ct);
        if (user is null)
        {
            await refreshTokens.RevokeAsync(rotated, ct);
            return Unauthorized();
        }

        return new TokenResponse(jwt.CreateAccessToken(user.Id, user.Email, Roles.Name(user.Role)), rotated);
    }

    /// <summary>Revokes one refresh token. The access token simply runs out within 15 minutes.</summary>
    [HttpPost("logout")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    public async Task<IActionResult> Logout(LogoutRequest request, CancellationToken ct)
    {
        await refreshTokens.RevokeAsync(request.Refresh, ct);
        return NoContent();
    }

    /// <summary>The caller's registered devices (settings screen, sessions).</summary>
    [HttpGet("devices")]
    [ProducesResponseType<IReadOnlyList<DeviceResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<DeviceResponse>>> Devices(CancellationToken ct)
    {
        var userId = UserId;
        return await db.Devices.AsNoTracking()
            .Where(d => d.UserId == userId)
            .OrderByDescending(d => d.LastSeen)
            .Select(d => new DeviceResponse(d.Id, d.Platform, d.PushToken, d.LastSeen))
            .ToListAsync(ct);
    }

    /// <summary>Push token registration for the spec 10.4 notifications.</summary>
    [HttpPost("devices")]
    [ProducesResponseType<DeviceResponse>(StatusCodes.Status200OK)]
    public async Task<ActionResult<DeviceResponse>> RegisterDevice(RegisterDeviceRequest request, CancellationToken ct)
    {
        var userId = UserId;
        var device = await db.Devices
            .FirstOrDefaultAsync(d => d.UserId == userId && d.PushToken == request.PushToken, ct);

        if (device is null)
        {
            device = new Device { Id = Guid.NewGuid(), UserId = userId, Platform = request.Platform };
            db.Devices.Add(device);
        }

        device.Platform = request.Platform;
        device.PushToken = request.PushToken;
        device.LastSeen = DateTimeOffset.UtcNow;
        await db.SaveChangesAsync(ct);

        return new DeviceResponse(device.Id, device.Platform, device.PushToken, device.LastSeen);
    }

    private async Task<TokenResponse> IssueAsync(User user, CancellationToken ct)
    {
        var refresh = JwtIssuer.NewRefreshToken();
        await refreshTokens.IssueAsync(user.Id, refresh, ct);
        return new TokenResponse(jwt.CreateAccessToken(user.Id, user.Email, Roles.Name(user.Role)), refresh);
    }
}
