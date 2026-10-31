// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Security.Claims;
using System.Threading.RateLimiting;
using FluentValidation;
using FluentValidation.AspNetCore;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.OpenApi;
using Neml.Api.Auth;
using Neml.Api.Bridge;
using Neml.Api.Hubs;
using Neml.Api.Services;
using Neml.Domain.Entities;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;
using Neml.Infrastructure.Repositories;
using CommandQueue = Neml.Api.Services.CommandQueue;
using RefreshTokenStore = Neml.Infrastructure.Security.RefreshTokenStore;
using Serilog;
using Serilog.Formatting.Compact;

var builder = WebApplication.CreateBuilder(args);

// Spec 18.3: structured JSON on stdout, journald collects it.
builder.Services.AddSerilog((_, configuration) => configuration
    .ReadFrom.Configuration(builder.Configuration)
    .Enrich.FromLogContext()
    .WriteTo.Console(new CompactJsonFormatter()));

// Spec 17.3: ConnectionStrings__Default points at neml_cloud.
builder.Services.AddDbContext<NemlDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("Default")));

var jwt = new JwtIssuer(builder.Configuration);
builder.Services.AddSingleton(jwt);
builder.Services.AddSingleton<LabState>();
builder.Services.AddSingleton<PushNotifier>();
builder.Services.AddSingleton<LiveBroadcaster>();
builder.Services.AddScoped<CommandQueue>();
builder.Services.AddScoped<RefreshTokenStore>();
builder.Services.AddScoped<MirrorWriter>();
builder.Services.AddScoped<TaskRepository>();
builder.Services.AddScoped<TelemetryRepository>();
builder.Services.AddScoped<GenomeRepository>();
builder.Services.AddScoped<ApprovalRepository>();
builder.Services.AddTransient<BridgeSession>();
builder.Services.AddHostedService<ApprovalExpiryService>();
builder.Services.AddSingleton<IAuthorizationHandler, ApprovalDecisionHandler>();

builder.Services
    .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        options.TokenValidationParameters = jwt.ValidationParameters;

        // Keep sub/email/role as issued; the default inbound map renames them.
        options.MapInboundClaims = false;
        options.Events = new JwtBearerEvents
        {
            // SignalR cannot set an Authorization header on the websocket handshake, and neither can an
            // image tag asking for a recording.
            OnMessageReceived = context =>
            {
                var token = context.Request.Query["access_token"];
                if (!string.IsNullOrEmpty(token) && context.Request.Path.StartsWithSegments("/hubs") || context.Request.Path.StartsWithSegments("/api/v1/media")
                    || context.Request.Path.StartsWithSegments("/api/v1/models"))
                {
                    context.Token = token;
                }

                return Task.CompletedTask;
            },
        };
    })
    .AddScheme<AuthenticationSchemeOptions, BridgeAuthenticationHandler>(
        BridgeAuthenticationHandler.SchemeName, _ => { });

builder.Services.AddAuthorizationBuilder()
    .AddPolicy(Policies.Operator, policy => policy.RequireRole(Roles.Owner, Roles.Operator))
    .AddPolicy(Policies.Owner, policy => policy.RequireRole(Roles.Owner))
    .AddPolicy(Policies.ApprovalDecision, policy => policy.AddRequirements(new ApprovalDecisionRequirement()))
    .AddPolicy(Policies.Bridge, policy => policy
        .AddAuthenticationSchemes(BridgeAuthenticationHandler.SchemeName)
        .RequireAuthenticatedUser());

// Spec 5.5: 100 requests/min/user, 10 commands/min.
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(context =>
        RateLimitPartition.GetFixedWindowLimiter(PartitionKey(context), _ => new FixedWindowRateLimiterOptions
        {
            PermitLimit = RateLimits.RequestsPerMinute,
            Window = TimeSpan.FromMinutes(1),
        }));
    options.AddPolicy(RateLimits.Commands, context =>
        RateLimitPartition.GetFixedWindowLimiter(PartitionKey(context), _ => new FixedWindowRateLimiterOptions
        {
            PermitLimit = RateLimits.CommandsPerMinute,
            Window = TimeSpan.FromMinutes(1),
        }));
});

// The Flutter client and the hosted Blazor app are the only browsers that need this.
builder.Services.AddCors(options => options.AddDefaultPolicy(policy => policy
    .WithOrigins(builder.Configuration.GetSection("Cors:Origins").Get<string[]>() ?? [])
    .AllowAnyHeader()
    .AllowAnyMethod()
    .AllowCredentials()));

// Spec 9.3: "Hata formati RFC 7807 application/problem+json" — the media type, not only the
// body. ControllerBase.Problem() and the FluentValidation 400 build an RFC 7807 body but leave
// the content type to negotiation, which settles on application/json.
builder.Services.AddControllers(options => options.Filters.Add(new ProblemJsonMediaType()));

