// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text.Json;

namespace Neml.Web;

/// <summary>§5.5 role names. The same strings the API's users.role column and JWT claim carry.</summary>
public static class Roles
{
    public const string Owner = "owner";
    public const string Operator = "operator";
    public const string Viewer = "viewer";
}

/// <summary>Why a request cannot be decided from this browser, or <c>None</c>.</summary>
public enum ApprovalBlock
{
    None,
    NotAuthorized,
    OwnerOnly,
    Expired,
    Decided,
    ConfirmationMissing,
}

/// <summary>§5.2 deployment gates as the UI presents them.</summary>
public static class ApprovalLevels
{
    /// <summary>Phrase the operator must type for a level 4 approval (§10.2 screen 10).</summary>
    public const string Level4Phrase = "ONAYLIYORUM";

    /// <summary>§5.2 default window. The server sends expiresAt; this only documents it.</summary>
    public static readonly TimeSpan Timeout = TimeSpan.FromHours(24);

    /// <summary>
    /// Character for character. Whitespace is not trimmed and the comparison is ordinal:
    /// level 4 is MANUFACTURE (§5.2) and §5 never relaxes, so a keyboard that appends a space
    /// keeps the button down instead of rounding in the operator's favour, and Turkish
    /// dotless-i casing cannot widen the match either. The Flutter client pins the same rule
    /// in mobile/lib/features/approvals/approvals_provider.dart — one safety gate, one answer.
    /// </summary>
    public static bool IsLevel4Confirmed(string? typed) =>
        string.Equals(typed, Level4Phrase, StringComparison.Ordinal);

    /// <summary>§5.5: owner and operator decide, and level 4 is owner only.</summary>
    public static bool CanDecide(string? role, int level) => role switch
    {
        Roles.Owner => true,
        Roles.Operator => level < 4,
        _ => false,
    };

    /// <summary>
    /// §5.2: a request that times out is auto-rejected, so the boundary itself counts as
    /// expired — at exactly expiresAt there is no window left to decide in.
    /// </summary>
    public static bool IsExpired(DateTimeOffset expiresAt, DateTimeOffset now) => now >= expiresAt;

    /// <summary>
    /// Why neither decision may be taken. The typed phrase is deliberately not part of it: it
    /// gates approval only, because §10.3 keeps the safe direction open.
    /// </summary>
    public static ApprovalBlock DecisionBlock(Approval approval, string? role, DateTimeOffset now)
    {
        if (approval.Decision is not null)
        {
            return ApprovalBlock.Decided;
        }

        if (IsExpired(approval.ExpiresAt, now))
        {
            return ApprovalBlock.Expired;
        }

        if (CanDecide(role, approval.Level))
        {
            return ApprovalBlock.None;
        }

        // An operator is allowed to decide something, just not this: name the real reason.
        return CanDecide(role, 1) ? ApprovalBlock.OwnerOnly : ApprovalBlock.NotAuthorized;
    }

    /// <summary>The approve button's gate: <see cref="DecisionBlock"/> plus the level 4 phrase.</summary>
    public static ApprovalBlock ApproveBlock(Approval approval, string? role, DateTimeOffset now, string? typed)
    {
        var block = DecisionBlock(approval, role, now);
        if (block != ApprovalBlock.None)
        {
            return block;
        }

        return approval.Level >= 4 && !IsLevel4Confirmed(typed)
            ? ApprovalBlock.ConfirmationMissing
            : ApprovalBlock.None;
    }

    public static string? Reason(ApprovalBlock block) => block switch
    {
        ApprovalBlock.NotAuthorized => "Karar yetkiniz yok — §5.5 onayı sahip ve operatöre bırakır.",
        ApprovalBlock.OwnerOnly => "Seviye 4 yalnızca sahip tarafından karara bağlanır (§5.5).",
        ApprovalBlock.Expired => "Bu istek zaman aşımına uğradı (§5.2) ve otomatik reddedildi.",
        ApprovalBlock.Decided => "Bu istek zaten karara bağlandı.",
        ApprovalBlock.ConfirmationMissing => $"Onaylamak için \"{Level4Phrase}\" metnini birebir yazın.",
        _ => null,
    };

    public static string Label(int level) => level switch
    {
        1 => "BENCH — tekerlekler havada, güç %30",
        2 => "TETHERED — sınırlı alan, e-stop elde",
        3 => "FREE — serbest çalışma",
        4 => "MANUFACTURE — baskı / PCB / firmware",
        _ => "bilinmeyen seviye",
    };

    public static string Countdown(TimeSpan remaining) => remaining <= TimeSpan.Zero
        ? "süresi doldu"
        : $"{(int)remaining.TotalHours:00}:{remaining.Minutes:00}:{remaining.Seconds:00}";
}

/// <summary>
/// §7 approvals.payload is free-form JSON produced by the lab, so the UI reads the cost and
/// time summary of §10.2 screen 10 defensively and shows the raw payload alongside it.
/// </summary>
public static class ApprovalPayload
{
    public static string? Summary(JsonElement? payload) =>
        Text(payload, "summary", "ozet", "description");

    public static string? Text(JsonElement? payload, params string[] names)
    {
        var value = Find(payload, names);
        return value?.ValueKind == JsonValueKind.String ? value.Value.GetString() : null;
    }

    public static double? Number(JsonElement? payload, params string[] names)
    {
        var value = Find(payload, names);
        return value?.ValueKind == JsonValueKind.Number ? value.Value.GetDouble() : null;
    }

    public static string Pretty(JsonElement? payload) => payload is null
        ? "{}"
        : JsonSerializer.Serialize(payload.Value, new JsonSerializerOptions { WriteIndented = true });

    /// <summary>Estimated print time, as §10.2 screen 10 shows it.</summary>
    public static string Hours(double? hours) =>
        hours is null ? "—" : $"{(int)hours.Value} sa {(int)Math.Round(hours.Value % 1 * 60)} dk";

    public static string Grams(double? grams) => grams is null ? "—" : $"{grams.Value:0.#} g";

    public static string Cost(double? cost) => cost is null ? "—" : $"{cost.Value:0.##} ₺";

    private static JsonElement? Find(JsonElement? payload, string[] names)
    {
        if (payload is not { ValueKind: JsonValueKind.Object } root)
        {
            return null;
        }

        foreach (var name in names)
        {
            if (root.TryGetProperty(name, out var value))
            {
                return value;
            }
        }

        return null;
    }
}
