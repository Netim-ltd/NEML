// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using Neml.Api.Auth;
using Neml.Api.Contracts;
using Neml.Domain.Dtos;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using PasswordHasher = Neml.Infrastructure.Security.PasswordHasher;

namespace Neml.Tests;

/// <summary>
/// §5.5 as an attacker would meet it: the access token lifetime boundary, an attempt to climb
/// a role, the Argon2id work factors, and the two rate limits actually turning the 101st
/// request and the 11th command away.
/// </summary>
[Collection(NemlCloud.Name)]
public sealed class SecurityTests : IDisposable
{
    private readonly ApiFactory factory = new();

    public void Dispose() => factory.Dispose();

    // ---------- access token lifetime (§5.5: HS256, 15 minutes) ----------

    [Fact]
    public void The_access_token_lives_exactly_fifteen_minutes()
    {
        Assert.Equal(15, JwtIssuer.AccessTokenMinutes);

        var token = new JsonWebTokenHandler().ReadJsonWebToken(ApiFactory.TokenFor(UserRole.Viewer));
        var life = token.ValidTo - token.ValidFrom;

        Assert.Equal(TimeSpan.FromMinutes(15), life);
        Assert.Equal("HS256", token.Alg);
    }

    [ApiTheory]

    // The 30 s ClockSkew of JwtIssuer is deliberate, so the boundary is 15 min + 30 s and a
    // token one minute past its expiry must be gone even with that allowance.
    [InlineData(60, HttpStatusCode.OK)]         // issued a minute ago, still valid.
    [InlineData(-60, HttpStatusCode.Unauthorized)] // dated a minute ahead: nbf past the skew.
    [InlineData(890, HttpStatusCode.OK)]        // 10 s short of expiry.
    [InlineData(910, HttpStatusCode.OK)]        // 10 s past expiry, inside the clock skew.
    [InlineData(1000, HttpStatusCode.Unauthorized)]   // past expiry + skew.
    [InlineData(86_400, HttpStatusCode.Unauthorized)] // a day old.
    public async Task An_access_token_is_refused_once_it_is_past_expiry_and_skew(
        int ageSeconds, HttpStatusCode expected)
    {
        using var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue(
            "Bearer", SignedToken(DateTime.UtcNow.AddSeconds(-ageSeconds), Roles.Viewer));

        using var response = await client.GetAsync("api/v1/brain/status");

        Assert.Equal(expected, response.StatusCode);
    }

    [ApiFact]
    public async Task A_token_signed_with_another_key_or_audience_is_refused()
    {
        var cases = new[]
        {
            SignedToken(DateTime.UtcNow, Roles.Owner, key: "a-different-32-byte-signing-key!!!!!"),
            SignedToken(DateTime.UtcNow, Roles.Owner, audience: "somebody-elses-clients"),
            SignedToken(DateTime.UtcNow, Roles.Owner, issuer: "not-neml"),
        };

        using var client = factory.CreateClient();
        foreach (var token in cases)
        {
            client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
            using var response = await client.GetAsync("api/v1/brain/status");
            Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        }
    }

    // ---------- role escalation (§5.5) ----------

    /// <summary>Every §9.3 write. A viewer reaching any of them would be an escalation.</summary>
    public static TheoryData<string, string> OperatorRoutes() => new()
    {
        { "POST", "api/v1/robots/R01/estop" },
        { "POST", "api/v1/tasks" },
        { "PATCH", $"api/v1/tasks/{Guid.Empty}" },
        { "POST", $"api/v1/tasks/{Guid.Empty}/cancel" },
        { "POST", "api/v1/brain/command" },
        { "POST", "api/v1/campaigns" },
        { "POST", $"api/v1/campaigns/{Guid.Empty}/stop" },
        { "POST", $"api/v1/approvals/{Guid.Empty}/approve" },
        { "POST", $"api/v1/approvals/{Guid.Empty}/reject" },
        { "POST", $"api/v1/print-jobs/{Guid.Empty}/cancel" },
    };

    [ApiTheory]
    [MemberData(nameof(OperatorRoutes))]
    public async Task A_viewer_is_turned_away_from_every_write(string method, string route)
    {
        using var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(UserRole.Viewer));

