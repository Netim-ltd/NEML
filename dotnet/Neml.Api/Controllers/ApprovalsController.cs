// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Security.Claims;
using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.JsonWebTokens;
using Neml.Api.Auth;
using Neml.Api.Contracts;
using Neml.Api.Hubs;
using Neml.Api.Services;
using Neml.Domain.Dtos;
using Neml.Domain.Enums;
using Neml.Infrastructure.Persistence;

namespace Neml.Api.Controllers;

/// <summary>
/// Spec 9.3 Approvals. Who may decide is settled by the ApprovalDecision policy (spec 5.5:
/// owner and operator, level 4 owner only), never by a branch in here. The decision is
/// recorded locally and then handed to the lab through the command queue.
/// </summary>
[Route("api/v1/approvals")]
[Tags("Approvals")]
public sealed class ApprovalsController(
    NemlDbContext db,
    CommandQueue queue,
    LiveBroadcaster live,
    IAuthorizationService authorization)
    : NemlController
{
    /// <summary>pending=true hides everything already decided or timed out.</summary>
    [HttpGet]
    [ProducesResponseType<IReadOnlyList<ApprovalResponse>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<ApprovalResponse>>> List(
        [FromQuery] bool pending, CancellationToken ct)
    {
        var now = DateTimeOffset.UtcNow;
        var rows = db.Approvals.AsNoTracking();
        if (pending)
        {
            rows = rows.Where(a => a.Decision == null && a.ExpiresAt > now);
        }

        return await Project(rows.OrderByDescending(a => a.RequestedAt)).ToListAsync(ct);
    }

    /// <summary>Detail. payload carries the summary and the preview PNG path (spec 7).</summary>
    [HttpGet("{id:guid}")]
    [ProducesResponseType<ApprovalResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<ApprovalResponse>> Get(Guid id, CancellationToken ct)
    {
        var approval = await Project(db.Approvals.AsNoTracking().Where(a => a.Id == id)).FirstOrDefaultAsync(ct);
        return approval is null ? NotFound() : approval;
    }

    [HttpPost("{id:guid}/approve")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status409Conflict)]
    public Task<ActionResult<CommandAccepted>> Approve(
        Guid id, ApprovalDecisionRequest request, CancellationToken ct) =>
        DecideAsync(id, ApprovalDecision.Approved, request.Note, ct);

    [HttpPost("{id:guid}/reject")]
    [Authorize(Policy = Policies.Operator)]
    [EnableRateLimiting(RateLimits.Commands)]
    [ProducesResponseType<CommandAccepted>(StatusCodes.Status202Accepted)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status409Conflict)]
    public Task<ActionResult<CommandAccepted>> Reject(
        Guid id, ApprovalDecisionRequest request, CancellationToken ct) =>
        DecideAsync(id, ApprovalDecision.Rejected, request.Note, ct);

    private static IQueryable<ApprovalResponse> Project(IQueryable<Domain.Entities.Approval> approvals) =>
        approvals.Select(a => new ApprovalResponse(
            a.Id, a.Level, a.SubjectKind, a.SubjectId, a.Payload, a.RequestedAt, a.ExpiresAt,
            a.DecidedAt, a.DecidedBy, a.Decision, a.Note));

    private async Task<ActionResult<CommandAccepted>> DecideAsync(
        Guid id, ApprovalDecision decision, string? note, CancellationToken ct)
    {
        var approval = await db.Approvals.AsNoTracking()
            .Where(a => a.Id == id)
            .Select(a => new { a.Id, a.Level, a.DecidedAt, a.Decision, a.ExpiresAt })
            .FirstOrDefaultAsync(ct);

        if (approval is null)
        {
            return NotFound();
        }

        // Level 4 (MANUFACTURE) is owner only — spec 5.5, decided by the policy handler.
        var check = await authorization.AuthorizeAsync(
            User, new ApprovalResource(approval.Id, approval.Level), Policies.ApprovalDecision);
        if (!check.Succeeded)
        {
            return Forbid();
        }

        if (approval.DecidedAt is not null)
        {
            return Problem($"approval already {approval.Decision}", statusCode: StatusCodes.Status409Conflict);
        }

        var now = DateTimeOffset.UtcNow;
        if (approval.ExpiresAt <= now)
        {
            return Problem("approval expired", statusCode: StatusCodes.Status409Conflict);
        }

        var by = User.FindFirstValue(JwtRegisteredClaimNames.Email) ?? UserId.ToString();
        var applied = await db.Approvals
            .Where(a => a.Id == id && a.Decision == null && a.ExpiresAt > now)
            .ExecuteUpdateAsync(s => s
                .SetProperty(a => a.Decision, (ApprovalDecision?)decision)
                .SetProperty(a => a.DecidedAt, (DateTimeOffset?)now)
                .SetProperty(a => a.DecidedBy, by)
                .SetProperty(a => a.Note, note), ct);

        if (applied == 0)
        {
            return Problem("approval already decided or expired", statusCode: StatusCodes.Status409Conflict);
        }

        var text = EnumText.Of(decision);
        await live.ApprovalDecidedAsync(new ApprovalDecidedPayload(id, text, by));

        // The lab hears about it through the queue, like every other instruction (spec 3.1).
        var payload = JsonSerializer.Serialize(
            new { approvalId = id, decision = text, by, note }, JsonSerializerOptions.Web);
        return Accepted(await queue.EnqueueAsync(
            UserId, CommandQueue.ApprovalDecision, payload, IdempotencyKey(), ct));
    }
}
