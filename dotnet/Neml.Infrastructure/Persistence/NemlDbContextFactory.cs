// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace Neml.Infrastructure.Persistence;

/// <summary>
/// Only "dotnet ef" uses this. No connection string: scaffolding a migration reads the model,
/// never the database. At runtime Neml.Api injects the real options.
/// </summary>
public sealed class NemlDbContextFactory : IDesignTimeDbContextFactory<NemlDbContext>
{
    public NemlDbContext CreateDbContext(string[] args) =>
        new(new DbContextOptionsBuilder<NemlDbContext>().UseNpgsql().Options);
}