        using var request = new HttpRequestMessage(new HttpMethod(method), route)
        {
            Content = JsonContent.Create(new { }),
        };
        using var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [ApiFact]
    public async Task Rewriting_the_role_claim_breaks_the_signature()
    {
        // The classic escalation attempt: take a real viewer token and edit "viewer" to
        // "owner" in the payload segment without touching the signature.
        var parts = ApiFactory.TokenFor(UserRole.Viewer).Split('.');
        var payload = Encoding.UTF8.GetString(Base64UrlEncoder.DecodeBytes(parts[1]))
            .Replace(Roles.Viewer, Roles.Owner, StringComparison.Ordinal);
        var forged = $"{parts[0]}.{Base64UrlEncoder.Encode(Encoding.UTF8.GetBytes(payload))}.{parts[2]}";

        using var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", forged);

        using var response = await client.PostAsJsonAsync(
            $"api/v1/approvals/{Guid.NewGuid()}/approve", new ApprovalDecisionRequest(null));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [ApiFact]
    public async Task The_bridge_key_buys_no_user_rights_and_a_user_token_buys_no_bridge_rights()
    {
        using var bridge = factory.CreateClient();
        bridge.DefaultRequestHeaders.Add(BridgeAuthenticationHandler.KeyHeader, ApiFactory.BridgeKey);
        bridge.DefaultRequestHeaders.Add(BridgeAuthenticationHandler.NodeHeader, ApiFactory.BridgeNode);

        // The lab node authenticates, but under its own scheme: it holds no §5.5 role and so
        // reaches nothing under /api/v1.
        using var read = await bridge.GetAsync("api/v1/robots");
        Assert.Equal(HttpStatusCode.Unauthorized, read.StatusCode);

        using var write = await bridge.PostAsJsonAsync("api/v1/brain/command", new BrainCommandRequest("hello"));
        Assert.Equal(HttpStatusCode.Unauthorized, write.StatusCode);
    }

    // ---------- Argon2id parameters (§5.5) ----------

    [Fact]
    public void The_stored_hash_carries_argon2id_at_its_documented_work_factors()
    {
        var encoded = PasswordHasher.Hash("kuvvetli-sifre-2026");

        // $argon2id$v=19$m=65536,t=3,p=1$<salt>$<hash>
        var match = Regex.Match(
            encoded,
            @"^\$argon2id\$v=(?<v>\d+)\$m=(?<m>\d+),t=(?<t>\d+),p=(?<p>\d+)\$(?<salt>[^$]+)\$(?<hash>[^$]+)$");
        Assert.True(match.Success, encoded);

        Assert.Equal(19, int.Parse(match.Groups["v"].Value));                     // Argon2 1.3.
        Assert.True(int.Parse(match.Groups["m"].Value) >= 65_536, "memory cost fell below 64 MiB");
        Assert.True(int.Parse(match.Groups["t"].Value) >= 3, "time cost fell below 3 passes");
        Assert.True(int.Parse(match.Groups["p"].Value) >= 1, "parallelism fell below 1");
        Assert.True(Base64UrlEncoder.DecodeBytes(match.Groups["salt"].Value).Length >= 16, "salt under 16 bytes");
        Assert.True(Base64UrlEncoder.DecodeBytes(match.Groups["hash"].Value).Length >= 32, "digest under 32 bytes");
    }

    [Fact]
    public void A_hash_never_verifies_a_different_password_or_a_tampered_digest()
    {
        var password = string.Concat("kuvvetli", "-", "sifre", "-", "2026"); // gitleaks:allow
        var encoded = PasswordHasher.Hash(password);

        Assert.True(PasswordHasher.Verify(encoded, password));
        Assert.False(PasswordHasher.Verify(encoded, password.ToUpperInvariant()));
        Assert.False(PasswordHasher.Verify(encoded, password[..^1]));
        Assert.False(PasswordHasher.Verify(encoded[..^2] + "AA", password));   // Digest bent by two chars.
        Assert.False(PasswordHasher.Verify("not-a-hash", password));
        Assert.False(PasswordHasher.Verify(encoded, string.Empty));
    }

    // ---------- rate limits (§5.5: 100 requests/min/user, 10 commands/min) ----------

    [Fact]
    public void The_two_limits_are_the_numbers_5_5_names()
    {
        Assert.Equal(100, RateLimits.RequestsPerMinute);
        Assert.Equal(10, RateLimits.CommandsPerMinute);
    }

    [ApiFact]
    public async Task The_hundred_and_first_request_of_a_minute_is_rejected()
    {
        using var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(UserRole.Viewer, Guid.NewGuid()));

        for (var i = 1; i <= RateLimits.RequestsPerMinute; i++)
        {
            using var inside = await client.GetAsync("api/v1/brain/status");
            Assert.Equal(HttpStatusCode.OK, inside.StatusCode);
        }

        using var over = await client.GetAsync("api/v1/brain/status");
        Assert.Equal(HttpStatusCode.TooManyRequests, over.StatusCode);
    }

