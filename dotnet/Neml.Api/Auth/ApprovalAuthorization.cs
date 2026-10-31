// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;

namespace Neml.Api.Auth;

/// <summary>The approval being decided. Only the level matters for authorization.</summary>
public sealed record ApprovalResource(Guid Id, int Level);

public sealed class ApprovalDecisionRequirement : IAuthorizationRequirement;

/// <summary>
/// Spec 5.5: approval authority belongs to owner and operator only, and level 4
/// (MANUFACTURE) is restricted to owner. Enforced here so no controller can skip it.
/// </summary>
public sealed class ApprovalDecisionHandler
    : AuthorizationHandler<ApprovalDecisionRequirement, ApprovalResource>
{
    protected override Task HandleRequirementAsync(
        AuthorizationHandlerContext context,
        ApprovalDecisionRequirement requirement,
        ApprovalResource resource)
    {
        var role = context.User.FindFirstValue(ClaimTypes.Role);
        var allowed = role switch
        {
            Roles.Owner => true,
            Roles.Operator => resource.Level < 4,
            _ => false,
        };

        if (allowed)
        {
            context.Succeed(requirement);
        }

        return Task.CompletedTask;
    }
}
