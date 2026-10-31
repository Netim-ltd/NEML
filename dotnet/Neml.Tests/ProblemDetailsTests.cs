// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Neml.Api.Auth;
using Neml.Domain.Dtos;
using Neml.Domain.Entities;
using Neml.Domain.Enums;

namespace Neml.Tests;

/// <summary>
/// §9.3: "Tüm yanıtlar application/json. Hata formatı RFC 7807 application/problem+json."
/// Every status code the API can answer with is walked here — a bare 401 or a plain string
/// conflict is a contract break the mobile and web clients cannot parse.
/// </summary>
[Collection(NemlCloud.Name)]
public sealed class ProblemDetailsTests : IDisposable
{
    private readonly ApiFactory factory = new();

    public void Dispose() => factory.Dispose();

    [ApiFact]
    public async Task An_unauthenticated_request_answers_in_problem_json()
    {
        using var client = factory.CreateClient();

        using var response = await client.GetAsync("api/v1/robots");

        await AssertProblemAsync(response, HttpStatusCode.Unauthorized);
    }

    [ApiFact]
    public async Task A_forbidden_request_answers_in_problem_json()
    {
        using var client = Authenticated(UserRole.Viewer);

        using var response = await client.PostAsJsonAsync(
            $"api/v1/approvals/{Guid.NewGuid()}/approve", new ApprovalDecisionRequest(null));

        await AssertProblemAsync(response, HttpStatusCode.Forbidden);
    }

    [ApiFact]
    public async Task A_missing_resource_answers_in_problem_json()
    {
        using var client = Authenticated(UserRole.Viewer);

        using var response = await client.GetAsync($"api/v1/robots/{Guid.NewGuid():N}");

        await AssertProblemAsync(response, HttpStatusCode.NotFound);
    }

