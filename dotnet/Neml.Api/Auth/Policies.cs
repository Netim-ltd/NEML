// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using Neml.Domain.Enums;

namespace Neml.Api.Auth;

/// <summary>
/// Role claim values of NEML_SPEC.md 5.5. They are the same strings as the users.role
/// column, so a token and a database row always agree.
/// </summary>
public static class Roles
{
    public const string Owner = "owner";
    public const string Operator = "operator";
    public const string Viewer = "viewer";

    public static string Name(UserRole role) => role switch
    {
        UserRole.Owner => Owner,
        UserRole.Operator => Operator,
        _ => Viewer,
    };
}

/// <summary>Authorization policy names. Level 4 approval is owner-only (spec 5.5).</summary>
public static class Policies
{
    /// <summary>owner + operator: may queue commands and decide approvals.</summary>
    public const string Operator = "neml.operator";

    /// <summary>owner only: settings that change what the lab decides on its own.</summary>
    public const string Owner = "neml.owner";

    /// <summary>Resource based: evaluated against the approval being decided.</summary>
    public const string ApprovalDecision = "neml.approval.decision";

    /// <summary>Lab bridge, API key + IP restricted (spec 5.5).</summary>
    public const string Bridge = "neml.bridge";
}

/// <summary>Rate limit policy names for spec 5.5 (100 requests/min/user, 10 commands/min).</summary>
public static class RateLimits
{
    public const int RequestsPerMinute = 100;
    public const int CommandsPerMinute = 10;

    /// <summary>Applied on every endpoint that writes to the command queue.</summary>
    public const string Commands = "neml.commands";
}
