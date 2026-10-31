// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Reflection;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Neml.Cli;

namespace Neml.Tests;

/// <summary>
/// nemlctl runs in one process, talks to one static session file, and every command writes to
/// the process-wide Console. Nothing else may run beside it.
/// </summary>
[CollectionDefinition(CliSession.Name, DisableParallelization = true)]
public sealed class CliSession
{
    public const string Name = "nemlctl session";
}

/// <summary>
/// T-057 through the real entry point: every §9.3 command nemlctl offers, driven against a
/// loopback server so the HttpClient, the argument parser and the exit codes are all real.
/// The §5.2 level 4 phrase is checked here, where a mistyped confirmation would land.
/// </summary>
[Collection(CliSession.Name)]
public sealed class CliCommandTests : IDisposable
{
    private static readonly Guid TaskId = Guid.Parse("11111111-1111-1111-1111-111111111111");
    private static readonly Guid ApprovalId = Guid.Parse("22222222-2222-2222-2222-222222222222");

    private readonly string originalPath = Session.Path;
    private readonly TextWriter originalOut = Console.Out;
    private readonly TextWriter originalError = Console.Error;
    private readonly string directory = Path.Combine(Path.GetTempPath(), "neml-cli-" + Guid.NewGuid().ToString("N"));
    private readonly Stub stub = new();

    public CliCommandTests() => Session.Path = Path.Combine(directory, "session.json");

