// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Reflection;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Routing;
using Neml.Api.Auth;

namespace Neml.Tests;

/// <summary>
/// T-052. The table below is transcribed from NEML_SPEC.md §9.3 and is the contract: a row
/// with no matching controller action, a wrong verb or a wrong authorization fails the run.
/// </summary>
public sealed class EndpointContractTests
{
    /// <summary>Marker for "any authenticated user", i.e. a plain [Authorize].</summary>
    private const string Authenticated = "*";

    /// <summary>Marker for [AllowAnonymous].</summary>
    private const string Anonymous = "-";

    public static readonly (string Method, string Route, string Authorization)[] Spec93 =
    [
        // Auth
        ("POST", "api/v1/auth/login", Anonymous),
        ("POST", "api/v1/auth/refresh", Anonymous),
        ("POST", "api/v1/auth/logout", Authenticated),
        ("POST", "api/v1/auth/devices", Authenticated),

        // Robots
        ("GET", "api/v1/robots", Authenticated),
        ("GET", "api/v1/robots/{id}", Authenticated),
        ("GET", "api/v1/robots/{id}/telemetry", Authenticated),
        ("POST", "api/v1/robots/{id}/estop", Policies.Operator),

        // Tasks
        ("GET", "api/v1/tasks", Authenticated),
        ("GET", "api/v1/tasks/{id}", Authenticated),
        ("POST", "api/v1/tasks", Policies.Operator),
        ("PATCH", "api/v1/tasks/{id}", Policies.Operator),
        ("POST", "api/v1/tasks/{id}/cancel", Policies.Operator),
        ("GET", "api/v1/tasks/{id}/runs", Authenticated),

        // Brain command
        ("POST", "api/v1/brain/command", Policies.Operator),
        ("GET", "api/v1/brain/command/{id}", Authenticated),
        ("GET", "api/v1/brain/status", Authenticated),

        // Training / evolution
        ("GET", "api/v1/campaigns", Authenticated),
        ("GET", "api/v1/campaigns/{id}", Authenticated),
        ("POST", "api/v1/campaigns", Policies.Operator),
        ("POST", "api/v1/campaigns/{id}/stop", Policies.Operator),
        ("GET", "api/v1/campaigns/{id}/generations", Authenticated),
        ("GET", "api/v1/skills", Authenticated),
        ("GET", "api/v1/skills/{key}/versions", Authenticated),
        ("GET", "api/v1/genomes/tree", Authenticated),

        // Approvals
        ("GET", "api/v1/approvals", Authenticated),
        ("GET", "api/v1/approvals/{id}", Authenticated),
        ("POST", "api/v1/approvals/{id}/approve", Policies.Operator),
        ("POST", "api/v1/approvals/{id}/reject", Policies.Operator),

        // Manufacturing
        ("GET", "api/v1/print-jobs", Authenticated),
        ("GET", "api/v1/printers/{id}/status", Authenticated),
        ("POST", "api/v1/print-jobs/{id}/cancel", Policies.Operator),

        // Bridge (lab only, API key). §17.3 pins the address as wss://<host>/bridge/ws, so
        // these three sit at the root rather than under /api/v1. A WebSocket upgrade is an
        // HTTP GET, which is how §9.3's "WS" row is routed.
        ("GET", "bridge/ws", Policies.Bridge),
        ("POST", "bridge/telemetry/batch", Policies.Bridge),
        ("POST", "bridge/events", Policies.Bridge),
    ];

    [ApiFact]
    public void Every_spec_9_3_endpoint_is_routed()
    {
        var actual = Discover();

        var missing = Spec93
            .Where(row => !actual.Any(a => a.Method == row.Method && a.Route == row.Route))
            .Select(row => $"{row.Method} /{row.Route}")
            .ToArray();

        Assert.True(
            missing.Length == 0,
            $"§9.3 endpoints with no controller action:{Environment.NewLine}{string.Join(Environment.NewLine, missing)}");
    }

