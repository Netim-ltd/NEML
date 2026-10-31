// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.EntityFrameworkCore;
using Neml.Domain.Dtos;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;

namespace Neml.Infrastructure.Repositories;

/// <summary>GET /approvals?pending=true, plus the section 5.2 timeout rule.</summary>
public class ApprovalRepository(NemlDbContext db)
{
    /// <summary>Undecided and not yet timed out, soonest to expire first.</summary>
    public async Task<IReadOnlyList<ApprovalResponse>> PendingAsync(CancellationToken ct = default)
    {
        var now = DateTimeOffset.UtcNow;
        return await db.Approvals.AsNoTracking()
            .Where(a => a.Decision == null && a.ExpiresAt > now)
            .OrderBy(a => a.ExpiresAt)
            .Select(a => new ApprovalResponse(
                a.Id, a.Level, a.SubjectKind, a.SubjectId, a.Payload, a.RequestedAt,
                a.ExpiresAt, a.DecidedAt, a.DecidedBy, a.Decision, a.Note))
            .ToListAsync(ct);
    }

    /// <summary>
    /// Section 5.2: an approval request that runs out of time is automatically rejected.
    /// Enforced here in code, never by asking a model to remember.
    /// </summary>
    public Task<int> ExpireOverdueAsync(CancellationToken ct = default)
    {
        var now = DateTimeOffset.UtcNow;
        return db.Approvals
            .Where(a => a.Decision == null && a.ExpiresAt <= now)
            .ExecuteUpdateAsync(s => s
                .SetProperty(a => a.Decision, (ApprovalDecision?)ApprovalDecision.Expired)
                .SetProperty(a => a.DecidedAt, (DateTimeOffset?)now), ct);
    }
}