    public void Dispose()
    {
        Console.SetOut(originalOut);
        Console.SetError(originalError);
        Session.Path = originalPath;
        stub.DisposeAsync().AsTask().GetAwaiter().GetResult();
        if (Directory.Exists(directory))
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    // ---------- login / logout ----------

    [Fact]
    public async Task Login_caches_the_pair_and_logout_drops_it()
    {
        var login = await RunAsync("login", "--server", stub.Url, "--email", "mg@neml.test", "--password", "kuvvetli-sifre");

        Assert.Equal(0, login.Code);
        Assert.Contains("Giriş başarılı", login.Out);
        Assert.Equal("access-1", Session.Load()!.Access);

        var logout = await RunAsync("logout");

        Assert.Equal(0, logout.Code);
        Assert.Null(Session.Load());
        Assert.Contains("POST /api/v1/auth/logout", stub.Calls);
    }

    [Fact]
    public async Task An_empty_typed_password_stops_before_the_network()
    {
        Console.SetIn(new StringReader(string.Empty));

        var result = await RunAsync("login", "--server", stub.Url, "--email", "mg@neml.test");

        Assert.Equal(2, result.Code);
        Assert.Contains("Şifre gerekli", result.Error);
        Assert.DoesNotContain("POST /api/v1/auth/login", stub.Calls);
    }

    [Fact]
    public async Task A_refused_login_exits_one_and_caches_nothing()
    {
        stub.Routes["POST /api/v1/auth/login"] = (401, "{}");

        var result = await RunAsync("login", "--server", stub.Url, "--email", "mg@neml.test", "--password", "kuvvetli-sifre");

        Assert.Equal(1, result.Code);
        Assert.Contains("Giriş başarısız", result.Error);
        Assert.Null(Session.Load());
    }

    [Fact]
    public async Task Every_command_needs_a_session_first()
    {
        var result = await RunAsync("status");

        Assert.Equal(2, result.Code);
        Assert.Contains("nemlctl login", result.Error);
    }

    // ---------- status ----------

    [Fact]
    public async Task Status_prints_the_brain_line_and_a_robot_table()
    {
        SignIn();

        var result = await RunAsync("status");

        Assert.Equal(0, result.Code);
        Assert.Contains("Beyin: çevrimiçi", result.Out);
        Assert.Contains("qwen2.5-1.5b", result.Out);
        Assert.Contains("R01", result.Out);
        Assert.Contains("87%", result.Out);

        // §7 robots has no current-task column: the running task is joined in from /tasks.
        Assert.Contains("bacak taraması", result.Out);
    }

    [Fact]
    public async Task Status_says_so_when_the_brain_answers_nothing()
    {
        SignIn();
        stub.Routes["GET /api/v1/brain/status"] = (200, "null");

        var result = await RunAsync("status");

        Assert.Equal(0, result.Code);
        Assert.Contains("Beyin durumu alınamadı", result.Out);
    }

    [Fact]
    public async Task A_server_error_is_reported_rather_than_thrown()
    {
        SignIn();
        stub.Routes["GET /api/v1/brain/status"] = (500, "{}");

        var result = await RunAsync("status");

        Assert.Equal(1, result.Code);
        Assert.Contains("API hatası", result.Error);
    }

    // ---------- tasks ----------

    [Fact]
    public async Task Task_list_passes_the_state_filter_through()
    {
        SignIn();

        var all = await RunAsync("task", "list");
        var filtered = await RunAsync("task", "list", "--state", "running");

        Assert.Equal(0, all.Code);
        Assert.Equal(0, filtered.Code);
        Assert.Contains("BAŞLIK", all.Out);
        Assert.Contains("bacak taraması", filtered.Out);
        Assert.Contains("GET /api/v1/tasks?state=running", stub.Queries);
    }

    [Fact]
    public async Task Task_show_prints_the_spec_and_a_missing_one_exits_one()
    {
        SignIn();

        var found = await RunAsync("task", "show", TaskId.ToString());

        Assert.Equal(0, found.Code);
        Assert.Contains("bacak taraması", found.Out);
        Assert.Contains("\"gait\"", found.Out);

        stub.Routes[$"GET /api/v1/tasks/{TaskId}"] = (200, "null");
        var missing = await RunAsync("task", "show", TaskId.ToString());

        Assert.Equal(1, missing.Code);
        Assert.Contains("Görev bulunamadı", missing.Error);
    }

    [Fact]
    public async Task Task_cancel_reports_both_outcomes()
    {
        SignIn();

        var accepted = await RunAsync("task", "cancel", TaskId.ToString());
        Assert.Equal(0, accepted.Code);
        Assert.Contains("Görev iptal edildi", accepted.Out);

        stub.Routes[$"POST /api/v1/tasks/{TaskId}/cancel"] = (409, "{}");
        var refused = await RunAsync("task", "cancel", TaskId.ToString());

        Assert.Equal(1, refused.Code);
        Assert.Contains("HTTP 409", refused.Error);
    }

    // ---------- approvals ----------

    [Fact]
    public async Task Approval_list_and_show_render_the_pending_queue()
    {
        SignIn();

        var list = await RunAsync("approval", "list");
        Assert.Equal(0, list.Code);
        Assert.Contains("SEVİYE", list.Out);
        Assert.Contains(ApprovalId.ToString(), list.Out);

        var show = await RunAsync("approval", "show", ApprovalId.ToString());
        Assert.Equal(0, show.Code);
        Assert.Contains("bekliyor", show.Out);
        Assert.Contains("/previews/leg.png", show.Out);
        Assert.Contains("\"summary\"", show.Out);

        stub.Routes[$"GET /api/v1/approvals/{ApprovalId}"] = (200, "null");
        var missing = await RunAsync("approval", "show", ApprovalId.ToString());

        Assert.Equal(1, missing.Code);
        Assert.Contains("Onay bulunamadı", missing.Error);
    }

    [Fact]
    public async Task A_level_2_approval_goes_through_and_a_rejection_reports_itself()
    {
        SignIn();

        var approved = await RunAsync("approval", "approve", ApprovalId.ToString(), "--note", "tamam");
        Assert.Equal(0, approved.Code);
        Assert.Contains("Onaylandı", approved.Out);
        Assert.Contains($"POST /api/v1/approvals/{ApprovalId}/approve", stub.Calls);

        var rejected = await RunAsync("approval", "reject", ApprovalId.ToString(), "-n", "olmaz");
        Assert.Equal(0, rejected.Code);
        Assert.Contains("Reddedildi", rejected.Out);
        Assert.Contains($"POST /api/v1/approvals/{ApprovalId}/reject", stub.Calls);
    }

    /// <summary>§5.2: MANUFACTURE needs the phrase typed out, and nothing is sent without it.</summary>
    [Theory]
    [InlineData(null, 2, false)]
    [InlineData("onaylıyorum", 2, false)]
    [InlineData("evet", 2, false)]
    [InlineData(Level4.Phrase, 0, true)]
    public async Task Level_4_is_gated_on_the_confirmation_phrase(string? confirm, int expected, bool sent)
    {
        SignIn();
        stub.Routes[$"GET /api/v1/approvals/{ApprovalId}"] = (200, ApprovalJson(level: 4));

        string[] args = confirm is null
            ? ["approval", "approve", ApprovalId.ToString()]
            : ["approval", "approve", ApprovalId.ToString(), "--confirm", confirm];

        var result = await RunAsync(args);

        Assert.Equal(expected, result.Code);
        Assert.Equal(sent, stub.Calls.Contains($"POST /api/v1/approvals/{ApprovalId}/approve"));
        if (!sent)
        {
            Assert.Contains(Level4.Phrase, result.Error);
        }
    }

    [Fact]
    public async Task A_refused_decision_exits_one()
    {
        SignIn();
        stub.Routes[$"POST /api/v1/approvals/{ApprovalId}/approve"] = (403, "{}");

        var result = await RunAsync("approval", "approve", ApprovalId.ToString());

        Assert.Equal(1, result.Code);
        Assert.Contains("HTTP 403", result.Error);
    }

    // ---------- plumbing ----------

    private void SignIn() => new Session(stub.Url, "access-1", "refresh-1").Save();

    /// <summary>Runs nemlctl's real entry point in-process and collects what it wrote.</summary>
    private static async Task<(int Code, string Out, string Error)> RunAsync(params string[] args)
    {
        var entry = typeof(Session).Assembly.EntryPoint
            ?? throw new InvalidOperationException("nemlctl has no entry point.");

        var stdout = new StringWriter();
        var stderr = new StringWriter();
        Console.SetOut(stdout);
        Console.SetError(stderr);

        var code = await Task.Run(async () => Invoke(entry, args) switch
        {
            Task<int> task => await task,
            int value => value,
            var other => throw new InvalidOperationException($"Unexpected exit value {other}."),
        });

        return (code, stdout.ToString(), stderr.ToString());
    }

    private static object? Invoke(MethodBase entry, string[] args) =>
        entry.GetParameters().Length == 0 ? entry.Invoke(null, null) : entry.Invoke(null, [args]);

    private static string ApprovalJson(int level) =>
        $$"""
        {"id":"{{ApprovalId}}","level":{{level}},"subjectKind":"task","subjectId":"{{TaskId}}",
         "payload":{"summary":"bacak baskısı"},"requestedAt":"2026-09-16T08:00:00+00:00",
         "expiresAt":"2026-09-17T08:00:00+00:00","decidedBy":null,"decision":null,"note":null,
         "previewUrl":"/previews/leg.png"}
        """;

    /// <summary>
    /// A loopback server speaking the §9.3 shapes nemlctl reads. Not a handler double: nemlctl
    /// builds its own HttpClient, so the socket has to be real for the entry point to be.
    /// </summary>
    private sealed class Stub : IAsyncDisposable
    {
        private readonly WebApplication app;

        public Stub()
        {
            var builder = WebApplication.CreateSlimBuilder();
            builder.Logging.ClearProviders();

            app = builder.Build();
            app.Urls.Add("http://127.0.0.1:0");
            app.Run(HandleAsync);
            app.StartAsync().GetAwaiter().GetResult();
            Url = app.Urls.First();

            Routes = new Dictionary<string, (int, string)>(StringComparer.Ordinal)
            {
                ["POST /api/v1/auth/login"] = (200, """{"access":"access-1","refresh":"refresh-1"}"""),
                ["POST /api/v1/auth/refresh"] = (200, """{"access":"access-2","refresh":"refresh-2"}"""),
                ["POST /api/v1/auth/logout"] = (204, ""),
                ["GET /api/v1/brain/status"] = (200,
                    """{"online":true,"model":"qwen2.5-1.5b","gpuOwner":"llm","budgetUsed":0.4,"lastSeen":null}"""),
                ["GET /api/v1/robots"] = (200,
                    """[{"id":"R01","state":"idle","batterySoc":0.87,"lastSeen":"2026-09-16T08:00:00+00:00","realityGap":0.12}]"""),
                ["GET /api/v1/tasks"] = (200,
                    $$"""
                    {"items":[{"id":"{{TaskId}}","title":"bacak taraması","kind":"sim","source":"human",
                     "priority":0.5,"state":"running","robotId":"R01","spec":{"gait":"trot"},"result":null}],
                     "page":1,"pageSize":50}
                    """),
                [$"GET /api/v1/tasks/{TaskId}"] = (200,
                    $$"""
                    {"id":"{{TaskId}}","title":"bacak taraması","kind":"sim","source":"human","priority":0.5,
                     "state":"running","robotId":"R01","spec":{"gait":"trot"},"result":null}
                    """),
                [$"POST /api/v1/tasks/{TaskId}/cancel"] = (202, "{}"),
                ["GET /api/v1/approvals"] = (200, $"[{ApprovalJson(level: 2)}]"),
                [$"GET /api/v1/approvals/{ApprovalId}"] = (200, ApprovalJson(level: 2)),
                [$"POST /api/v1/approvals/{ApprovalId}/approve"] = (202, "{}"),
                [$"POST /api/v1/approvals/{ApprovalId}/reject"] = (202, "{}"),
            };
        }

        public string Url { get; }

        public Dictionary<string, (int Status, string Json)> Routes { get; }

        /// <summary>"METHOD /path", in arrival order.</summary>
        public List<string> Calls { get; } = [];

        /// <summary>The same with the query string, for the filter assertions.</summary>
        public List<string> Queries { get; } = [];

        public async ValueTask DisposeAsync()
        {
            await app.StopAsync();
            await app.DisposeAsync();
        }

        private async Task HandleAsync(HttpContext context)
        {
            var key = $"{context.Request.Method} {context.Request.Path}";
            lock (Calls)
            {
                Calls.Add(key);
                Queries.Add(key + context.Request.QueryString);
            }

            if (!Routes.TryGetValue(key, out var route))
            {
                context.Response.StatusCode = StatusCodes.Status404NotFound;
                return;
            }

            context.Response.StatusCode = route.Status;
            if (route.Json.Length > 0)
            {
                context.Response.ContentType = "application/json";
                await context.Response.WriteAsync(route.Json);
            }
        }
    }
}
