// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Reflection;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;
using Testcontainers.PostgreSql;

namespace Neml.Tests;

/// <summary>Reflection over the Neml.Api assembly, shared by the contract tests.</summary>
public static class ApiSurface
{
    public static readonly Assembly Assembly = typeof(Api.Hubs.LiveHub).Assembly;

    public static IReadOnlyList<Type> Controllers { get; } =
        [.. Assembly.GetTypes().Where(t => typeof(ControllerBase).IsAssignableFrom(t) && !t.IsAbstract)];
}

/// <summary>
/// A fact that needs the §9.3 controllers. If Neml.Api ever ships without one it reports as
/// skipped with the reason instead of silently passing; with controllers present every row
/// of the §9.3 table is checked for real and a missing endpoint fails the run.
/// </summary>
public sealed class ApiFactAttribute : FactAttribute
{
    public ApiFactAttribute()
    {
        if (ApiSurface.Controllers.Count == 0)
        {
            Skip = "Neml.Api exposes no ControllerBase type.";
        }
    }
}

/// <summary>
/// Every class that reads or writes the shared commands table. A live bridge session claims
/// from it on a 500 ms timer, so a class asserting that a command is still pending cannot run
/// beside one; xUnit gives a collection one test at a time.
/// </summary>
[CollectionDefinition(NemlCloud.Name)]
public sealed class NemlCloud
{
    public const string Name = "neml_cloud commands";
}

/// <summary>The <see cref="ApiFactAttribute"/> rule, for a data driven case.</summary>
public sealed class ApiTheoryAttribute : TheoryAttribute
{
    public ApiTheoryAttribute()
    {
        if (ApiSurface.Controllers.Count == 0)
        {
            Skip = "Neml.Api exposes no ControllerBase type.";
        }
    }
}

/// <summary>
/// The §7 schema on a real PostgreSQL. §18.1 puts the integration level on testcontainers, so
/// the suite starts its own postgres:16-alpine and migrates it — the command queue leans on
/// BIGSERIAL, UPDATE … RETURNING and FOR UPDATE SKIP LOCKED, none of which a fake provider
/// reproduces. NEML_TEST_POSTGRES points the run at an existing database instead.
/// </summary>
public static class TestDb
{
    public const string ConnectionVariable = "NEML_TEST_POSTGRES";

    /// <summary>A database somebody else provisioned, or null when the suite must start one.</summary>
    public static string? External => Environment.GetEnvironmentVariable(ConnectionVariable);

    // ponytail: one container for the whole run and never disposed — the Testcontainers reaper
    // removes it when the test process exits. Per-class containers if a suite ever needs to
    // start from an empty schema.
    private static readonly Lazy<string> Prepared = new(Prepare);

    public static string ConnectionString => Prepared.Value;

    public static NemlDbContext Connect() => new(Options(ConnectionString));

    /// <summary>commands and refresh_tokens both hang off users, so every case needs one.</summary>
    public static async Task<Guid> SeedUserAsync(NemlDbContext db)
    {
        var user = new User
        {
            Id = Guid.NewGuid(),
            Email = $"{Guid.NewGuid():N}@neml.test",
            PasswordHash = "x",
            Role = UserRole.Owner,
        };

        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private static DbContextOptions<NemlDbContext> Options(string connectionString) =>
        new DbContextOptionsBuilder<NemlDbContext>().UseNpgsql(connectionString).Options;

    private static string Prepare()
    {
        var connectionString = External;
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            var container = new PostgreSqlBuilder("postgres:16-alpine").Build();
            container.StartAsync().GetAwaiter().GetResult();
            connectionString = container.GetConnectionString();
        }

        using var db = new NemlDbContext(Options(connectionString));
        db.Database.Migrate();
        return connectionString;
    }
}
