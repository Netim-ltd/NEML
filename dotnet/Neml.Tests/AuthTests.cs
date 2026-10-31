// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Net.Http.Headers;
using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Neml.Api.Auth;
using Neml.Domain.Enums;
using RefreshTokenStore = Neml.Infrastructure.Security.RefreshTokenStore;

namespace Neml.Tests;

/// <summary>T-051 — JWT + refresh rotation + roles (§5.5), and the §5.2 level 4 owner gate.</summary>
public sealed class AuthTests
{
    // ---------- §5.5 refresh rotation ----------
    // The store keeps only the SHA-256 of each token in refresh_tokens, so these run against
    // the real database TestDb provisions rather than an in-process dictionary.

    [Fact]
    public async Task Refresh_rotation_invalidates_the_old_token()
    {
        await using var db = TestDb.Connect();
        var user = await TestDb.SeedUserAsync(db);
        var store = new RefreshTokenStore(db);

        var first = JwtIssuer.NewRefreshToken();
        await store.IssueAsync(user, first);

        var second = JwtIssuer.NewRefreshToken();
        var rotated = await store.RotateAsync(first, second);
        Assert.NotNull(rotated);
        Assert.Equal(user, rotated.UserId);
        Assert.NotEqual(first, second);

        // The new one still works exactly once.
        var third = JwtIssuer.NewRefreshToken();
        Assert.NotNull(await store.RotateAsync(second, third));

        // Replaying a spent token means the chain leaked: it is refused and every live token
        // of that user dies with it, third included.
        Assert.Null(await store.RotateAsync(second, JwtIssuer.NewRefreshToken()));
        Assert.Null(await store.RotateAsync(third, JwtIssuer.NewRefreshToken()));
    }

    [Fact]
    public async Task Revoked_refresh_token_cannot_be_rotated()
    {
        await using var db = TestDb.Connect();
        var token = JwtIssuer.NewRefreshToken();
        var store = new RefreshTokenStore(db);
        await store.IssueAsync(await TestDb.SeedUserAsync(db), token);

        Assert.True(await store.RevokeAsync(token));
        Assert.False(await store.RevokeAsync(token));   // Already spent.

        Assert.Null(await store.RotateAsync(token, JwtIssuer.NewRefreshToken()));
    }

    [Theory]
    [InlineData("not-a-token")]
    [InlineData("")]
    public async Task An_unknown_refresh_token_is_rejected(string token)
    {
        await using var db = TestDb.Connect();
        var store = new RefreshTokenStore(db);

        Assert.Null(await store.RotateAsync(token, JwtIssuer.NewRefreshToken()));
        Assert.False(await store.RevokeAsync(token));
    }

    [Fact]
    public async Task Two_users_never_share_a_refresh_token()
    {
        await using var db = TestDb.Connect();
        var store = new RefreshTokenStore(db);
        var alice = await TestDb.SeedUserAsync(db);
        var bob = await TestDb.SeedUserAsync(db);

        var aliceToken = JwtIssuer.NewRefreshToken();
        var bobToken = JwtIssuer.NewRefreshToken();
        await store.IssueAsync(alice, aliceToken);
        await store.IssueAsync(bob, bobToken);

        Assert.NotEqual(aliceToken, bobToken);

        // Rotating Alice's token hands back Alice's row, and leaves Bob logged in.
        var rotated = await store.RotateAsync(aliceToken, JwtIssuer.NewRefreshToken());
        Assert.Equal(alice, rotated!.UserId);
        Assert.True(await store.RevokeAsync(bobToken));
    }

    // ---------- §5.5 / §5.2 authority model ----------

    [Theory]
    [InlineData(Roles.Owner, 1, true)]
    [InlineData(Roles.Owner, 4, true)]
    [InlineData(Roles.Operator, 1, true)]
    [InlineData(Roles.Operator, 3, true)]
    [InlineData(Roles.Operator, 4, false)]   // §5.5: level 4 is owner only.
    [InlineData(Roles.Viewer, 1, false)]
    [InlineData(Roles.Viewer, 4, false)]
    [InlineData("admin", 1, false)]          // An invented role decides nothing.
    public async Task Approval_authority_follows_5_5(string role, int level, bool expected)
    {
        var context = Requirement(new ClaimsIdentity([new Claim(ClaimTypes.Role, role)], "test"), level);

        await new ApprovalDecisionHandler().HandleAsync(context);

        Assert.Equal(expected, context.HasSucceeded);
    }

    [Fact]
    public async Task Approval_authority_denies_an_unauthenticated_principal()
    {
        var context = Requirement(new ClaimsIdentity(), 1);

        await new ApprovalDecisionHandler().HandleAsync(context);

        Assert.False(context.HasSucceeded);
    }

    // ---------- §5.5 over the wire ----------

    [ApiFact]
    public async Task Unauthenticated_request_is_rejected()
    {
        using var factory = new ApiFactory();
        using var client = factory.CreateClient();

        using var response = await client.GetAsync("api/v1/robots");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [ApiFact]
    public async Task A_token_this_server_did_not_sign_is_rejected()
    {
        using var factory = new ApiFactory();
        using var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", "not.a.jwt");

        using var response = await client.GetAsync("api/v1/robots");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [ApiFact]
    public async Task A_viewer_cannot_decide_an_approval()
    {
        using var factory = new ApiFactory();
        using var client = Authenticated(factory, UserRole.Viewer);

        using var response = await client.PostAsync($"api/v1/approvals/{Guid.NewGuid()}/approve", null);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [ApiFact]
    public async Task A_viewer_may_read()
    {
        using var factory = new ApiFactory();
        using var client = Authenticated(factory, UserRole.Viewer);

        using var response = await client.GetAsync("api/v1/brain/status");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private static HttpClient Authenticated(ApiFactory factory, UserRole role)
    {
        var client = factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", ApiFactory.TokenFor(role));
        return client;
    }

    private static AuthorizationHandlerContext Requirement(ClaimsIdentity identity, int level) => new(
        [new ApprovalDecisionRequirement()],
        new ClaimsPrincipal(identity),
        new ApprovalResource(Guid.NewGuid(), level));
}
