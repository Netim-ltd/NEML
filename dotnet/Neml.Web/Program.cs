// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Microsoft.AspNetCore.Components.Web;
using Microsoft.AspNetCore.Components.WebAssembly.Hosting;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.JSInterop;
using Neml.Web;
using Neml.Web.Services;

var builder = WebAssemblyHostBuilder.CreateDefault(args);
builder.RootComponents.Add<App>("#app");
builder.RootComponents.Add<HeadOutlet>("head::after");

// The WASM bundle is served by Neml.Api, so the API lives on the same origin.
var apiBase = new Uri(builder.HostEnvironment.BaseAddress);

builder.Services.AddScoped(sp => new TokenStore(
    sp.GetRequiredService<IJSRuntime>(),
    new HttpClient { BaseAddress = apiBase }));

builder.Services.AddScoped(sp => new ApiClient(
    new HttpClient(new AuthHandler(sp.GetRequiredService<TokenStore>()) { InnerHandler = new HttpClientHandler() })
    {
        BaseAddress = apiBase,
    }));

builder.Services.AddScoped(sp => new AssistantState(sp.GetRequiredService<ApiClient>()));
builder.Services.AddScoped(sp => new LiveClient(sp.GetRequiredService<TokenStore>(), apiBase));

await builder.Build().RunAsync();