    [ApiFact]
    public async Task A_failed_validation_answers_in_problem_json_with_the_field_errors()
    {
        using var client = factory.CreateClient();

        // §5.5 minimum 12 characters, refused by LoginRequestValidator before any lookup.
        using var response = await client.PostAsJsonAsync("api/v1/auth/login", new LoginRequest("not-an-address", "kisa"));

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest);
        Assert.True(problem.TryGetProperty("errors", out var errors));
        Assert.Equal(JsonValueKind.Object, errors.ValueKind);
    }

    [ApiTheory]
    [InlineData("api/v1/tasks?state=napping")]
    [InlineData("api/v1/tasks?kind=knitting")]
    [InlineData("api/v1/robots/R01/telemetry?metric=battery_soc&agg=median")]
    public async Task A_rejected_query_string_answers_in_problem_json(string route)
    {
        using var client = Authenticated(UserRole.Viewer);

        using var response = await client.GetAsync(route);

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest);
        Assert.False(string.IsNullOrWhiteSpace(problem.GetProperty("detail").GetString()));
    }

    /// <summary>
    /// A query parameter the binder refuses never reaches the action, so it answers with the
    /// validation shape (errors) rather than a detail. Still RFC 7807, still problem+json.
    /// </summary>
    [ApiFact]
    public async Task A_missing_query_parameter_answers_in_the_validation_problem_shape()
    {
        using var client = Authenticated(UserRole.Viewer);

        using var response = await client.GetAsync("api/v1/robots/R01/telemetry?metric=");

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest);
        Assert.True(problem.TryGetProperty("errors", out var errors));
        Assert.True(errors.TryGetProperty("metric", out _));
    }

    [ApiFact]
    public async Task A_conflict_answers_in_problem_json()
    {
        var approval = await SeedApprovalAsync(DateTimeOffset.UtcNow.AddHours(1));
        using var client = await OperatorClientAsync();

        (await client.PostAsJsonAsync($"api/v1/approvals/{approval}/approve", new ApprovalDecisionRequest(null)))
            .Dispose();

        using var again = await client.PostAsJsonAsync(
            $"api/v1/approvals/{approval}/approve", new ApprovalDecisionRequest(null));

        var problem = await AssertProblemAsync(again, HttpStatusCode.Conflict);
        Assert.Contains("approval already", problem.GetProperty("detail").GetString());
    }

    [ApiFact]
    public async Task An_expired_approval_conflicts_in_problem_json()
    {
        var approval = await SeedApprovalAsync(DateTimeOffset.UtcNow.AddMinutes(-1));
        using var client = await OperatorClientAsync();

        using var response = await client.PostAsJsonAsync(
            $"api/v1/approvals/{approval}/reject", new ApprovalDecisionRequest(null));

        // The §5.2 sweeper may already have rejected it, in which case the detail names the
        // recorded decision instead; either way an expired approval can never be decided.
        var problem = await AssertProblemAsync(response, HttpStatusCode.Conflict);
        Assert.Contains("xpired", problem.GetProperty("detail").GetString());
    }

    [ApiFact]
    public async Task A_rate_limited_request_answers_in_problem_json()
    {
        using var client = await OperatorClientAsync();

        for (var i = 0; i < RateLimits.CommandsPerMinute; i++)
        {
            (await client.PostAsJsonAsync("api/v1/brain/command", new BrainCommandRequest($"k{i}"))).Dispose();
        }

        using var response = await client.PostAsJsonAsync("api/v1/brain/command", new BrainCommandRequest("bir fazla"));

        await AssertProblemAsync(response, HttpStatusCode.TooManyRequests);
    }

    [ApiFact]
    public async Task The_bridge_refuses_a_plain_get_in_problem_json()
    {
        using var client = factory.CreateClient();
        client.DefaultRequestHeaders.Add(BridgeAuthenticationHandler.KeyHeader, ApiFactory.BridgeKey);
        client.DefaultRequestHeaders.Add(BridgeAuthenticationHandler.NodeHeader, ApiFactory.BridgeNode);

        using var response = await client.GetAsync("bridge/ws");

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest);
        Assert.Equal("websocket upgrade required", problem.GetProperty("detail").GetString());
    }

    // ---------- shared shape check ----------

    /// <summary>RFC 7807: a JSON object served as application/problem+json, carrying status.</summary>
    private static async Task<JsonElement> AssertProblemAsync(HttpResponseMessage response, HttpStatusCode expected)
    {
        Assert.Equal(expected, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);

        var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
        Assert.Equal(JsonValueKind.Object, body.ValueKind);
        Assert.Equal((int)expected, body.GetProperty("status").GetInt32());
        Assert.False(string.IsNullOrWhiteSpace(body.GetProperty("title").GetString()));
        Assert.False(string.IsNullOrWhiteSpace(body.GetProperty("type").GetString()));
        return body;
    }

    // ---------- fixtures ----------

    private HttpClient Authenticated(UserRole role)
    {
        var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(role));
        return client;
    }

    private async Task<HttpClient> OperatorClientAsync()
    {
        await using var db = TestDb.Connect();
        var user = new User
        {
            Id = Guid.NewGuid(),
            Email = $"{Guid.NewGuid():N}@neml.test",
            PasswordHash = "x",
            Role = UserRole.Owner,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();

        var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(UserRole.Owner, user.Id));
        return client;
    }

    private static async Task<Guid> SeedApprovalAsync(DateTimeOffset expiresAt)
    {
        await using var db = TestDb.Connect();
        var approval = new Approval
        {
            Id = Guid.NewGuid(),
            Level = 2,
            SubjectKind = "task",
            SubjectId = Guid.NewGuid().ToString("N"),
            Payload = JsonDocument.Parse("""{"summary":"move"}"""),
            RequestedAt = DateTimeOffset.UtcNow,
            ExpiresAt = expiresAt,
        };
        db.Approvals.Add(approval);
        await db.SaveChangesAsync();
        return approval.Id;
    }
}