    [ApiFact]
    public void Every_spec_9_3_endpoint_requires_the_right_authorization()
    {
        var actual = Discover();

        var wrong = new List<string>();
        foreach (var row in Spec93)
        {
            var match = actual.FirstOrDefault(a => a.Method == row.Method && a.Route == row.Route);
            if (string.IsNullOrEmpty(match.Route))
            {
                continue; // Reported by the routing test; do not fail twice for one cause.
            }

            if (match.Authorization != row.Authorization)
            {
                wrong.Add($"{row.Method} /{row.Route}: beklenen '{row.Authorization}', bulunan '{match.Authorization}'");
            }
        }

        Assert.True(
            wrong.Count == 0,
            $"§9.3/§5.5 authorization mismatches:{Environment.NewLine}{string.Join(Environment.NewLine, wrong)}");
    }

    [ApiFact]
    public void No_controller_action_is_left_unauthenticated()
    {
        var open = Discover()
            .Where(a => a.Authorization == Anonymous)
            .Select(a => $"{a.Method} /{a.Route}")
            .Where(route => !Spec93.Any(r => r.Authorization == Anonymous && $"{r.Method} /{r.Route}" == route))
            .ToArray();

        Assert.True(
            open.Length == 0,
            $"Anonymous endpoints outside §9.3 auth/login and auth/refresh:{Environment.NewLine}{string.Join(Environment.NewLine, open)}");
    }

    private static List<(string Method, string Route, string Authorization)> Discover()
    {
        var endpoints = new List<(string Method, string Route, string Authorization)>();

        foreach (var controller in ApiSurface.Controllers)
        {
            var prefix = Declared<RouteAttribute>(controller)?.Template ?? string.Empty;

            foreach (var action in controller.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            {
                foreach (var verb in action.GetCustomAttributes<HttpMethodAttribute>())
                {
                    foreach (var method in verb.HttpMethods)
                    {
                        endpoints.Add((
                            method.ToUpperInvariant(),
                            Normalize(controller, prefix, verb.Template),
                            Authorization(action, controller)));
                    }
                }
            }
        }

        return endpoints;
    }

    /// <summary>Joins the controller and action templates and strips route constraints.</summary>
    private static string Normalize(Type controller, string prefix, string? template)
    {
        var name = controller.Name.EndsWith("Controller", StringComparison.Ordinal)
            ? controller.Name[..^"Controller".Length]
            : controller.Name;

        var joined = string.Join('/', new[] { prefix, template }.Where(p => !string.IsNullOrEmpty(p)))
            .Replace("[controller]", name, StringComparison.OrdinalIgnoreCase)
            .Trim('/');

        // {id:guid} and {id?} both mean "{id}" for contract purposes.
        return Regex.Replace(joined, @"\{(\w+).*?\}", "{$1}").ToLowerInvariant();
    }

    private static string Authorization(MethodInfo action, Type controller)
    {
        if (action.GetCustomAttribute<AllowAnonymousAttribute>() is not null)
        {
            return Anonymous;
        }

        var authorize = action.GetCustomAttributes<AuthorizeAttribute>(inherit: false).FirstOrDefault()
            ?? Declared<AuthorizeAttribute>(controller);

        return authorize is null
            ? Anonymous
            : authorize.Policy ?? authorize.Roles ?? Authenticated;
    }

    /// <summary>
    /// First attribute declared on the type itself, then on its bases. Controllers inherit
    /// [Route("api/v1")] and [Authorize] from NemlController but override both, and MVC gives
    /// the most derived declaration precedence — so plain inherit:true would read the wrong one.
    /// </summary>
    private static T? Declared<T>(Type? type)
        where T : Attribute
    {
        for (; type is not null; type = type.BaseType)
        {
            if (type.GetCustomAttributes<T>(inherit: false).FirstOrDefault() is { } attribute)
            {
                return attribute;
            }
        }

        return null;
    }
}
