// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using FluentValidation;
using Neml.Api.Bridge;
using Neml.Api.Contracts;
using Neml.Domain.Dtos;
using Neml.Infrastructure.Security;

namespace Neml.Api.Validators;

// One validator per spec 9.3 request body. The enum-typed fields need no rule of their own:
// they are the spec 7 CHECK sets and a value outside them fails to bind at all.

/// <summary>Shared predicates.</summary>
public static class Is
{
    /// <summary>jsonb columns hold an object, not a bare scalar or array.</summary>
    public static bool JsonObject(JsonDocument? document) =>
        document is not null && document.RootElement.ValueKind == JsonValueKind.Object;

    /// <summary>
    /// The same for a nullable jsonb column. A client that spells an absent value as an explicit
    /// null gets a JsonDocument holding null rather than a null reference, so "is not null" alone
    /// would reject every untagged telemetry sample the lab sends.
    /// </summary>
    public static bool OptionalJsonObject(JsonDocument? document) =>
        document is null || document.RootElement.ValueKind is JsonValueKind.Null or JsonValueKind.Object;
}

public sealed class LoginRequestValidator : AbstractValidator<LoginRequest>
{
    public LoginRequestValidator()
    {
        RuleFor(x => x.Email).NotEmpty().EmailAddress().MaximumLength(320);

        // Spec 5.5: minimum 12 characters.
        RuleFor(x => x.Password).NotEmpty().MinimumLength(PasswordHasher.MinimumLength).MaximumLength(256);
    }
}

public sealed class RefreshRequestValidator : AbstractValidator<RefreshRequest>
{
    public RefreshRequestValidator() => RuleFor(x => x.Refresh).NotEmpty().MaximumLength(512);
}

public sealed class LogoutRequestValidator : AbstractValidator<LogoutRequest>
{
    public LogoutRequestValidator() => RuleFor(x => x.Refresh).NotEmpty().MaximumLength(512);
}

public sealed class RegisterDeviceRequestValidator : AbstractValidator<RegisterDeviceRequest>
{
    public RegisterDeviceRequestValidator() => RuleFor(x => x.PushToken).NotEmpty().MaximumLength(4096);
}

public sealed class EstopRequestValidator : AbstractValidator<EstopRequest>
{
    public EstopRequestValidator() => RuleFor(x => x.Reason).NotEmpty().MaximumLength(500);
}

public sealed class CancelRequestValidator : AbstractValidator<CancelRequest>
{
    public CancelRequestValidator() => RuleFor(x => x.Reason).MaximumLength(500);
}

public sealed class CreateTaskRequestValidator : AbstractValidator<CreateTaskRequest>
{
    public CreateTaskRequestValidator()
    {
        RuleFor(x => x.Title).NotEmpty().MaximumLength(200);
        RuleFor(x => x.Source).NotEmpty().MaximumLength(100);

        // tasks.priority is NUMERIC(6,3) — spec 7.
        RuleFor(x => x.Priority).InclusiveBetween(0m, 999.999m);
        RuleFor(x => x.RobotId).MaximumLength(64);
        RuleFor(x => x.Spec).Must(Is.JsonObject).WithMessage("spec must be a JSON object");
        RuleFor(x => x.Deadline).GreaterThan(_ => DateTimeOffset.UtcNow).When(x => x.Deadline.HasValue);
    }
}

public sealed class UpdateTaskRequestValidator : AbstractValidator<UpdateTaskRequest>
{
    public UpdateTaskRequestValidator()
    {
        RuleFor(x => x).Must(x => x.Title is not null || x.Priority is not null || x.State is not null
                || x.RobotId is not null || x.Deadline is not null)
            .WithMessage("at least one field must be supplied");
        RuleFor(x => x.Title).NotEmpty().MaximumLength(200).When(x => x.Title is not null);
        RuleFor(x => x.Priority!.Value).InclusiveBetween(0m, 999.999m).When(x => x.Priority.HasValue);
        RuleFor(x => x.RobotId).MaximumLength(64);
    }
}

public sealed class BrainCommandRequestValidator : AbstractValidator<BrainCommandRequest>
{
    public BrainCommandRequestValidator() => RuleFor(x => x.Text).NotEmpty().MaximumLength(4000);
}

public sealed class CreateCampaignRequestValidator : AbstractValidator<CreateCampaignRequest>
{
    public CreateCampaignRequestValidator()
    {
        RuleFor(x => x.Name).NotEmpty().MaximumLength(200);
        RuleFor(x => x.Objective).NotEmpty().MaximumLength(2000);
        RuleFor(x => x.Weights).Must(Is.JsonObject).WithMessage("weights must be a JSON object");
        RuleFor(x => x.Budget).Must(Is.JsonObject).WithMessage("budget must be a JSON object");
    }
}

public sealed class ApprovalDecisionRequestValidator : AbstractValidator<ApprovalDecisionRequest>
{
    public ApprovalDecisionRequestValidator() => RuleFor(x => x.Note).MaximumLength(1000);
}

public sealed class TelemetryBatchRequestValidator : AbstractValidator<TelemetryBatchRequest>
{
    public TelemetryBatchRequestValidator()
    {
        RuleFor(x => x.Samples).NotEmpty();
        RuleFor(x => x.Samples.Count).LessThanOrEqualTo(10_000);
        RuleForEach(x => x.Samples).ChildRules(sample =>
        {
            sample.RuleFor(s => s.RobotId).NotEmpty().MaximumLength(64);
            sample.RuleFor(s => s.Metric).NotEmpty().MaximumLength(128);
            sample.RuleFor(s => s.Value).Must(double.IsFinite).WithMessage("value must be finite");
            sample.RuleFor(s => s.Tags).Must(Is.OptionalJsonObject).WithMessage("tags must be a JSON object");
        });
    }
}

public sealed class BridgeEventsRequestValidator : AbstractValidator<BridgeEventsRequest>
{
    public BridgeEventsRequestValidator()
    {
        RuleFor(x => x.Events).NotEmpty();
        RuleFor(x => x.Events.Count).LessThanOrEqualTo(1000);
        RuleForEach(x => x.Events).ChildRules(envelope =>
        {
            envelope.RuleFor(e => e.V).Equal(1);

            // Spec 3.1: seq is monotonic and the key is what makes a replay a no-op.
            envelope.RuleFor(e => e.Seq).GreaterThan(0);
            envelope.RuleFor(e => e.IdempotencyKey).NotEmpty().MaximumLength(128);
            envelope.RuleFor(e => e.Type).Must(BridgeMessage.FromLab.Contains)
                .WithMessage($"type must be one of: {string.Join(", ", BridgeMessage.FromLab)}");
            envelope.RuleFor(e => e.Payload).NotNull();
        });
    }
}
