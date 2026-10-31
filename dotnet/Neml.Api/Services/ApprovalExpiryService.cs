// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.EntityFrameworkCore;
using Neml.Api.Hubs;
using Neml.Infrastructure.Persistence;
using Neml.Infrastructure.Repositories;

namespace Neml.Api.Services;

/// <summary>
/// Spec 5.2: an approval request times out (24 h by default) and is then automatically
/// rejected. Enforced by this sweep rather than at read time, so a stale request can never be
/// decided after its deadline, and every expiry is published as ApprovalDecided.
/// </summary>
public sealed class ApprovalExpiryService(
    IServiceScopeFactory scopes,
    LiveBroadcaster live,
    ILogger<ApprovalExpiryService> log)
    : BackgroundService
{
    private static readonly TimeSpan Interval = TimeSpan.FromMinutes(1);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(Interval);
        do
        {
            try
            {
                await ExpireOnceAsync(stoppingToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                log.LogError(ex, "Approval expiry sweep failed.");
            }
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }

    private async Task ExpireOnceAsync(CancellationToken ct)
    {
        using var scope = scopes.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<NemlDbContext>();

        var now = DateTimeOffset.UtcNow;
        var overdue = await db.Approvals.AsNoTracking()
            .Where(a => a.Decision == null && a.ExpiresAt <= now)
            .Select(a => a.Id)
            .ToListAsync(ct);

        if (overdue.Count == 0)
        {
            return;
        }

        await scope.ServiceProvider.GetRequiredService<ApprovalRepository>().ExpireOverdueAsync(ct);

        foreach (var id in overdue)
        {
            await live.ApprovalDecidedAsync(new ApprovalDecidedPayload(id, "expired", "system"));
        }

        log.LogInformation("Expired {Count} approval request(s).", overdue.Count);
    }
}