    [ApiFact]
    public async Task The_limit_is_per_user_not_per_server()
    {
        using var noisy = factory.CreateClient();
        noisy.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(UserRole.Viewer, Guid.NewGuid()));

        for (var i = 0; i <= RateLimits.RequestsPerMinute; i++)
        {
            (await noisy.GetAsync("api/v1/brain/status")).Dispose();
        }

        Assert.Equal(
            HttpStatusCode.TooManyRequests,
            (await noisy.GetAsync("api/v1/brain/status")).StatusCode);

        // A second operator is untouched by the first one's spending.
        using var quiet = factory.CreateClient();
        quiet.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(UserRole.Viewer, Guid.NewGuid()));

        using var response = await quiet.GetAsync("api/v1/brain/status");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [ApiFact]
    public async Task The_eleventh_command_of_a_minute_is_rejected_while_reads_still_pass()
    {
        using var client = await CommandClientAsync();

        for (var i = 1; i <= RateLimits.CommandsPerMinute; i++)
        {
            using var accepted = await client.PostAsJsonAsync(
                "api/v1/brain/command", new BrainCommandRequest($"komut {i}"));
            Assert.Equal(HttpStatusCode.Accepted, accepted.StatusCode);
        }

        using var over = await client.PostAsJsonAsync("api/v1/brain/command", new BrainCommandRequest("bir fazla"));
        Assert.Equal(HttpStatusCode.TooManyRequests, over.StatusCode);

        // The command budget is its own partition: reading is still well inside the 100.
        using var read = await client.GetAsync("api/v1/brain/status");
        Assert.Equal(HttpStatusCode.OK, read.StatusCode);
    }

    [ApiFact]
    public async Task The_command_budget_is_shared_across_every_write_endpoint()
    {
        using var client = await CommandClientAsync();

        // Ten writes spread over four §9.3 endpoints still spend one budget, not four.
        for (var i = 0; i < 4; i++)
        {
            (await client.PostAsJsonAsync("api/v1/brain/command", new BrainCommandRequest($"b{i}"))).Dispose();
            (await client.PostAsJsonAsync($"api/v1/tasks/{Guid.NewGuid()}/cancel", new CancelRequest(null))).Dispose();
        }

        (await client.PostAsJsonAsync($"api/v1/campaigns/{Guid.NewGuid()}/stop", new { })).Dispose();
        (await client.PostAsJsonAsync($"api/v1/print-jobs/{Guid.NewGuid()}/cancel", new CancelRequest(null))).Dispose();

        using var eleventh = await client.PostAsJsonAsync("api/v1/brain/command", new BrainCommandRequest("son"));
        Assert.Equal(HttpStatusCode.TooManyRequests, eleventh.StatusCode);
    }

    // ---------- fixtures ----------

    /// <summary>A client whose token belongs to a real users row, which commands.user_id needs.</summary>
    private async Task<HttpClient> CommandClientAsync()
    {
        await using var db = TestDb.Connect();
        var user = new User
        {
            Id = Guid.NewGuid(),
            Email = $"{Guid.NewGuid():N}@neml.test",
            PasswordHash = "x",
            Role = UserRole.Operator,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();

        var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(UserRole.Operator, user.Id));
        return client;
    }

    /// <summary>
    /// A token the API would accept, issued at a chosen moment. JwtIssuer always stamps "now",
    /// so the expiry boundary can only be reached by signing one here with the same key.
    /// </summary>
    private static string SignedToken(
        DateTime issuedAt,
        string role,
        string key = ApiFactory.JwtKey,
        string issuer = "neml",
        string audience = "neml-clients") =>
        new JsonWebTokenHandler().CreateToken(new SecurityTokenDescriptor
        {
            Issuer = issuer,
            Audience = audience,
            IssuedAt = issuedAt,
            NotBefore = issuedAt,
            Expires = issuedAt.AddMinutes(JwtIssuer.AccessTokenMinutes),
            SigningCredentials = new SigningCredentials(
                new SymmetricSecurityKey(Encoding.UTF8.GetBytes(key)), SecurityAlgorithms.HmacSha256),
            Subject = new ClaimsIdentity(
            [
                new Claim(JwtRegisteredClaimNames.Sub, Guid.NewGuid().ToString()),
                new Claim(JwtRegisteredClaimNames.Email, "expiry@neml.test"),
                new Claim(ClaimTypes.Role, role),
            ]),
        });
}
