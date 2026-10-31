// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;

namespace Neml.Api.Contracts;

// Only what NEML_SPEC.md 9.3 needs and Neml.Domain.Dtos does not already carry.
// Everything else on the wire is a Neml.Domain.Dtos record, reused as is.

/// <summary>
/// Answer to every write in spec 9.3. Spec 19 risk 11: this server can never drive a robot,
/// it can only add a row to the command queue, so a write returns a queue receipt and never
/// a completed action. State is the commands.state text of spec 7.
/// </summary>
public record CommandAccepted(Guid CommandId, string State, long Seq);

/// <summary>GET /brain/command/{id} — how a queued command ended up.</summary>
public record CommandDto(
    Guid CommandId,
    long Seq,
    string Kind,
    string State,
    JsonDocument? Result,
    DateTimeOffset CreatedAt,
    DateTimeOffset? AppliedAt);

/// <summary>POST /robots/{id}/estop</summary>
public record EstopRequest(string Reason);

/// <summary>POST /tasks/{id}/cancel and POST /print-jobs/{id}/cancel</summary>
public record CancelRequest(string? Reason);

/// <summary>
/// Enum to the exact text of its spec 7 CHECK constraint and back. The enums carry
/// [JsonStringEnumMemberName], so serializing through System.Text.Json is the single source
/// of truth and no second table of strings can drift from the database.
/// </summary>
public static class EnumText
{
    public static string Of<T>(T value)
        where T : struct, Enum => JsonSerializer.Serialize(value).Trim('"');

    public static bool TryParse<T>(string? text, out T value)
        where T : struct, Enum
    {
        try
        {
            value = JsonSerializer.Deserialize<T>($"\"{text}\"");
            return true;
        }
        catch (JsonException)
        {
            value = default;
            return false;
        }
    }
}
