// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;
using FluentValidation;
using Neml.Api.Bridge;
using Neml.Api.Contracts;
using Neml.Api.Validators;
using Neml.Domain.Dtos;
using Neml.Domain.Enums;

namespace Neml.Tests;

/// <summary>
/// Every §9.3 request body crosses the trust boundary through one of these validators, so each
/// one gets both halves: the request that must pass and the one that must not.
/// </summary>
public sealed class ValidatorTests
{
    private static JsonDocument Json(string raw) => JsonDocument.Parse(raw);

    private static void Accepts<T>(AbstractValidator<T> validator, T request) =>
        Assert.True(validator.Validate(request).IsValid, string.Join("; ", validator.Validate(request).Errors));

    private static void Refuses<T>(AbstractValidator<T> validator, T request) =>
        Assert.False(validator.Validate(request).IsValid);

    // ---------- auth (§5.5) ----------

    [Fact]
    public void Login_needs_an_address_and_a_twelve_character_password()
    {
        var validator = new LoginRequestValidator();

        Accepts(validator, new LoginRequest("mg@neml.local", "correct-horse-battery"));

        Refuses(validator, new LoginRequest("", "correct-horse-battery"));
        Refuses(validator, new LoginRequest("not-an-address", "correct-horse-battery"));
        Refuses(validator, new LoginRequest("mg@neml.local", "short"));            // §5.5 minimum 12.
        Refuses(validator, new LoginRequest("mg@neml.local", new string('x', 257)));
    }

    [Fact]
    public void Refresh_and_logout_need_a_token_of_sane_length()
    {
        Accepts(new RefreshRequestValidator(), new RefreshRequest("token"));
        Refuses(new RefreshRequestValidator(), new RefreshRequest(""));
        Refuses(new RefreshRequestValidator(), new RefreshRequest(new string('t', 513)));

        Accepts(new LogoutRequestValidator(), new LogoutRequest("token"));
        Refuses(new LogoutRequestValidator(), new LogoutRequest(""));
        Refuses(new LogoutRequestValidator(), new LogoutRequest(new string('t', 513)));
    }

    [Fact]
    public void Device_registration_needs_a_push_token()
    {
        var validator = new RegisterDeviceRequestValidator();

        Accepts(validator, new RegisterDeviceRequest(DevicePlatform.Android, "fcm-token"));

        Refuses(validator, new RegisterDeviceRequest(DevicePlatform.Ios, null));
        Refuses(validator, new RegisterDeviceRequest(DevicePlatform.Web, new string('t', 4097)));
    }

    // ---------- robots and tasks ----------

    [Fact]
    public void Estop_needs_a_reason_and_cancel_only_bounds_one()
    {
        Accepts(new EstopRequestValidator(), new EstopRequest("battery on fire"));
        Refuses(new EstopRequestValidator(), new EstopRequest(""));
        Refuses(new EstopRequestValidator(), new EstopRequest(new string('r', 501)));

        Accepts(new CancelRequestValidator(), new CancelRequest(null));      // Reason is optional here.
        Accepts(new CancelRequestValidator(), new CancelRequest("no longer needed"));
        Refuses(new CancelRequestValidator(), new CancelRequest(new string('r', 501)));
    }

    [Fact]
    public void Create_task_matches_the_tasks_column_widths()
    {
        var validator = new CreateTaskRequestValidator();
        CreateTaskRequest Valid() => new("survey", TaskKind.Human, "user:mg", 10m, "R01", Json("{}"), null);

        Accepts(validator, Valid());
        Accepts(validator, Valid() with { Deadline = DateTimeOffset.UtcNow.AddHours(1) });

        Refuses(validator, Valid() with { Title = "" });
        Refuses(validator, Valid() with { Title = new string('t', 201) });
        Refuses(validator, Valid() with { Source = "" });
        Refuses(validator, Valid() with { Priority = -1m });                  // NUMERIC(6,3), §7.
        Refuses(validator, Valid() with { Priority = 1000m });
        Refuses(validator, Valid() with { RobotId = new string('r', 65) });
        Refuses(validator, Valid() with { Spec = Json("[]") });               // jsonb holds an object.
        Refuses(validator, Valid() with { Spec = Json("3") });
        Refuses(validator, Valid() with { Deadline = DateTimeOffset.UtcNow.AddHours(-1) });
    }

