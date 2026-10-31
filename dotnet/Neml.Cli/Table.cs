// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Text;

namespace Neml.Cli;

/// <summary>Fixed-width console table. No dependency earns its keep for this.</summary>
public static class Table
{
    public static string Render(IReadOnlyList<string> headers, IReadOnlyList<string?[]> rows)
    {
        var widths = headers.Select(h => h.Length).ToArray();
        foreach (var row in rows)
        {
            for (var i = 0; i < widths.Length; i++)
            {
                widths[i] = Math.Max(widths[i], Cell(row, i).Length);
            }
        }

        var output = new StringBuilder();
        AppendRow(output, headers.ToArray(), widths);
        output.AppendLine(string.Join("  ", widths.Select(w => new string('-', w))));
        foreach (var row in rows)
        {
            AppendRow(output, row, widths);
        }

        return output.ToString();
    }

    private static void AppendRow(StringBuilder output, string?[] row, int[] widths)
    {
        var cells = widths.Select((w, i) => Cell(row, i).PadRight(w));
        output.AppendLine(string.Join("  ", cells).TrimEnd());
    }

    private static string Cell(string?[] row, int index) =>
        index < row.Length ? row[index] ?? "-" : "-";
}
