// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Globalization;

namespace Neml.Web;

/// <summary>Pure view logic, kept out of the .razor files so it can be unit tested.</summary>
public static class ViewLogic
{
    // §12.5 tolerances, identical to the mobile screen.
    public const double DimToleranceMm = 0.3;
    public const double MassToleranceRatio = 0.05;
    public const double WarpLimitMm = 0.5;

    /// <summary>SVG polyline points for a series, scaled into width x height. Empty series gives "".</summary>
    public static string Polyline(IReadOnlyList<double> values, double width, double height)
    {
        if (values.Count == 0)
        {
            return "";
        }

        var min = values.Min();
        var span = Math.Max(values.Max() - min, 1e-9);
        var step = values.Count == 1 ? 0 : width / (values.Count - 1);
        return string.Join(' ', values.Select((v, i) =>
            FormattableString.Invariant($"{i * step:0.##},{height - ((v - min) / span * height):0.##}")));
    }

    /// <summary>Screen 12 tabs and the text filter. "audit" shows everything.</summary>
    public static IEnumerable<AuditEntry> FilterAudit(IEnumerable<AuditEntry> entries, string tab, string query)
    {
        var needle = query.Trim();
        return entries.Where(e =>
            (tab == "audit" || (tab == "tools" && e.IsToolCall) || (tab == "errors" && e.IsError))
            && (needle.Length == 0
                || e.Actor.Contains(needle, StringComparison.OrdinalIgnoreCase)
                || e.Action.Contains(needle, StringComparison.OrdinalIgnoreCase)
                || (e.Target?.Contains(needle, StringComparison.OrdinalIgnoreCase) ?? false)));
    }

    public static bool? DimOk(double? measured, double? nominal) =>
        measured is null || nominal is null ? null : Math.Abs(measured.Value - nominal.Value) <= DimToleranceMm + 1e-9;

    public static bool? MassOk(double? measured, double? nominal) =>
        measured is null || nominal is not > 0 ? null
            : Math.Abs(measured.Value - nominal.Value) <= nominal.Value * MassToleranceRatio + 1e-9;

    public static bool? WarpOk(double? warp) => warp is null ? null : warp.Value <= WarpLimitMm + 1e-9;

    /// <summary>Parses a decimal typed in either "1.5" or "1,5" form.</summary>
    public static double? Number(string? text) =>
        double.TryParse(text?.Trim().Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out var v)
        && double.IsFinite(v)
            ? v
            : null;
}
