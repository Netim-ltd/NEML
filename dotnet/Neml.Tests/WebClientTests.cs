// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using Microsoft.JSInterop;
using Neml.Web;
using Neml.Web.Pages;
using Neml.Web.Services;

namespace Neml.Tests;

/// <summary>T-056 — the web client's own logic: token rotation, the §5.2 level 4 gate, tabs.</summary>
public sealed class WebClientTests
{
    [Fact]
    public async Task A_401_triggers_a_refresh_and_the_request_is_replayed_with_the_new_token()
    {
        var js = new FakeJsRuntime();
        js.Storage["neml.access"] = "access-1";
        js.Storage["neml.refresh"] = "refresh-1";

        var stub = new StubHandler();
        var tokens = new TokenStore(js, new HttpClient(stub, disposeHandler: false) { BaseAddress = Root });
        await tokens.LoadAsync();

        using var client = new HttpClient(new AuthHandler(tokens) { InnerHandler = stub }) { BaseAddress = Root };
        using var response = await client.GetAsync("api/v1/tasks");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var protectedCalls = stub.Requests.Where(r => r.Path.EndsWith("/tasks", StringComparison.Ordinal)).ToArray();
        Assert.Equal(2, protectedCalls.Length);
        Assert.Equal("access-1", protectedCalls[0].Token);
        Assert.Equal("access-2", protectedCalls[1].Token);

        // Rotation replaces both halves of the pair in session storage (§5.5).
        Assert.Equal("access-2", js.Storage["neml.access"]);
        Assert.Equal("refresh-2", js.Storage["neml.refresh"]);
        Assert.Equal("access-2", tokens.Access);
    }

    [Fact]
    public async Task A_failed_refresh_signs_the_session_out_instead_of_looping()
    {
        var js = new FakeJsRuntime();
        js.Storage["neml.access"] = "access-1";
        js.Storage["neml.refresh"] = "stale";

        var stub = new StubHandler { RefreshSucceeds = false };
        var tokens = new TokenStore(js, new HttpClient(stub, disposeHandler: false) { BaseAddress = Root });
        await tokens.LoadAsync();

        using var client = new HttpClient(new AuthHandler(tokens) { InnerHandler = stub }) { BaseAddress = Root };
        using var response = await client.GetAsync("api/v1/tasks");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Single(stub.Requests, r => r.Path.EndsWith("/tasks", StringComparison.Ordinal));
        Assert.False(tokens.IsAuthenticated);
        Assert.Empty(js.Storage);
    }

    [Fact]
    public async Task A_posted_body_survives_the_replay()
    {
        var js = new FakeJsRuntime { Storage = { ["neml.access"] = "access-1", ["neml.refresh"] = "refresh-1" } };
        var stub = new StubHandler();
        var tokens = new TokenStore(js, new HttpClient(stub, disposeHandler: false) { BaseAddress = Root });
        await tokens.LoadAsync();

        using var client = new HttpClient(new AuthHandler(tokens) { InnerHandler = stub }) { BaseAddress = Root };
        using var response = await client.PostAsync("api/v1/tasks", new StringContent("""{"title":"x"}"""));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.All(
            stub.Requests.Where(r => r.Path.EndsWith("/tasks", StringComparison.Ordinal)),
            r => Assert.Equal("""{"title":"x"}""", r.Body));
    }

    [Theory]
    [InlineData("ONAYLIYORUM", true)]
    [InlineData("  ONAYLIYORUM  ", false)]
    [InlineData("onaylıyorum", false)]
    [InlineData("ONAYLİYORUM", false)]
    [InlineData("ONAYLA", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    public void Level_4_needs_the_exact_phrase(string? typed, bool expected) =>
        Assert.Equal(expected, ApprovalLevels.IsLevel4Confirmed(typed));

    [Fact]
    public void Countdown_reports_an_expired_approval()
    {
        Assert.Equal("süresi doldu", ApprovalLevels.Countdown(TimeSpan.FromSeconds(-1)));
        Assert.Equal("23:59:59", ApprovalLevels.Countdown(TimeSpan.FromDays(1) - TimeSpan.FromSeconds(1)));
    }

    [Theory]
    [InlineData("queued", "queue")]
    [InlineData("planning", "queue")]
    [InlineData("awaiting_approval", "queue")]
    [InlineData("paused", "queue")]
    [InlineData("running", "running")]
    [InlineData("succeeded", "done")]
    [InlineData("failed", "done")]
    [InlineData("cancelled", "done")]
    public void Every_task_state_lands_on_a_tab(string state, string tab) =>
        Assert.Equal(tab, TaskList.Bucket(state));

    private static Uri Root => new("https://neml.test/");

    private sealed class StubHandler : HttpMessageHandler
    {
        private int attempts;

        public bool RefreshSucceeds { get; init; } = true;

        public List<(string Path, string? Token, string? Body)> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri!.AbsolutePath;
            var body = request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
            Requests.Add((path, request.Headers.Authorization?.Parameter, body));

            if (path.EndsWith("/auth/refresh", StringComparison.Ordinal))
            {
                return RefreshSucceeds
                    ? Json("""{"access":"access-2","refresh":"refresh-2"}""")
                    : new HttpResponseMessage(HttpStatusCode.Unauthorized);
            }

            // First call on a protected route is stale, the replay succeeds.
            return ++attempts == 1
                ? new HttpResponseMessage(HttpStatusCode.Unauthorized)
                : Json("""[]""");
        }

        private static HttpResponseMessage Json(string payload) =>
            new(HttpStatusCode.OK) { Content = new StringContent(payload, System.Text.Encoding.UTF8, "application/json") };
    }

    private sealed class FakeJsRuntime : IJSRuntime
    {
        public Dictionary<string, string> Storage { get; } = [];

        public ValueTask<TValue> InvokeAsync<TValue>(string identifier, object?[]? args) =>
            InvokeAsync<TValue>(identifier, CancellationToken.None, args);

        public ValueTask<TValue> InvokeAsync<TValue>(string identifier, CancellationToken cancellationToken, object?[]? args)
        {
            var key = (string)args![0]!;
            switch (identifier)
            {
                case "sessionStorage.setItem":
                    Storage[key] = (string)args[1]!;
                    break;
                case "sessionStorage.removeItem":
                    Storage.Remove(key);
                    break;
                case "sessionStorage.getItem":
                    return ValueTask.FromResult((TValue)(object?)Storage.GetValueOrDefault(key)!);
            }

            return ValueTask.FromResult(default(TValue)!);
        }
    }
}
