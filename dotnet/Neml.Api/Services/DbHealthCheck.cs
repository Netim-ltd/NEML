// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Neml.Infrastructure.Persistence;

namespace Neml.Api.Services;

/// <summary>/health — the mirror database plus bridge liveness (spec 18.3).</summary>
public sealed class DbHealthCheck(NemlDbContext db, LabState lab) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var data = new Dictionary<string, object> { ["bridgeConnected"] = lab.BridgeConnected };

        return await db.Database.CanConnectAsync(cancellationToken)
            ? HealthCheckResult.Healthy("neml_cloud reachable", data)
            : HealthCheckResult.Unhealthy("neml_cloud unreachable", data: data);
    }
}
