// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net.Http.Json;
using Microsoft.JSInterop;

namespace Neml.Web.Services;

/// <summary>
/// Holds the §5.5 JWT pair. Persisted in browser session storage so a tab reload keeps the
/// session but closing the tab ends it.
/// </summary>
public sealed class TokenStore(IJSRuntime js, HttpClient plain)
{
    private const string AccessKey = "neml.access";
    private const string RefreshKey = "neml.refresh";

    public string? Access { get; private set; }

    private readonly SemaphoreSlim refreshLock = new(1, 1);

    public string? Refresh { get; private set; }

    public bool IsAuthenticated => Access is not null;

    public async Task LoadAsync()
    {
        Access = await GetItemAsync(AccessKey);
        Refresh = await GetItemAsync(RefreshKey);
    }

    public async Task SignInAsync(string email, string password)
    {
        var response = await plain.PostAsJsonAsync("api/v1/auth/login", new LoginRequest(email, password));
        response.EnsureSuccessStatusCode();
        await StoreAsync(await response.Content.ReadFromJsonAsync<TokenPair>());
    }

    /// <summary>Rotates the refresh token (§5.5). Returns false when the session is dead.</summary>
    public async Task<bool> TryRefreshAsync(CancellationToken ct = default)
    {
        // Several requests hit the expired token together (polling, live feed): rotate once, the others reuse it.
        var seen = Refresh;
        await refreshLock.WaitAsync(ct);
        try
        {
            if (Refresh is null)
            {
                return false;
            }

            if (seen != Refresh && Access is not null)
            {
                return true; // another request already rotated the pair
            }

            var response = await plain.PostAsJsonAsync("api/v1/auth/refresh", new RefreshRequest(Refresh), ct);
            if (!response.IsSuccessStatusCode)
            {
                await SignOutAsync();
                return false;
            }

            await StoreAsync(await response.Content.ReadFromJsonAsync<TokenPair>(ct));
            return Access is not null;
        }
        catch (HttpRequestException)
        {
            return false;
        }
        finally
        {
            refreshLock.Release();
        }
    }

    public async Task SignOutAsync()
    {
        if (Refresh is not null)
        {
            try
            {
                await plain.PostAsJsonAsync("api/v1/auth/logout", new RefreshRequest(Refresh));
            }
            catch (HttpRequestException)
            {
                // The local session is dropped regardless of what the server says.
            }
        }

        Access = null;
        Refresh = null;
        await js.InvokeVoidAsync("sessionStorage.removeItem", AccessKey);
        await js.InvokeVoidAsync("sessionStorage.removeItem", RefreshKey);
    }

    private async Task StoreAsync(TokenPair? pair)
    {
        if (pair is null)
        {
            return;
        }

        Access = pair.Access;
        Refresh = pair.Refresh;
        await js.InvokeVoidAsync("sessionStorage.setItem", AccessKey, pair.Access);
        await js.InvokeVoidAsync("sessionStorage.setItem", RefreshKey, pair.Refresh);
    }

    private async Task<string?> GetItemAsync(string key)
    {
        try
        {
            return await js.InvokeAsync<string?>("sessionStorage.getItem", key);
        }
        catch (JSException)
        {
            return null;
        }
    }
}
