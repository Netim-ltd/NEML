// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.OpenApi;
using Swashbuckle.AspNetCore.SwaggerGen;

namespace Neml.Api.Services;

/// <summary>
/// Describes the OpenAI compatible language model door in this API's Swagger. The door itself is not served by this
/// process: the API has no route towards the lab (spec 3.1), so the host's reverse proxy sends /v1/* straight to the
/// neml gateway service, which checks the key. Documentation only, no code path.
/// </summary>
public sealed class LlmDocsFilter : IDocumentFilter
{
    public void Apply(OpenApiDocument swaggerDoc, DocumentFilterContext context)
    {
        swaggerDoc.Paths ??= [];
        Add(swaggerDoc, "/v1/models", HttpMethod.Get, "The chat model and the embedder that are served.");
        Add(swaggerDoc, "/v1/chat/completions", HttpMethod.Post,
            "Chat completion (OpenAI schema). \"stream\": true answers with server-sent events. max_tokens is capped at 2048; one outside request runs at a time.");
        Add(swaggerDoc, "/v1/embeddings", HttpMethod.Post,
            "Embeddings (OpenAI schema): \"input\" is a string or up to 64 strings; the vectors have 384 dimensions (model neml-embed).");
    }

    private static void Add(OpenApiDocument doc, string path, HttpMethod method, string summary)
    {
        var operation = new OpenApiOperation
        {
            Summary = summary,
            Tags = new HashSet<OpenApiTagReference> { new("LLM (OpenAI compatible)", doc) },
            Responses = new OpenApiResponses
            {
                ["200"] = new OpenApiResponse { Description = "OpenAI schema response" },
                ["401"] = new OpenApiResponse { Description = "Missing or wrong key (Authorization: Bearer <key>)" },
            },
        };
        doc.Paths.Add(path, new OpenApiPathItem { Operations = new Dictionary<HttpMethod, OpenApiOperation> { [method] = operation } });
    }
}
