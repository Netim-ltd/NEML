// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Neml.Api.Auth;
using Neml.Domain.Enums;

namespace Neml.Tests;

/// <summary>Boots Neml.Api in memory over its own Program entry point.</summary>
public sealed class ApiFactory : WebApplicationFactory<Program>
{
    /// <summary>HS256 needs 32 bytes (§5.5). Test key, never a deployed one.</summary>
    public const string JwtKey = "neml-test-signing-key-32-bytes-min!!";

    /// <summary>The §5.5 long lived bridge key and the one node id it is bound to.</summary>
    public const string BridgeKey = "neml-test-bridge-key";

    public const string BridgeNode = "lab-01";

    private static readonly IConfiguration Configuration = new ConfigurationBuilder()
        .AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["Jwt:Key"] = JwtKey,
            ["Jwt:Issuer"] = "neml",
            ["Jwt:Audience"] = "neml-clients",

            // The hosted API talks to the same migrated database TestDb provisions, so an
            // endpoint test exercises the real SQL rather than a stub.
            ["ConnectionStrings:Default"] = TestDb.ConnectionString,

            // §5.5 bridge scheme. AllowedIps stays empty, so the address check is off and the
            // key, the node id and the header are what the tests exercise.
            ["Bridge:ApiKey"] = BridgeKey,
            ["Bridge:NodeIds:0"] = BridgeNode,
        })
        .Build();

    /// <summary>A signed §5.5 access token for one of the three roles, with no user row behind it.</summary>
    public static string TokenFor(UserRole role) => TokenFor(role, Guid.NewGuid());

    /// <summary>The same token bound to a seeded users row, which every queued write needs.</summary>
    public static string TokenFor(UserRole role, Guid userId) => new JwtIssuer(Configuration)
        .CreateAccessToken(userId, $"{userId:N}@neml.local", Roles.Name(role));

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        foreach (var (key, value) in Configuration.AsEnumerable())
        {
            builder.UseSetting(key, value);
        }
    }
}
