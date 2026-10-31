// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Net;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Options;

namespace Neml.Api.Auth;

/// <summary>
/// Spec 5.5: the lab bridge authenticates with a long lived API key plus an IP
/// restriction, and names itself in the X-NEML-Node header. There is no user behind
/// this scheme and it grants no user role, so it can never satisfy Policies.Operator.
/// </summary>
public sealed class BridgeAuthenticationHandler(
    IOptionsMonitor<AuthenticationSchemeOptions> options,
    ILoggerFactory logger,
    UrlEncoder encoder,
    IConfiguration configuration)
    : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
{
    public const string SchemeName = "Bridge";
    public const string KeyHeader = "X-NEML-Key";
    public const string NodeHeader = "X-NEML-Node";
    public const string NodeClaim = "neml:node";

    private readonly IConfiguration _configuration = configuration;

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        var section = _configuration.GetSection("Bridge");

        var expectedKey = section["ApiKey"];
        if (string.IsNullOrEmpty(expectedKey) || expectedKey == "CHANGEME")
        {
            return Task.FromResult(AuthenticateResult.Fail("Bridge:ApiKey is not configured."));
        }

        if (!Request.Headers.TryGetValue(KeyHeader, out var presented) ||
            !FixedTimeEquals(presented.ToString(), expectedKey))
        {
            return Task.FromResult(AuthenticateResult.Fail("Invalid bridge API key."));
        }

        if (!Request.Headers.TryGetValue(NodeHeader, out var nodeHeader))
        {
            return Task.FromResult(AuthenticateResult.Fail($"{NodeHeader} header is required."));
        }

        var node = nodeHeader.ToString();
        var knownNodes = section.GetSection("NodeIds").Get<string[]>() ?? [];
        if (knownNodes.Length > 0 && !knownNodes.Contains(node, StringComparer.Ordinal))
        {
            return Task.FromResult(AuthenticateResult.Fail($"Unknown node '{node}'."));
        }

        var allowedIps = section.GetSection("AllowedIps").Get<string[]>() ?? [];
        if (!IsAllowedAddress(Context.Connection.RemoteIpAddress, allowedIps))
        {
            return Task.FromResult(AuthenticateResult.Fail("Remote address is not allowed."));
        }

        var identity = new ClaimsIdentity(
            [new Claim(NodeClaim, node), new Claim(ClaimTypes.Name, $"node:{node}")], SchemeName);
        return Task.FromResult(AuthenticateResult.Success(
            new AuthenticationTicket(new ClaimsPrincipal(identity), SchemeName)));
    }

    /// <summary>Empty allow list means "no IP restriction", which is only for local development.</summary>
    private static bool IsAllowedAddress(IPAddress? remote, string[] allowed)
    {
        if (allowed.Length == 0)
        {
            return true;
        }

        if (remote is null)
        {
            return false;
        }

        foreach (var entry in allowed)
        {
            if (entry.Contains('/', StringComparison.Ordinal)
                    ? IPNetwork.Parse(entry).Contains(remote)
                    : IPAddress.TryParse(entry, out var single) && single.Equals(remote))
            {
                return true;
            }
        }

        return false;
    }

    private static bool FixedTimeEquals(string presented, string expected) =>
        CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(presented), Encoding.UTF8.GetBytes(expected));
}
