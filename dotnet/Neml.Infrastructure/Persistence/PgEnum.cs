// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later

using System.Reflection;
using System.Text.Json.Serialization;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;

namespace Neml.Infrastructure.Persistence;

/// <summary>
/// Maps a domain enum to the exact text its section 7 CHECK constraint allows. The value
/// comes from [JsonStringEnumMemberName], the very attribute the JSON wire format uses, so
/// the column, the CHECK and the mobile client can never drift apart. Integer ordinals are
/// never involved: these are text columns.
/// </summary>
internal static class PgEnum
{
    public static string Value<T>(T member) where T : struct, Enum =>
        typeof(T).GetField(member.ToString())?.GetCustomAttribute<JsonStringEnumMemberNameAttribute>()?.Name
        ?? throw new InvalidOperationException($"{typeof(T).Name}.{member} is missing [JsonStringEnumMemberName]");

    public static ValueConverter<T, string> Converter<T>() where T : struct, Enum
    {
        var toDb = Enum.GetValues<T>().ToDictionary(v => v, v => Value(v));
        var fromDb = toDb.ToDictionary(p => p.Value, p => p.Key);
        return new ValueConverter<T, string>(v => toDb[v], s => fromDb[s]);
    }

    /// <summary>Renders the CHECK body, e.g. <c>status IN ('draft','testing','active','deprecated')</c>.</summary>
    public static string Check<T>(string column) where T : struct, Enum =>
        $"{column} IN ({string.Join(",", Enum.GetValues<T>().Select(v => $"'{Value(v)}'"))})";
}