// Covers every status code that carries no body of its own (401, 403, 404, 429), so no error
// path leaves the API in a different shape.
builder.Services.AddProblemDetails(options => options.CustomizeProblemDetails = context =>
{
    // ASP.NET Core's defaults table has no 429 row, so a rate limited caller (spec 5.5) would
    // otherwise get a body with neither type nor title.
    context.ProblemDetails.Title ??= ReasonPhrases.GetReasonPhrase(context.HttpContext.Response.StatusCode);
    context.ProblemDetails.Type ??= "about:blank";
});
builder.Services.AddFluentValidationAutoValidation();
builder.Services.AddValidatorsFromAssemblyContaining<Program>();
builder.Services.AddSignalR();
builder.Services.AddResponseCompression(options =>
{
    // Models and boards are the big downloads of the panel; they compress to a half or a third.
    options.EnableForHttps = true;
    options.MimeTypes = Microsoft.AspNetCore.ResponseCompression.ResponseCompressionDefaults.MimeTypes.Concat(
        ["model/stl", "model/step", "application/x-neml-mesh", "image/svg+xml", "text/csv"]);
});
builder.Services.AddHealthChecks().AddCheck<DbHealthCheck>("neml_cloud");
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(options =>
{
    options.SwaggerDoc("v1", new OpenApiInfo { Title = "NEML API", Version = "v1" });

    // T-052: the XML comments on every action are part of "Swagger is complete".
    var xml = Path.Combine(AppContext.BaseDirectory, $"{typeof(Program).Assembly.GetName().Name}.xml");
    if (File.Exists(xml))
    {
        options.IncludeXmlComments(xml, true);
    }

    options.AddSecurityDefinition(JwtBearerDefaults.AuthenticationScheme, new OpenApiSecurityScheme
    {
        Type = SecuritySchemeType.Http,
        Scheme = "bearer",
        BearerFormat = "JWT",
        In = ParameterLocation.Header,
        Description = "JWT access token (spec 5.5).",
    });
    options.DocumentFilter<LlmDocsFilter>();
    options.AddSecurityDefinition(BridgeAuthenticationHandler.SchemeName, new OpenApiSecurityScheme
    {
        Type = SecuritySchemeType.ApiKey,
        Name = BridgeAuthenticationHandler.KeyHeader,
        In = ParameterLocation.Header,
        Description = "Long lived lab bridge key; also requires the X-NEML-Node header (spec 5.5).",
    });
});

var app = builder.Build();

// Run schema changes as a separate one-shot container before replacing the API.
if (args.Contains("--migrate", StringComparer.Ordinal))
{
    using var scope = app.Services.CreateScope();
    await scope.ServiceProvider.GetRequiredService<NemlDbContext>().Database.MigrateAsync();
    return;
}
if (args.Contains("--provision-owner", StringComparer.Ordinal))
{
    var email = Environment.GetEnvironmentVariable("NEML_OWNER_EMAIL")
        ?? throw new InvalidOperationException("NEML_OWNER_EMAIL is required.");
    var password = Environment.GetEnvironmentVariable("NEML_OWNER_PASSWORD")
        ?? throw new InvalidOperationException("NEML_OWNER_PASSWORD is required.");
    if (!email.Contains('@') || password.Length < PasswordHasher.MinimumLength)
    {
        throw new InvalidOperationException("Owner email or password is invalid.");
    }
    using var scope = app.Services.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<NemlDbContext>();
    if (!await db.Users.AnyAsync(user => user.Email == email))
    {
        db.Users.Add(new User
        {
            Id = Guid.NewGuid(),
            Email = email,
            PasswordHash = PasswordHasher.Hash(password),
            Role = UserRole.Owner,
            CreatedAt = DateTimeOffset.UtcNow,
        });
        await db.SaveChangesAsync();
    }
    return;
}

app.UseSerilogRequestLogging();

// Before everything it has to cover, including the rate limiter's 429 (spec 9.3).
app.UseStatusCodePages();
// TLS is terminated by the shared nginx proxy in production. Do not redirect
// an internal HTTP request back to HTTPS on the container's unbound port.
if (app.Environment.IsDevelopment())
{
    app.UseHttpsRedirection();
}
app.UseWebSockets();

// Blazor WebAssembly is served from this same host (spec 2).
app.UseResponseCompression();
app.UseBlazorFrameworkFiles();
app.UseStaticFiles();

app.UseRouting();
app.UseCors();
app.UseAuthentication();
app.UseAuthorization();
app.UseRateLimiter();

app.UseSwagger();
app.UseSwaggerUI();

app.MapControllers();
app.MapHub<LiveHub>("/hubs/live");
app.MapHealthChecks("/health").AllowAnonymous();
app.MapFallbackToFile("index.html");

app.Run();

// Rate limits are per user; an unauthenticated caller is partitioned by address.
static string PartitionKey(HttpContext context) =>
    context.User.FindFirstValue(JwtRegisteredClaimNames.Sub)
    ?? context.Connection.RemoteIpAddress?.ToString()
    ?? "anonymous";

/// <summary>
/// Pins the spec 9.3 media type on every MVC result that carries an RFC 7807 body. Without it
/// the body is right and the Content-Type is application/json, which the mobile and web
/// clients use to tell an error apart from a payload.
/// </summary>
internal sealed class ProblemJsonMediaType : IResultFilter, IOrderedFilter
{
    /// <summary>
    /// Last, so it wins over the controllers' [Produces("application/json")] — that attribute
    /// documents the success shape in Swagger but overwrites the media type of an error too.
    /// </summary>
    public int Order => int.MaxValue;

    public void OnResultExecuting(ResultExecutingContext context)
    {
        if (context.Result is ObjectResult { Value: ProblemDetails } result)
        {
            result.ContentTypes.Clear();
            result.ContentTypes.Add("application/problem+json");
        }
    }

    public void OnResultExecuted(ResultExecutedContext context)
    {
    }
}

/// <summary>Entry point, made public so Neml.Tests can host the API with WebApplicationFactory.</summary>
public partial class Program;
