// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Text;
using Neml.Cli;

namespace Neml.Tests;

/// <summary>T-057 — the console tool's own logic: cached session, level 4 phrase, tables.</summary>
public sealed class CliTests : IDisposable
{
    private readonly string original = Session.Path;
    private readonly string directory = Path.Combine(Path.GetTempPath(), "neml-cli-" + Guid.NewGuid().ToString("N"));

    public CliTests() => Session.Path = Path.Combine(directory, "session.json");

    [Fact]
    public void A_saved_session_is_read_back()
    {
        new Session("https://neml.test", "access-1", "refresh-1").Save();

        var loaded = Session.Load();

        Assert.NotNull(loaded);
        Assert.Equal("https://neml.test", loaded.Server);
        Assert.Equal("access-1", loaded.Access);
        Assert.Equal("refresh-1", loaded.Refresh);
    }

    [Fact]
    public void No_session_file_means_no_session()
    {
        Assert.Null(Session.Load());
    }

    [Fact]
    public void A_corrupt_session_file_is_treated_as_absent()
    {
        Directory.CreateDirectory(directory);
        File.WriteAllText(Session.Path, "{ not json");

        Assert.Null(Session.Load());
    }

    [Fact]
    public void Logout_removes_the_cached_session()
    {
        new Session("https://neml.test", "a", "r").Save();

        Session.Clear();

        Assert.Null(Session.Load());
        Assert.False(File.Exists(Session.Path));
    }

    [Theory]
    [InlineData("ONAYLIYORUM", true)]
    [InlineData(" ONAYLIYORUM ", true)]
    [InlineData("onaylıyorum", false)]
    [InlineData("evet", false)]
    [InlineData(null, false)]
    public void Level_4_needs_the_exact_phrase(string? typed, bool expected) =>
        Assert.Equal(expected, Level4.IsConfirmed(typed));

    [Fact]
    public void A_table_pads_every_column_to_its_widest_cell()
    {
        var rendered = Table.Render(
            ["ROBOT", "DURUM"],
            [["R01", "idle"], ["R002", "running"]]);

        var lines = rendered.Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries);

        Assert.Equal("ROBOT  DURUM", lines[0]);
        Assert.Equal("-----  -------", lines[1]);
        Assert.Equal("R01    idle", lines[2]);
        Assert.Equal("R002   running", lines[3]);
    }

    [Fact]
    public void A_missing_or_null_cell_renders_as_a_dash()
    {
        var rendered = Table.Render(["A", "B"], [[null, "x"], ["y"]]);
        var lines = rendered.Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries);

        Assert.Equal("-  x", lines[2]);
        Assert.Equal("y  -", lines[3]);
    }

    [Fact]
    public async Task Login_caches_the_token_pair_for_the_server_it_came_from()
    {
        var session = await CliApi.LoginAsync("https://neml.test", "mg@neml.test", "kuvvetli-sifre", new StubHandler());

        Assert.Equal("https://neml.test", session.Server);
        Assert.Equal("access-1", session.Access);
        Assert.Equal("refresh-1", session.Refresh);
    }

    [Fact]
    public async Task A_401_refreshes_replays_the_request_and_re_caches_the_rotated_pair()
    {
        new Session("https://neml.test", "access-1", "refresh-1").Save();
        var stub = new StubHandler { ExpireFirstCall = true };

        using var api = new CliApi(Session.Load()!, stub);
        var robots = await api.GetRobotsAsync();

        Assert.NotNull(robots);

        var protectedCalls = stub.Requests.Where(r => r.Path.EndsWith("/robots", StringComparison.Ordinal)).ToArray();
        Assert.Equal(2, protectedCalls.Length);
        Assert.Equal("access-1", protectedCalls[0].Token);
        Assert.Equal("access-2", protectedCalls[1].Token);

        // §5.5 rotation: the cached file must hold the new pair, not the spent one.
        var cached = Session.Load();
        Assert.Equal("access-2", cached!.Access);
        Assert.Equal("refresh-2", cached.Refresh);
    }

    [Fact]
    public async Task A_failed_refresh_surfaces_the_401_instead_of_looping()
    {
        new Session("https://neml.test", "access-1", "stale").Save();
        var stub = new StubHandler { ExpireFirstCall = true, RefreshSucceeds = false };

        using var api = new CliApi(Session.Load()!, stub);

        await Assert.ThrowsAsync<HttpRequestException>(api.GetRobotsAsync);
        Assert.Single(stub.Requests, r => r.Path.EndsWith("/robots", StringComparison.Ordinal));
    }

    public void Dispose()
    {
        Session.Path = original;
        if (Directory.Exists(directory))
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    private sealed class StubHandler : HttpMessageHandler
    {
        private int protectedCalls;

        public bool ExpireFirstCall { get; init; }

        public bool RefreshSucceeds { get; init; } = true;

        public List<(string Path, string? Token)> Requests { get; } = [];

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri!.AbsolutePath;
            Requests.Add((path, request.Headers.Authorization?.Parameter));

            if (path.EndsWith("/auth/login", StringComparison.Ordinal))
            {
                return Task.FromResult(Json("""{"access":"access-1","refresh":"refresh-1"}"""));
            }

            if (path.EndsWith("/auth/refresh", StringComparison.Ordinal))
            {
                return Task.FromResult(RefreshSucceeds
                    ? Json("""{"access":"access-2","refresh":"refresh-2"}""")
                    : new HttpResponseMessage(HttpStatusCode.Unauthorized));
            }

            return Task.FromResult(ExpireFirstCall && ++protectedCalls == 1
                ? new HttpResponseMessage(HttpStatusCode.Unauthorized)
                : Json("[]"));
        }

        private static HttpResponseMessage Json(string payload) =>
            new(HttpStatusCode.OK) { Content = new StringContent(payload, Encoding.UTF8, "application/json") };
    }
}
