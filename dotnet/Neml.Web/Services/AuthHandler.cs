// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Net.Http.Headers;

namespace Neml.Web.Services;

/// <summary>
/// Attaches the access token and, on a single 401, rotates the refresh token and replays the
/// request once. A second 401 is surfaced to the caller so the UI can send the user to login.
/// </summary>
public sealed class AuthHandler(TokenStore tokens) : DelegatingHandler
{
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        // Buffer the body up front: a retried request cannot re-read a streamed content.
        var body = request.Content is null ? null : await request.Content.ReadAsByteArrayAsync(cancellationToken);
        var mediaType = request.Content?.Headers.ContentType;

        Authorize(request);
        var response = await base.SendAsync(request, cancellationToken);
        if (response.StatusCode != HttpStatusCode.Unauthorized)
        {
            return response;
        }

        if (!await tokens.TryRefreshAsync(cancellationToken))
        {
            return response;
        }

        response.Dispose();
        var retry = new HttpRequestMessage(request.Method, request.RequestUri);
        foreach (var header in request.Headers)
        {
            retry.Headers.TryAddWithoutValidation(header.Key, header.Value);
        }

        if (body is not null)
        {
            retry.Content = new ByteArrayContent(body);
            retry.Content.Headers.ContentType = mediaType;
        }

        Authorize(retry);
        return await base.SendAsync(retry, cancellationToken);
    }

    private void Authorize(HttpRequestMessage request)
    {
        if (tokens.Access is not null)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", tokens.Access);
        }
    }
}