    [Fact]
    public void Update_task_refuses_an_empty_patch()
    {
        var validator = new UpdateTaskRequestValidator();

        Accepts(validator, new UpdateTaskRequest("renamed", null, null, null, null));
        Accepts(validator, new UpdateTaskRequest(null, null, TaskState.Cancelled, null, null));

        Refuses(validator, new UpdateTaskRequest(null, null, null, null, null));
        Refuses(validator, new UpdateTaskRequest("", null, null, null, null));
        Refuses(validator, new UpdateTaskRequest(null, 1000m, null, null, null));
        Refuses(validator, new UpdateTaskRequest(null, null, null, new string('r', 65), null));
    }

    // ---------- brain and campaigns ----------

    [Fact]
    public void Brain_command_text_is_bounded()
    {
        var validator = new BrainCommandRequestValidator();

        Accepts(validator, new BrainCommandRequest("cancel task 7"));
        Refuses(validator, new BrainCommandRequest(""));
        Refuses(validator, new BrainCommandRequest(new string('t', 4001)));
    }

    [Fact]
    public void Campaign_weights_and_budget_must_be_json_objects()
    {
        var validator = new CreateCampaignRequestValidator();
        CreateCampaignRequest Valid() => new("gen 4", "walk further", Json("""{"speed":1}"""), Json("""{"gpu_h":10}"""));

        Accepts(validator, Valid());

        Refuses(validator, Valid() with { Name = "" });
        Refuses(validator, Valid() with { Objective = new string('o', 2001) });
        Refuses(validator, Valid() with { Weights = Json("[]") });
        Refuses(validator, Valid() with { Budget = Json("null") });
    }

    [Fact]
    public void Approval_note_is_bounded()
    {
        Accepts(new ApprovalDecisionRequestValidator(), new ApprovalDecisionRequest(null));
        Refuses(new ApprovalDecisionRequestValidator(), new ApprovalDecisionRequest(new string('n', 1001)));
    }

    // ---------- bridge (§9.5) ----------

    [Fact]
    public void A_telemetry_batch_is_checked_sample_by_sample()
    {
        var validator = new TelemetryBatchRequestValidator();
        TelemetrySample Sample() => new(DateTimeOffset.UtcNow, "R01", "battery_soc", 42, null);

        Accepts(validator, new TelemetryBatchRequest([Sample()]));
        Accepts(validator, new TelemetryBatchRequest([Sample() with { Tags = Json("""{"unit":"%"}""") }]));

        Refuses(validator, new TelemetryBatchRequest([]));
        Refuses(validator, new TelemetryBatchRequest([Sample() with { RobotId = "" }]));
        Refuses(validator, new TelemetryBatchRequest([Sample() with { Metric = new string('m', 129) }]));
        Refuses(validator, new TelemetryBatchRequest([Sample() with { Value = double.NaN }]));
        Refuses(validator, new TelemetryBatchRequest([Sample() with { Value = double.PositiveInfinity }]));
        Refuses(validator, new TelemetryBatchRequest([Sample() with { Tags = Json("[]") }]));

        // A client that spells "no tags" as an explicit null must still get through: that is what
        // the lab bridge puts on the wire for an untagged sample.
        Accepts(validator, new TelemetryBatchRequest([Sample() with { Tags = Json("null") }]));
    }

    [Fact]
    public void A_bridge_event_must_carry_a_known_type_and_a_monotonic_seq()
    {
        var validator = new BridgeEventsRequestValidator();
        BridgeEnvelope Envelope() => new(1, 7, DateTimeOffset.UtcNow, BridgeMessage.Event, "key-1", Json("{}"));

        Accepts(validator, new BridgeEventsRequest([Envelope()]));

        Refuses(validator, new BridgeEventsRequest([]));
        Refuses(validator, new BridgeEventsRequest([Envelope() with { V = 2 }]));
        Refuses(validator, new BridgeEventsRequest([Envelope() with { Seq = 0 }]));
        Refuses(validator, new BridgeEventsRequest([Envelope() with { IdempotencyKey = "" }]));
        Refuses(validator, new BridgeEventsRequest([Envelope() with { IdempotencyKey = new string('k', 129) }]));

        // §9.5: command and approval_decision travel server to lab, so a node may not send them.
        Refuses(validator, new BridgeEventsRequest([Envelope() with { Type = BridgeMessage.Command }]));
        Refuses(validator, new BridgeEventsRequest([Envelope() with { Type = "invented" }]));
    }
}
