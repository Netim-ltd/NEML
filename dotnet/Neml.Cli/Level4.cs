// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

namespace Neml.Cli;

/// <summary>§5.2 / §10.2 screen 10: level 4 needs a typed confirmation phrase.</summary>
public static class Level4
{
    public const string Phrase = "ONAYLIYORUM";

    /// <summary>Ordinal on purpose: Turkish dotless-i casing must not widen the match.</summary>
    public static bool IsConfirmed(string? typed) =>
        string.Equals(typed?.Trim(), Phrase, StringComparison.Ordinal);
}
