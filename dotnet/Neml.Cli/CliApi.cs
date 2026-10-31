// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace Neml.Cli;

/// <summary>Thin HTTP client over §9.3. Refreshes once on 401 and re-saves the rotated pair.</summary>
public sealed class CliApi(Session session, HttpMessageHandler? handler = null) : IDisposable
{
    private readonly HttpClient http = new(handler ?? new HttpClientHandler(), disposeHandler: true)
    {
        BaseAddress = new Uri(session.Server.TrimEnd('/') + "/"),
    };

    private Session current = session;

    public static async Task<Session> LoginAsync(string server, string email, string password, HttpMessageHandler? handler = null)
    {
        using var http = new HttpClient(handler ?? new HttpClientHandler(), disposeHandler: true)
        {
            BaseAddress = new Uri(server.TrimEnd('/') + "/"),
        };

        var response = await http.PostAsJsonAsync("api/v1/auth/login", new LoginRequest(email, password));
        response.EnsureSuccessStatusCode();
        var pair = await response.Content.ReadFromJsonAsync<TokenPair>()
            ?? throw new HttpRequestException("Sunucu token döndürmedi.");

        return new Session(server, pair.Access, pair.Refresh);
    }

    public Task<BrainStatus?> GetBrainStatusAsync() => GetAsync<BrainStatus>("api/v1/brain/status");

    public Task<Robot[]?> GetRobotsAsync() => GetAsync<Robot[]>("api/v1/robots");

    public async Task<IReadOnlyList<TaskItem>> GetTasksAsync(string? state) =>
        (await GetAsync<Paged<TaskItem>>(
            state is null ? "api/v1/tasks" : $"api/v1/tasks?state={Uri.EscapeDataString(state)}"))?.Items ?? [];

    public Task<TaskItem?> GetTaskAsync(Guid id) => GetAsync<TaskItem>($"api/v1/tasks/{id}");

    public Task<HttpResponseMessage> CancelTaskAsync(Guid id) =>
        SendAsync(() => new HttpRequestMessage(HttpMethod.Post, $"api/v1/tasks/{id}/cancel")
        {
            Content = JsonContent.Create(new { }),
        });

    public Task<Approval[]?> GetPendingApprovalsAsync() => GetAsync<Approval[]>("api/v1/approvals?pending=true");

    public Task<Approval?> GetApprovalAsync(Guid id) => GetAsync<Approval>($"api/v1/approvals/{id}");

    public async Task<JsonElement?> GetJsonAsync(string path) => await GetAsync<JsonElement>(path);

    public Task<HttpResponseMessage> SendJsonAsync(string path, object body) =>
        SendAsync(() => new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = JsonContent.Create(body),
        });

    public Task<HttpResponseMessage> DecideAsync(Guid id, bool approve, ApprovalDecision decision) =>
        SendAsync(() => new HttpRequestMessage(HttpMethod.Post, $"api/v1/approvals/{id}/{(approve ? "approve" : "reject")}")
        {
            Content = JsonContent.Create(decision),
        });

    public async Task LogoutAsync()
    {
        try
        {
            using var response = await SendAsync(() => new HttpRequestMessage(HttpMethod.Post, "api/v1/auth/logout")
            {
                Content = JsonContent.Create(new RefreshRequest(current.Refresh)),
            });
        }
        catch (HttpRequestException)
        {
            // The cached file is dropped regardless of what the server says.
        }

        Session.Clear();
    }

    private async Task<T?> GetAsync<T>(string path)
    {
        using var response = await SendAsync(() => new HttpRequestMessage(HttpMethod.Get, path));
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<T>();
    }

    private async Task<HttpResponseMessage> SendAsync(Func<HttpRequestMessage> factory)
    {
        var response = await http.SendAsync(Authorize(factory()));
        if (response.StatusCode != HttpStatusCode.Unauthorized || !await TryRefreshAsync())
        {
            return response;
        }

        response.Dispose();
        return await http.SendAsync(Authorize(factory()));
    }

    private HttpRequestMessage Authorize(HttpRequestMessage request)
    {
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", current.Access);
        return request;
    }

    private async Task<bool> TryRefreshAsync()
    {
        using var response = await http.PostAsJsonAsync("api/v1/auth/refresh", new RefreshRequest(current.Refresh));
        if (!response.IsSuccessStatusCode)
        {
            return false;
        }

        var pair = await response.Content.ReadFromJsonAsync<TokenPair>();
        if (pair is null)
        {
            return false;
        }

        current = current with { Access = pair.Access, Refresh = pair.Refresh };
        current.Save();
        return true;
    }

    public void Dispose() => http.Dispose();
}
