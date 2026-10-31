// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Security.Cryptography;
using System.Text;
using Microsoft.EntityFrameworkCore;
using Neml.Domain.Entities;
using Neml.Infrastructure.Persistence;

namespace Neml.Infrastructure.Security;

/// <summary>
/// Section 5.5 refresh tokens: 30 days, rotated on every use. Issuing the token string and the
/// JWT is Neml.Api's job; this class only stores the SHA-256 of it, so a database dump leaks
/// no usable token.
/// </summary>
public class RefreshTokenStore(NemlDbContext db)
{
    public static readonly TimeSpan Lifetime = TimeSpan.FromDays(30);

    public async Task<RefreshToken> IssueAsync(Guid userId, string token, CancellationToken ct = default)
    {
        var stored = new RefreshToken
        {
            Id = Guid.NewGuid(),
            UserId = userId,
            TokenHash = HashOf(token),
            ExpiresAt = DateTimeOffset.UtcNow + Lifetime,
        };
        db.RefreshTokens.Add(stored);
        await db.SaveChangesAsync(ct);
        return stored;
    }

    /// <summary>
    /// Swaps a live token for its replacement. Returns null when the presented token is unknown,
    /// expired or already spent — the caller must then refuse the refresh.
    /// </summary>
    public async Task<RefreshToken?> RotateAsync(string presented, string replacement, CancellationToken ct = default)
    {
        var hash = HashOf(presented);

        // AsNoTracking throughout: the revocations below are server side UPDATEs, which leave
        // any tracked copy of the same row stale and would let a killed token rotate again.
        var current = await db.RefreshTokens.AsNoTracking().FirstOrDefaultAsync(t => t.TokenHash == hash, ct);
        if (current is null) return null;

        if (current.RevokedAt is not null)
        {
            // A token offered twice means the chain leaked: kill every live token of that user.
            await db.RefreshTokens
                .Where(t => t.UserId == current.UserId && t.RevokedAt == null)
                .ExecuteUpdateAsync(s => s.SetProperty(t => t.RevokedAt, (DateTimeOffset?)DateTimeOffset.UtcNow), ct);
            return null;
        }

        if (current.ExpiresAt <= DateTimeOffset.UtcNow) return null;

        var next = new RefreshToken
        {
            Id = Guid.NewGuid(),
            UserId = current.UserId,
            TokenHash = HashOf(replacement),
            ExpiresAt = DateTimeOffset.UtcNow + Lifetime,
        };

        // The conditional UPDATE is the spend: two refreshes racing on one token cannot both
        // match RevokedAt == null, so only one of them gets a replacement.
        var spent = await db.RefreshTokens
            .Where(t => t.Id == current.Id && t.RevokedAt == null)
            .ExecuteUpdateAsync(s => s
                .SetProperty(t => t.RevokedAt, (DateTimeOffset?)DateTimeOffset.UtcNow)
                .SetProperty(t => t.ReplacedBy, (Guid?)next.Id), ct);
        if (spent == 0) return null;

        db.RefreshTokens.Add(next);
        await db.SaveChangesAsync(ct);
        return next;
    }

    /// <summary>POST /auth/logout. False when the token was already unknown or spent.</summary>
    public async Task<bool> RevokeAsync(string token, CancellationToken ct = default)
    {
        var hash = HashOf(token);
        return await db.RefreshTokens
            .Where(t => t.TokenHash == hash && t.RevokedAt == null)
            .ExecuteUpdateAsync(s => s.SetProperty(t => t.RevokedAt, (DateTimeOffset?)DateTimeOffset.UtcNow), ct) > 0;
    }

    private static string HashOf(string token) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(token)));
}
